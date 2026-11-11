"""
(Phase 7) Staff & Customer Notification Service.
Routes handoff alerts, new order notifications, and order status updates via the
Gateway internal server (`POST /send` with `X-Internal-Secret`).
Failures are logged with retries and NEVER block or fail customer replies.
"""

import json
import logging
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Set

from app.config import settings
from app.db.models import Order
from app.services import pricing
from app.state.session import Session

log = logging.getLogger("brain.notifier")


class NotifierService:
    def __init__(self):
        self.sent_events: List[Dict[str, Any]] = []
        self._notified_orders: Set[str] = set()
        self._transport: Optional[Callable[[str, str], bool]] = None

    def set_transport(self, transport: Optional[Callable[[str, str], bool]]) -> None:
        """Allows tests to inject a custom transport or failure simulator."""
        self._transport = transport

    def clear_events(self) -> None:
        self.sent_events.clear()
        self._notified_orders.clear()

    def _default_http_send(self, jid: str, text: str) -> bool:
        url = f"{settings.GATEWAY_INTERNAL_URL.rstrip('/')}/send"
        payload = json.dumps({"jid": jid, "text": text}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-Internal-Secret": settings.INTERNAL_SECRET,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            return 200 <= resp.status < 300

    def send_whatsapp(
        self,
        jid: str,
        text: str,
        event_type: str = "generic",
        branch_id: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
        retries: int = 2,
    ) -> bool:
        """
        Sends an outbound WhatsApp message via Gateway internal server with retries.
        Never raises an exception to the caller.
        """
        event_record = {
            "jid": jid,
            "text": text,
            "event_type": event_type,
            "branch_id": branch_id,
            "meta": meta or {},
            "delivered": False,
        }
        self.sent_events.append(event_record)

        sender_fn = self._transport or self._default_http_send
        for attempt in range(1, retries + 2):
            try:
                ok = sender_fn(jid, text)
                if ok:
                    event_record["delivered"] = True
                    return True
            except Exception as exc:
                log.warning(
                    "Notifier attempt %d/%d failed for jid=%s event=%s: %s",
                    attempt,
                    retries + 1,
                    jid,
                    event_type,
                    exc,
                )
        return False

    def resolve_staff_jids(
        self, branch_id: Optional[str], is_critical: bool = False
    ) -> List[str]:
        """
        Determines which staff JID(s) should receive a notification:
        - Uses branch_id if known, else 'area' manager.
        - Critical cases (food safety, illness, severe allergy) notify BOTH the branch (if known)
          and the 'area' manager.
        """
        jids_map = settings.STAFF_NOTIFY_JIDS
        targets: List[str] = []

        if branch_id and branch_id in jids_map:
            targets.append(jids_map[branch_id])
        elif "area" in jids_map:
            targets.append(jids_map["area"])

        if is_critical and "area" in jids_map:
            area_jid = jids_map["area"]
            if area_jid not in targets:
                targets.append(area_jid)

        return targets

    def notify_handoff(
        self,
        session: Session,
        reason: str,
        category: str = "general",
        is_critical: bool = False,
        latest_user_message: Optional[str] = None,
    ) -> List[str]:
        """
        Formats and dispatches a staff handoff alert containing:
        - Customer user_id
        - Reason & category
        - Last 5 messages
        - Current cart summary (if any)
        Returns the list of notified staff JIDs.
        """
        recent = list(session.history[-5:])
        if latest_user_message and (
            not recent or recent[-1].get("content") != latest_user_message
        ):
            recent = (recent + [{"role": "user", "content": latest_user_message}])[-5:]

        history_lines = [
            f"  - {m.get('role', 'user')}: {m.get('content', '')}" for m in recent
        ] or ["  (no prior messages)"]

        if session.cart:
            sub = pricing.subtotal(session.cart)
            cart_lines = [
                f"  - {line.qty}x {line.item_id} ({line.size})" for line in session.cart
            ]
            cart_summary = "\n".join(cart_lines) + f"\n  Subtotal: LKR {sub:,}"
        else:
            cart_summary = "  (empty)"

        header = "🚨 *CRITICAL ESCALATION ALERT*" if is_critical else "⚠️ *CUSTOMER HANDOFF ALERT*"
        alert_text = (
            f"{header}\n"
            f"Customer: {session.user_id}\n"
            f"Branch: {session.branch_id or 'unassigned (routed to Area Manager)'}\n"
            f"Category: {category}\n"
            f"Reason: {reason}\n\n"
            f"*Last {len(history_lines)} message(s):*\n"
            + "\n".join(history_lines)
            + f"\n\n*Current Cart:*\n{cart_summary}\n\n"
            f"Reply `/resume {session.user_id}` when resolved."
        )

        target_jids = self.resolve_staff_jids(session.branch_id, is_critical=is_critical)
        for jid in target_jids:
            self.send_whatsapp(
                jid=jid,
                text=alert_text,
                event_type="handoff",
                branch_id=session.branch_id or "area",
                meta={
                    "user_id": session.user_id,
                    "reason": reason,
                    "category": category,
                    "is_critical": is_critical,
                },
            )
        return target_jids

    def forward_customer_message(self, session: Session, text: str) -> None:
        """Forwards a customer message sent during active handoff to the assigned staff."""
        target_jids = self.resolve_staff_jids(session.branch_id, is_critical=False)
        msg_text = (
            f"💬 *Follow-up from {session.user_id}* (in handoff):\n"
            f"{text}\n\n"
            f"Reply `/resume {session.user_id}` to return customer to bot."
        )
        for jid in target_jids:
            self.send_whatsapp(
                jid=jid,
                text=msg_text,
                event_type="handoff_followup",
                branch_id=session.branch_id or "area",
                meta={"user_id": session.user_id},
            )

    def notify_new_order(self, order: Order, one_line_summary: str) -> bool:
        """
        Notifies the order's branch staff exactly once when a new order is placed.
        """
        if order.order_no in self._notified_orders:
            return False
        self._notified_orders.add(order.order_no)

        branch_jid = settings.STAFF_NOTIFY_JIDS.get(
            order.branch_id, settings.STAFF_NOTIFY_JIDS.get("area", "")
        )
        if not branch_jid:
            return False

        item_lines = [
            f"  - {it.qty}x {it.name_snapshot} ({it.size}) = LKR {it.line_total:,}"
            for it in order.items
        ]
        staff_msg = (
            f"🍕 *NEW ORDER: {order.order_no}* ({order.branch_id})\n"
            f"Summary: {one_line_summary}\n"
            f"Customer: {order.user_id}\n"
            f"Fulfilment: {order.fulfilment.upper()}"
            + (f" — {order.address}" if order.address else "")
            + "\n*Items:*\n"
            + "\n".join(item_lines)
            + f"\nTotal: *LKR {order.total:,}*\n"
            f"Update status with: `/status {order.order_no} accepted`"
        )

        return self.send_whatsapp(
            jid=branch_jid,
            text=staff_msg,
            event_type="new_order",
            branch_id=order.branch_id,
            meta={"order_no": order.order_no, "user_id": order.user_id, "total": order.total},
        )

    def notify_customer_order_status(self, order: Order, customer_text: str) -> bool:
        """Sends an order status update notification to the customer."""
        if not order.user_id:
            return False
        return self.send_whatsapp(
            jid=order.user_id,
            text=customer_text,
            event_type="order_status_update",
            branch_id=order.branch_id,
            meta={
                "order_no": order.order_no,
                "status": order.status.value,
                "user_id": order.user_id,
            },
        )


notifier = NotifierService()

