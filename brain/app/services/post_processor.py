import re
import logging
from typing import Any, Dict, List, Optional, Set
from app.state.session import Session
from app.services.menu_repo import menu_repo
from app.services import pricing

log = logging.getLogger("brain.post_processor")

PRICE_REGEX = re.compile(r"(?:LKR|Rs\.?)\s*([\d,]{2,})", re.IGNORECASE)


def collect_verified_prices(session: Session, tool_results: List[Dict[str, Any]]) -> Set[int]:
    """
    Gathers all legitimate integer-LKR prices that were produced by tool results,
    cart lines, and current session state.
    """
    verified: Set[int] = {0, 1500, 250}  # standard free, min order, delivery fee

    # 1. From tool execution results in this turn
    for res in tool_results:
        data = res.get("data", {})
        if isinstance(data, dict):
            for key in ("subtotal", "total", "discount", "delivery_fee", "unit_price", "line_total", "min_order_lkr"):
                val = data.get(key)
                if isinstance(val, (int, float)):
                    verified.add(int(val))
            if "lines" in data and isinstance(data["lines"], list):
                for line in data["lines"]:
                    if isinstance(line, dict):
                        if "unit_price" in line:
                            verified.add(int(line["unit_price"]))
                        if "line_total" in line:
                            verified.add(int(line["line_total"]))

    # 2. From current cart lines and menu items
    if session.cart:
        try:
            sub = pricing.subtotal(session.cart)
            verified.add(sub)
        except Exception:
            pass
        for line in session.cart:
            try:
                verified.add(pricing.unit_price(line))
                verified.add(pricing.line_total(line))
            except Exception:
                pass
            item = menu_repo.get_item(line.item_id)
            if item:
                verified.update(item.sizes.values())

    return verified


def verify_and_post_process_reply(
    reply_text: str,
    session: Session,
    tool_results: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Post-processes the orchestrator's reply:
    1. Checks prices mentioned in the text against tool-verified figures.
    2. Corrects any fabricated price with the tool-verified order total if mismatched.
    3. Trims trailing whitespace and maintains clean WhatsApp formatting.
    """
    if not reply_text:
        return ""

    text = reply_text.strip()
    tools = tool_results or []
    verified_prices = collect_verified_prices(session, tools)

    # Check if a summary or place_order tool result has an official total
    official_total = None
    for res in reversed(tools):
        data = res.get("data", {})
        if isinstance(data, dict) and "total" in data:
            official_total = int(data["total"])
            break

    # If the reply is an exact formatted receipt from show_summary, preserve it directly
    for res in tools:
        data = res.get("data", {})
        if isinstance(data, dict) and "receipt_text" in data:
            receipt = data["receipt_text"]
            if receipt in text or "Your order 🍕" in text:
                return text

    # Scan for price occurrences
    def check_match(match: re.Match) -> str:
        raw_num = match.group(1).replace(",", "")
        try:
            amount = int(raw_num)
        except ValueError:
            return match.group(0)

        # Allow prices that match tool figures
        if amount in verified_prices:
            return match.group(0)

        # If a single official total exists and an unverified total was stated, replace it
        if official_total is not None:
            log.warning("Fabricated price %d detected; correcting to verified total LKR %d", amount, official_total)
            return f"LKR {official_total:,}"

        # Otherwise leave or format
        return match.group(0)

    processed = PRICE_REGEX.sub(check_match, text)
    return processed.strip()

