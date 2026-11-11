"""
(Phase 7) Escalation Agent: Rule-based & LLM-assisted complaint, allergy, food-safety,
abuse, and human-handoff detector mirrored against `internal/hr/bot-escalation-rules.md`.
"""

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from app.config import settings
from app.db.order_repo import OrderRepo, order_repo
from app.llm.client import llm_client
from app.services import clock
from app.services.branch_repo import BranchRepo, branch_repo
from app.services.notifier import NotifierService, notifier
from app.state.session import Session

log = logging.getLogger("brain.escalation")

# Mirrors every trigger phrase in `data/knowledge/internal/hr/bot-escalation-rules.md`:
# "The bot hands over when a customer makes a complaint; asks for a refund or compensation;
#  mentions a severe allergy or illness after eating; is abusive or very frustrated;
#  asks for the manager; or when the bot fails three times in a row."
BOT_ESCALATION_RULES_CLAUSES: Dict[str, str] = {
    "makes a complaint": "complaint",
    "asks for a refund or compensation": "refund_or_compensation",
    "mentions a severe allergy": "severe_allergy",
    "illness after eating": "food_safety_or_illness",
    "is abusive or very frustrated": "abusive_or_frustrated",
    "asks for the manager": "manager_or_human_request",
    "fails three times in a row": "repeated_failures",
}

CRITICAL_CATEGORIES = {"severe_allergy", "food_safety_or_illness"}

_CATEGORY_PATTERNS: Dict[str, List[re.Pattern]] = {
    "severe_allergy": [
        re.compile(
            r"\b(severe\s+allerg\w*|anaphylax\w*|epipen|allergic\s+reaction|life[\s-]*threatening\s+allerg\w*)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(allerg(?:y|ic)\s+to\s+(?:nuts?|peanuts?|shellfish|dairy|gluten|soy|eggs?))\b.*\b(100%\s+safe|guaranteed\s+safe|completely\s+safe|safe\s+for\s+me|severe)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(100%\s+safe|guaranteed\s+safe|completely\s+safe)\b.*\b(allerg(?:y|ic)|nut|peanut)\b",
            re.IGNORECASE,
        ),
    ],
    "food_safety_or_illness": [
        re.compile(
            r"\b(food\s+poisoning|sick\s+after\s+eating|illness\s+after\s+eating|fell\s+ill|got\s+sick\s+from|vomiting|stomach\s+ache\s+after|diarrh\w+|spoiled|rotten|moldy|mouldy|undercooked|raw\s+chicken|hair\s+in\s+my|plastic\s+in\s+my|glass\s+in\s+my|foreign\s+object|food\s+safety)\b",
            re.IGNORECASE,
        ),
    ],
    "refund_or_compensation": [
        re.compile(
            r"\b(want\s+a\s+refund|need\s+a\s+refund|give\s+me\s+a\s+refund|demand\s+a\s+refund|money\s+back|compensation|compensate\s+me|reimburse\w*|overcharged|charged\s+twice|double\s+charged)\b",
            re.IGNORECASE,
        ),
    ],
    "complaint": [
        re.compile(
            r"\b(make\s+a\s+complaint|file\s+a\s+complaint|have\s+a\s+complaint|want\s+to\s+complain|cold\s+pizza|burnt\s+pizza|wrong\s+pizza|wrong\s+order|missing\s+item|never\s+arrived|still\s+hasn't\s+arrived|rider\s+was\s+rude|rider\s+misconduct|terrible\s+quality|horrible\s+food)\b",
            re.IGNORECASE,
        ),
    ],
    "abusive_or_frustrated": [
        re.compile(
            r"\b(stupid\s+bot|useless\s+bot|idiot|moron|pathetic\s+service|worst\s+service\s+ever|furious|fed\s+up\s+with\s+this|what\s+the\s+hell|screw\s+you|shut\s+up|garbage\s+bot|trash\s+service)\b",
            re.IGNORECASE,
        ),
    ],
    "manager_or_human_request": [
        re.compile(
            r"\b(speak\s+to\s+(?:a\s+|the\s+)?manager|talk\s+to\s+(?:a\s+|the\s+)?manager|branch\s+manager|area\s+manager|connect\s+me\s+to\s+(?:a\s+)?(?:human|staff|agent|person|manager)|talk\s+to\s+(?:a\s+)?(?:human|real\s+person|staff|representative|agent)|human\s+agent)\b",
            re.IGNORECASE,
        ),
    ],
}

# Representative test phrases for every clause in bot-escalation-rules.md
CATEGORY_SAMPLE_PHRASES: Dict[str, str] = {
    "complaint": "I want to make a complaint because you sent a cold pizza and wrong order.",
    "refund_or_compensation": "I was overcharged and I want a refund and compensation right now.",
    "severe_allergy": "I have a severe allergy to peanuts and anaphylaxis, is your kitchen 100% safe?",
    "food_safety_or_illness": "I got food poisoning and illness after eating your pizza last night.",
    "abusive_or_frustrated": "This is a useless bot and the worst service ever, I am furious!",
    "manager_or_human_request": "Let me speak to the manager or a human agent immediately.",
}


class EscalationDecision(BaseModel):
    escalate: bool = False
    reason: str = ""
    category: str = "none"
    is_critical: bool = False


class EscalationAgent:
    def __init__(self, enable_llm_classifier: bool = False):
        self.enable_llm_classifier = enable_llm_classifier

    def evaluate(
        self,
        message: str,
        session: Optional[Session] = None,
    ) -> EscalationDecision:
        """
        Evaluates whether a customer message or session failure state requires human handoff.
        1. Checks consecutive_failures >= 3 first.
        2. Checks fast deterministic regex rules across all 6 text trigger categories.
        3. Optionally invokes small LLM classifier for ambiguous frustration.
        """
        if session is not None and session.consecutive_failures >= 3:
            return EscalationDecision(
                escalate=True,
                reason="Bot failed three times in a row (consecutive_failures >= 3).",
                category="repeated_failures",
                is_critical=False,
            )

        text = (message or "").strip()
        if not text:
            return EscalationDecision(escalate=False)

        # Priority order: critical categories (severe_allergy, food_safety_or_illness) first
        ordered_categories = [
            "severe_allergy",
            "food_safety_or_illness",
            "refund_or_compensation",
            "complaint",
            "abusive_or_frustrated",
            "manager_or_human_request",
        ]

        for category in ordered_categories:
            for pattern in _CATEGORY_PATTERNS.get(category, []):
                match = pattern.search(text)
                if match:
                    matched_str = match.group(0)
                    return EscalationDecision(
                        escalate=True,
                        reason=f"Customer triggered {category} rule ('{matched_str}').",
                        category=category,
                        is_critical=(category in CRITICAL_CATEGORIES),
                    )

        if self.enable_llm_classifier and self._looks_ambiguously_frustrated(text):
            return self._classify_with_llm(text)

        return EscalationDecision(escalate=False)

    def _looks_ambiguously_frustrated(self, text: str) -> bool:
        lower = text.lower()
        frustration_hints = ("ridiculous", "unacceptable", "disappointed", "angry", "waste of time", "not working")
        return any(h in lower for h in frustration_hints)

    def _classify_with_llm(self, text: str) -> EscalationDecision:
        system = (
            "You are an escalation classifier for a Pizza Hut WhatsApp assistant. "
            'Return strict JSON: {"escalate": bool, "reason": str, "category": "abusive_or_frustrated" | "complaint" | "none"}.'
        )
        try:
            resp = llm_client.complete(
                system=system,
                messages=[{"role": "user", "content": text}],
                model=settings.SUBAGENT_MODEL,
                temperature=0.0,
                max_tokens=80,
            )
            data = json.loads(resp.text.strip())
            if data.get("escalate"):
                cat = data.get("category") or "abusive_or_frustrated"
                return EscalationDecision(
                    escalate=True,
                    reason=data.get("reason") or "Customer frustration detected by classifier.",
                    category=cat,
                    is_critical=(cat in CRITICAL_CATEGORIES),
                )
        except Exception as exc:
            log.warning("LLM frustration classifier fallback skipped: %s", exc)
        return EscalationDecision(escalate=False)

    def _is_branch_or_system_open(
        self, session: Session, branches: BranchRepo
    ) -> bool:
        mode = session.fulfilment or "delivery"
        if session.branch_id:
            return branches.is_open(session.branch_id, mode=mode)
        return any(branches.is_open(b.id, mode=mode) for b in branches.list_branches())

    def execute_handoff(
        self,
        session: Session,
        reason: str,
        category: str = "general",
        is_critical: Optional[bool] = None,
        latest_user_message: Optional[str] = None,
        orders: OrderRepo = order_repo,
        branches: BranchRepo = branch_repo,
        notify_svc: NotifierService = notifier,
        now_dt: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Transitions the session into `stage="handoff"` for 2 hours, persists a `Handoff` DB record,
        notifies the branch staff (and Area Manager for critical cases or unassigned branch),
        and returns an opening-hours-aware customer response.
        """
        current = clock.now(now_dt)
        critical = is_critical if is_critical is not None else (category in CRITICAL_CATEGORIES)

        session.stage = "handoff"
        session.handoff_until = current + timedelta(hours=settings.HANDOFF_DURATION_HOURS)
        session.consecutive_failures = 0

        handoff_record = orders.create_handoff(
            user_id=session.user_id,
            reason=reason,
            branch_id=session.branch_id,
            now_dt=current,
        )

        notified_jids = notify_svc.notify_handoff(
            session=session,
            reason=reason,
            category=category,
            is_critical=critical,
            latest_user_message=latest_user_message,
        )

        is_open_now = self._is_branch_or_system_open(session, branches)
        if is_open_now:
            customer_reply = (
                "I'm really sorry about that. I've shared your details with our team, "
                "and a staff member will get back to you shortly (within 30 minutes) 🙏"
            )
        else:
            customer_reply = (
                "I'm really sorry about that. Our outlets are currently closed, "
                "so I've logged your case for our team and a staff member will respond tomorrow morning by 11:00 🙏"
            )

        return {
            "ok": True,
            "data": {
                "handoff_id": handoff_record.id,
                "stage": session.stage,
                "branch_id": session.branch_id,
                "category": category,
                "is_critical": critical,
                "is_open_now": is_open_now,
                "handoff_until": session.handoff_until.isoformat(),
                "notified_jids": notified_jids,
                "customer_reply": customer_reply,
            },
        }

    async def run(self, message: str, context: dict) -> str:
        session = context.get("session")
        if session:
            decision = self.evaluate(message, session=session)
            res = self.execute_handoff(
                session=session,
                reason=decision.reason or "Customer requested assistance",
                category=decision.category,
                is_critical=decision.is_critical,
                latest_user_message=message,
            )
            return res["data"]["customer_reply"]
        return "Our team will get back to you shortly 🙏"


escalation_agent = EscalationAgent()


def escalation_handoff_tool(
    session: Session,
    reason: str,
    category: str = "general",
) -> Dict[str, Any]:
    """Tool wrapper exposed to the Orchestrator as `escalation.handoff`."""
    return escalation_agent.execute_handoff(
        session=session,
        reason=reason,
        category=category,
    )
