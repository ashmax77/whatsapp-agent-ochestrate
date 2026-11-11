"""
(Phase 7) Post-Order Agent & Branch-Scoped Staff Command Handler.
Handles:
- One-line order summary generation & exact-once branch notification on order placement.
- Customer notifications on order status transitions (`accepted`, `preparing`, `out_for_delivery`, `ready_for_pickup`, `completed`, `cancelled`).
- Authenticated, branch-scoped staff commands (`/orders`, `/status <order_no> <status>`, `/resume <user_id>`).
"""

import logging
from typing import Dict, Optional

from app.config import settings
from app.db.models import Order, OrderStatus
from app.db.order_repo import OrderRepo, order_repo
from app.services.branch_repo import branch_repo
from app.services.notifier import NotifierService, notifier

log = logging.getLogger("brain.post_order")


def _clean_phone(value: str) -> str:
    raw = (value or "").strip()
    if "@" in raw:
        raw = raw.split("@", 1)[0]
    return "".join(ch for ch in raw if ch.isdigit())


class PostOrderAgent:
    def summarize_order_one_line(self, order: Order) -> str:
        """Creates a concise one-line order summary for branch staff notifications."""
        items_part = ", ".join(
            f"{it.qty}x {it.name_snapshot} ({it.size})" for it in order.items
        )
        dest_part = (
            f"Delivery to {order.address}"
            if order.fulfilment == "delivery" and order.address
            else f"Pickup ({order.branch_id})"
        )
        return f"{items_part} | {dest_part} | LKR {order.total:,}"

    def on_order_placed(
        self, order: Order, notify_svc: NotifierService = notifier
    ) -> bool:
        """
        Triggered after `order.place_order` succeeds.
        Sends the formatted order with its one-line summary to the order's branch staff
        exactly once. Failures are logged inside notifier and never break order placement.
        """
        summary_line = self.summarize_order_one_line(order)
        return notify_svc.notify_new_order(order, summary_line)

    def format_status_message(self, order: Order) -> str:
        """Formats the customer-facing WhatsApp status notification for an order."""
        branch = branch_repo.get_branch(order.branch_id)
        branch_name = branch.name if branch else order.branch_id

        status_templates: Dict[OrderStatus, str] = {
            OrderStatus.NEW: f"Your order *{order.order_no}* has been received at {branch_name} 🍕",
            OrderStatus.ACCEPTED: f"Good news! Your order *{order.order_no}* has been accepted by our {branch_name} kitchen 🍕",
            OrderStatus.PREPARING: f"Your order *{order.order_no}* is now being freshly prepared in the oven! 🔥",
            OrderStatus.OUT_FOR_DELIVERY: (
                f"Your order *{order.order_no}* is out for delivery to {order.address or 'your address'}! 🛵"
            ),
            OrderStatus.READY_FOR_PICKUP: (
                f"Your order *{order.order_no}* is hot and ready for pickup at our {branch_name} outlet! 🎉"
            ),
            OrderStatus.COMPLETED: f"Your order *{order.order_no}* is completed. Enjoy your meal! 🍕",
            OrderStatus.CANCELLED: (
                f"Your order *{order.order_no}* has been cancelled. If you need help, please reply here 🙏"
            ),
        }
        return status_templates.get(
            order.status,
            f"Update on your order *{order.order_no}*: status is now *{order.status.value}*.",
        )

    def get_staff_role(self, sender_user_id: str) -> Optional[str]:
        """
        Checks if `sender_user_id` is in `settings.STAFF_NOTIFY_JIDS`.
        Returns the staff scope ('area', 'colombo07', 'nugegoda', 'kandy') or None if not staff.
        """
        sender_clean = _clean_phone(sender_user_id)
        if not sender_clean:
            return None

        # Check 'area' first so area manager has full privileges if mapped
        area_jid = _clean_phone(settings.STAFF_NOTIFY_JIDS.get("area", ""))
        if area_jid and sender_clean == area_jid:
            return "area"

        for scope, configured_jid in settings.STAFF_NOTIFY_JIDS.items():
            if scope == "area":
                continue
            if _clean_phone(configured_jid) == sender_clean:
                return scope

        return None

    async def handle_staff_command(
        self,
        sender_user_id: str,
        raw_text: str,
        store,
        orders: OrderRepo = order_repo,
        notify_svc: NotifierService = notifier,
    ) -> Optional[str]:
        """
        Processes `/orders`, `/status <order_no> <status>`, and `/resume <user_id>` commands
        strictly from authorized numbers in `STAFF_NOTIFY_JIDS`, enforcing branch scoping.
        Returns None if the sender is not a staff number or text is not a staff command.
        """
        role = self.get_staff_role(sender_user_id)
        if role is None:
            return None

        text = (raw_text or "").strip()
        if not text.startswith("/"):
            return None

        parts = text.split()
        cmd = parts[0].lower()

        if cmd == "/orders":
            scope_branch = None if role == "area" else role
            recent = orders.list_recent_orders(branch_id=scope_branch, limit=10)
            if not recent:
                return f"📋 No recent orders found for scope '{role}'."
            lines = [f"📋 *Recent Orders ({role}):*"]
            for o in recent:
                lines.append(
                    f"- *{o.order_no}* [{o.branch_id}] {o.status.value} | {o.fulfilment} | LKR {o.total:,} (user: {o.user_id})"
                )
            return "\n".join(lines)

        if cmd == "/status":
            if len(parts) < 3:
                return "Usage: `/status <order_no> <accepted|preparing|out_for_delivery|ready_for_pickup|completed|cancelled>`"

            order_no = parts[1].strip().upper()
            status_raw = parts[2].strip().lower()

            existing = orders.get_order_by_no(order_no)
            if not existing:
                return f"❌ Order '{order_no}' not found."

            # Enforce per-branch isolation: a Kandy staff number cannot modify a Nugegoda order
            if role != "area" and existing.branch_id != role:
                return (
                    f"⛔ Access denied: Order {existing.order_no} belongs to branch '{existing.branch_id}', "
                    f"and your staff number is scoped to '{role}'."
                )

            try:
                new_status = OrderStatus(status_raw)
            except ValueError:
                valid_vals = ", ".join(s.value for s in OrderStatus)
                return f"❌ Invalid status '{status_raw}'. Valid statuses: {valid_vals}"

            updated = orders.update_order_status(order_no, new_status)
            if not updated:
                return f"❌ Failed to update order '{order_no}'."

            customer_msg = self.format_status_message(updated)
            notify_svc.notify_customer_order_status(updated, customer_msg)
            return (
                f"✅ Order *{updated.order_no}* ({updated.branch_id}) updated to *{updated.status.value}*. "
                f"Customer {updated.user_id} has been notified."
            )

        if cmd == "/resume":
            if len(parts) < 2:
                return "Usage: `/resume <user_id>`"

            target_user_id = parts[1].strip()
            async with store.lock(target_user_id):
                target_session = await store.get(target_user_id)
                if (
                    role != "area"
                    and target_session.branch_id
                    and target_session.branch_id != role
                ):
                    return (
                        f"⛔ Access denied: Customer {target_user_id} is assigned to branch '{target_session.branch_id}', "
                        f"and your staff number is scoped to '{role}'."
                    )

                target_session.stage = "browsing"
                target_session.handoff_until = None
                target_session.consecutive_failures = 0
                await store.save(target_session)

            resolved_count = orders.resolve_handoffs_for_user(target_user_id)
            return (
                f"✅ Resumed bot for customer *{target_user_id}* "
                f"(resolved {resolved_count} open handoff record(s))."
            )

        return "Unknown staff command. Available commands: `/orders`, `/status <order_no> <status>`, `/resume <user_id>`"

    async def run(self, message: str, context: dict) -> str:
        session = context.get("session")
        if session and session.last_order_no:
            order = order_repo.get_order_by_no(session.last_order_no)
            if order:
                return self.format_status_message(order)
        return "Please share your order number (e.g. PH-YYYYMMDD-0001) to check your order status."


post_order_agent = PostOrderAgent()
