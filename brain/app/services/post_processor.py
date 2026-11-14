import re
import logging
from typing import Any, Dict, List, Optional, Set
from app.state.session import Session
from app.services.menu_repo import menu_repo
from app.services import pricing

log = logging.getLogger("brain.post_processor")

# Matches both "LKR 3,490" / "Rs. 3490" (prefix) and "3490 LKR" / "3,490 Rs" (suffix)
PRICE_REGEX = re.compile(
    r"(?:(?:LKR|Rs\.?)\s*([\d,]{2,})|([\d,]{2,})\s*(?:LKR|Rs\b))",
    re.IGNORECASE,
)


def _price_amount(match: re.Match) -> Optional[int]:
    raw = (match.group(1) or match.group(2) or "").replace(",", "").strip()
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def _numbers_in_strings(obj: Any) -> Set[int]:
    """Every price-like number written inside any string value of a tool result."""
    found: Set[int] = set()
    if isinstance(obj, str):
        for m in PRICE_REGEX.finditer(obj):
            amt = _price_amount(m)
            if amt is not None:
                found.add(amt)
    elif isinstance(obj, dict):
        for v in obj.values():
            found |= _numbers_in_strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            found |= _numbers_in_strings(v)
    return found


def _menu_wide_prices() -> Set[int]:
    """Every legitimate price in menu.json: item sizes, combos, crust and topping surcharges."""
    prices: Set[int] = set()
    try:
        for item in menu_repo.get_all_items():
            prices.update(int(p) for p in item.sizes.values())
        for combo in menu_repo.get_all_combos():
            prices.add(int(combo.price))
        data = menu_repo.load() if getattr(menu_repo, "_data", None) is None else menu_repo._data
        for extra in list(data.crusts) + list(data.extra_toppings):
            for key in ("surcharge", "price", "extra"):
                val = extra.get(key)
                if isinstance(val, (int, float)):
                    prices.add(int(val))
    except Exception:
        pass
    return prices


def collect_verified_prices(
    session: Session,
    tool_results: List[Dict[str, Any]],
    user_text: Optional[str] = None,
) -> Set[int]:
    """
    Gathers all legitimate integer-LKR prices that were produced by tool results,
    cart lines, the menu, and numbers the customer typed themselves (e.g. "under LKR 2500").
    """
    verified: Set[int] = {0, 1500, 250}  # standard free, min order, delivery fee
    verified |= _menu_wide_prices()

    # 1. From tool execution results in this turn (structured fields and free text)
    for res in tool_results:
        verified |= _numbers_in_strings(res)
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

    # 2. Numbers the customer wrote themselves may be echoed back (thresholds, budgets)
    if user_text:
        for token in re.findall(r"\d[\d,]*", user_text):
            try:
                verified.add(int(token.replace(",", "")))
            except ValueError:
                pass

    # 2. From current cart lines and menu items
    if session.cart:
        try:
            sub = pricing.subtotal(session.cart)
            verified.add(sub)
            verified.add(sub + 250)  # subtotal + standard delivery fee
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

    # 3. From placed order if cart was reset
    if session.last_order_no:
        try:
            from app.db.order_repo import order_repo
            past = order_repo.get_order_by_no(session.last_order_no)
            if past:
                verified.add(past.total)
                verified.add(past.subtotal)
                verified.add(past.delivery_fee)
                verified.add(past.discount)
                for oi in past.items:
                    verified.add(oi.unit_price)
                    verified.add(oi.line_total)
        except Exception:
            pass

    return verified


def find_unverified_prices(
    reply_text: str,
    session: Session,
    tool_results: Optional[List[Dict[str, Any]]] = None,
    user_text: Optional[str] = None,
) -> List[int]:
    """Prices written in `reply_text` that no tool, menu entry, cart line or the customer produced."""
    if not reply_text:
        return []
    verified = collect_verified_prices(session, tool_results or [], user_text)
    bad: List[int] = []
    for m in PRICE_REGEX.finditer(reply_text):
        amount = _price_amount(m)
        if amount is not None and amount not in verified and amount not in bad:
            bad.append(amount)
    return bad


def redact_unverified_prices(reply_text: str, bad_prices: List[int]) -> str:
    """
    Last-resort cleanup: removes prices no tool can vouch for. A parenthesised price such as
    "(LKR 7,600)" is dropped entirely; a bare price becomes "the menu price".
    """
    text = reply_text or ""
    bad = set(bad_prices)
    if not bad:
        return text

    def _bad(match: re.Match) -> bool:
        return _price_amount(match) in bad

    def _drop_parenthetical(m: re.Match) -> str:
        inner = m.group(0)
        return "" if any(_bad(pm) for pm in PRICE_REGEX.finditer(inner)) else inner

    text = re.sub(r"\s*\([^()]*\)", _drop_parenthetical, text)
    text = PRICE_REGEX.sub(lambda m: "the menu price" if _bad(m) else m.group(0), text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def verify_and_post_process_reply(
    reply_text: str,
    session: Session,
    tool_results: Optional[List[Dict[str, Any]]] = None,
    user_text: Optional[str] = None,
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
    verified_prices = collect_verified_prices(session, tools, user_text)

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
        amount = _price_amount(match)
        if amount is None:
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

