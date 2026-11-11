"""
Action-claim guard.

The orchestrator LLM sometimes *says* it did something ("Added garlic bread",
"Applied promo STUDENT15", "Order placed! Order No: 1001") without calling the
tool that actually does it. State then silently disagrees with what the customer
was told. This module detects such claims deterministically so the orchestrator
can force a real tool call or fall back to an honest reply.

Everything here is pure (no I/O) so it can be unit-tested exhaustively.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Pattern, Set

# claim type -> tools of which at least one must have succeeded *this turn*
CLAIM_REQUIRED_TOOLS: Dict[str, Set[str]] = {
    "cart_add": {"cart.add_item", "cart.add_combo", "cart.update_item"},
    "cart_update": {
        "cart.update_item", "cart.add_item", "cart.add_combo", "cart.remove_item",
        "cart.clear", "delivery.set_address", "order.set_fulfilment",
        "order.set_pickup", "promo.apply", "promo.remove",
    },
    "cart_remove": {"cart.remove_item", "cart.clear", "order.cancel_draft", "promo.remove"},
    "promo_applied": {"promo.apply"},
    "order_placed": {"order.place_order"},
}

CLAIM_LABELS: Dict[str, str] = {
    "cart_add": "added an item to the cart",
    "cart_update": "updated the order",
    "cart_remove": "removed something from the cart",
    "promo_applied": "applied a promo code",
    "order_placed": "placed the order",
}

_S = r"[^.!?\n]"  # same-sentence filler

CLAIM_PATTERNS: Dict[str, List[Pattern]] = {
    "cart_add": [
        re.compile(rf"\badded\b(?!{_S}{{0,25}}\b(?:address|location|promo|code|discount|note)\b)", re.I),
    ],
    "cart_update": [
        re.compile(r"\b(?:updated|adjusted|modified)\b", re.I),
        re.compile(r"\bchanged\s+(?:it\s+|that\s+|the\s+\w+\s+)?(?:to|quantity|qty|size)\b", re.I),
    ],
    "cart_remove": [
        re.compile(r"\b(?:removed|deleted|cleared)\b", re.I),
    ],
    "promo_applied": [
        re.compile(rf"\bapplied\b{_S}{{0,30}}\b(?:promo|code|discount|student15|friday10)\b", re.I),
        re.compile(rf"\b(?:promo|code|discount|student15|friday10)\b{_S}{{0,30}}\bapplied\b", re.I),
        re.compile(rf"\bapplied\b{_S}*\d+\s*%", re.I),
    ],
    "order_placed": [
        re.compile(r"\border\s+(?:is\s+|has\s+been\s+)?(?:placed|confirmed)\b", re.I),
        re.compile(r"\bplaced\s+(?:your|the)\s+order\b", re.I),
        re.compile(r"\byour\s+order\s+(?:is|has\s+been)\s+(?:placed|confirmed)\b", re.I),
    ],
}

# Wording that makes the sentence a question/condition/future rather than a claim
_NON_CLAIM_PREFIX = re.compile(
    r"\b(?:not|never|unable|if|once|until|before|will|would|can|could|should|want|like|need|to\s+be|when)\b|n['’]t\b",
    re.I,
)

ORDER_NO_PATTERNS: List[Pattern] = [
    re.compile(r"\bPH-\d{8}-\d{4}\b", re.I),
    re.compile(r"\border\s*(?:no\.?|number|num|#)\s*(?:is\s+)?[:#]?\s*([A-Za-z0-9][A-Za-z0-9\-]*)", re.I),
]


@dataclass
class ClaimReport:
    unsupported: List[str] = field(default_factory=list)  # claim types lacking a successful tool call
    fabricated_order_numbers: List[str] = field(default_factory=list)
    unverified_prices: List[int] = field(default_factory=list)

    @property
    def has_problem(self) -> bool:
        return bool(self.unsupported or self.fabricated_order_numbers or self.unverified_prices)

    @property
    def needs_tool_call(self) -> bool:
        """True when the model claimed something that only a tool call can make true."""
        return bool(self.unsupported or self.fabricated_order_numbers)


def _sentence_prefix(text: str, start: int) -> str:
    """Text from the beginning of the sentence containing `start` up to `start`."""
    cut = max(text.rfind(ch, 0, start) for ch in ".!?\n")
    return text[cut + 1:start]


def detect_claims(reply: str) -> Set[str]:
    """Returns the set of affirmative action-claim types asserted in `reply`."""
    found: Set[str] = set()
    if not reply:
        return found
    for claim, patterns in CLAIM_PATTERNS.items():
        for pat in patterns:
            for m in pat.finditer(reply):
                prefix = _sentence_prefix(reply, m.start())[-30:]
                # Negations/conditionals may sit before the match ("can't be applied" is inside it)
                if _NON_CLAIM_PREFIX.search(prefix) or _NON_CLAIM_PREFIX.search(m.group(0)):
                    continue
                found.add(claim)
                break
            if claim in found:
                break
    return found


def extract_order_numbers(reply: str) -> List[str]:
    """Order numbers mentioned in `reply` (PH-YYYYMMDD-NNNN or 'Order No: X')."""
    nums: List[str] = []
    if not reply:
        return nums
    for pat in ORDER_NO_PATTERNS:
        for m in pat.finditer(reply):
            token = (m.group(1) if m.groups() else m.group(0)).strip().upper()
            # real order numbers always contain digits; ignores filler words such as "is" / "confirmed"
            if token and any(ch.isdigit() for ch in token) and token not in nums:
                nums.append(token)
    return nums


def normalize_tool_name(name: str) -> str:
    return (name or "").replace("__", ".").strip()


def check_reply(
    reply: str,
    ok_tools: Iterable[str],
    valid_order_nos: Iterable[str] = (),
) -> ClaimReport:
    """
    ok_tools: names of tools that returned ok=True during this turn.
    valid_order_nos: order numbers that genuinely exist (this turn's place_order result,
                     or session.last_order_no).
    """
    ok = {normalize_tool_name(t) for t in ok_tools}
    valid = {str(n).strip().upper() for n in valid_order_nos if n}
    report = ClaimReport()

    mentioned = extract_order_numbers(reply)
    references_real_order = any(n in valid for n in mentioned)

    for claim in sorted(detect_claims(reply)):
        if CLAIM_REQUIRED_TOOLS[claim] & ok:
            continue
        # Talking about a genuinely existing order ("your order PH-... is confirmed") is not a new claim
        if claim == "order_placed" and references_real_order:
            continue
        report.unsupported.append(claim)

    for num in mentioned:
        if num not in valid:
            report.fabricated_order_numbers.append(num)

    return report


def correction_message(report: ClaimReport) -> str:
    """Instruction appended to the conversation to force a real tool call."""
    parts: List[str] = []
    if report.unsupported:
        claimed = ", ".join(CLAIM_LABELS[c] for c in report.unsupported)
        parts.append(
            f"Your previous reply claimed you {claimed}, but no matching tool call succeeded, "
            "so NOTHING has changed."
        )
    if report.fabricated_order_numbers:
        parts.append(
            "Your previous reply mentioned an order number that does not exist "
            f"({', '.join(report.fabricated_order_numbers)}). Order numbers only come from a successful order.place_order."
        )
    if report.unverified_prices:
        prices = ", ".join(f"LKR {p:,}" for p in report.unverified_prices)
        parts.append(
            f"Your previous reply quoted prices that no tool returned ({prices}). "
            "Prices must come from tool results (menu.get_item, menu.list_items, kb.ask, cart.view, order.show_summary)."
        )
    if report.needs_tool_call:
        parts.append(
            "Call the correct tool now using the CURRENT SESSION STATE, then reply based only on the tool result. "
            "Never state that an action is done unless its tool returned ok."
        )
    else:
        parts.append(
            "Re-answer using only figures from tool results (call a read-only tool such as menu.get_item, "
            "kb.ask or cart.view if you need one) or leave the price out. "
            "Do NOT repeat any action that already succeeded."
        )
    return "[SYSTEM CHECK] " + " ".join(parts)


def safe_fallback(report: ClaimReport, stage: str = "browsing") -> str:
    """Honest reply used when the model still cannot back its claim with a tool call."""
    if "order_placed" in report.unsupported or report.fabricated_order_numbers:
        if stage == "confirming":
            return "I haven't placed your order yet. Please reply YES to confirm the summary above and I'll place it."
        return "I haven't placed an order yet. Let me know what you'd like and I'll get it ready for you 🍕"
    return "Sorry, I couldn't complete that just now, so nothing has been changed. Could you please say it again?"
