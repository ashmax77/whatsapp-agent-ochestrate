"""
Pure integer-LKR pricing engine and receipt formatter (Decision D3, D6).
All money calculations happen here in deterministic integer arithmetic—never in an LLM.
Discounts apply strictly to the food subtotal, never to the delivery fee.
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional
from app.state.session import CartLine, Session
from app.services.menu_repo import MenuRepo, menu_repo
from app.services.branch_repo import Branch, BranchZone
from app.services.promo_repo import Promo


def round_lkr(value: Decimal | float | int) -> int:
    """Deterministic half-up integer rounding in LKR."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def item_display_name(line: CartLine, repo: MenuRepo = menu_repo) -> str:
    combo = repo.get_combo(line.item_id)
    if combo:
        return combo.name
    item = repo.get_item(line.item_id)
    return item.name if item else line.item_id


def unit_price(line: CartLine, repo: MenuRepo = menu_repo) -> int:
    """Computes the single-unit price in integer LKR including crust and topping surcharges."""
    combo = repo.get_combo(line.item_id)
    if combo:
        return int(combo.price)

    item = repo.get_item(line.item_id)
    if not item:
        raise ValueError(f"Unknown item_id '{line.item_id}' in cart.")

    size_key = line.size.lower()
    if size_key not in item.sizes:
        raise ValueError(f"Invalid size '{line.size}' for item '{item.name}'.")

    price = int(item.sizes[size_key])
    opts = line.options or {}

    if "crust" in opts:
        crust = repo.get_crust(str(opts["crust"]))
        if crust:
            if "surcharges" in crust and isinstance(crust["surcharges"], dict):
                price += int(crust["surcharges"].get(size_key, 0))
            else:
                price += int(crust.get("surcharge", 0))

    if "extra_toppings" in opts and isinstance(opts["extra_toppings"], list):
        for top_id in opts["extra_toppings"]:
            top = repo.get_topping(str(top_id))
            if top:
                price += int(top.get("surcharge", 0))

    return price


def line_total(line: CartLine, repo: MenuRepo = menu_repo) -> int:
    """Computes unit_price * qty in integer LKR."""
    if line.qty < 1:
        raise ValueError("Cart line quantity must be >= 1.")
    return unit_price(line, repo=repo) * int(line.qty)


def subtotal(cart: List[CartLine], repo: MenuRepo = menu_repo) -> int:
    """Computes the food subtotal across all cart lines in integer LKR."""
    return sum(line_total(line, repo=repo) for line in cart)


def delivery_fee(
    branch: Optional[Branch],
    zone_id: Optional[str],
    subtotal_lkr: int = 0,
    fulfilment: Optional[str] = "delivery",
) -> int:
    """Returns the delivery fee in integer LKR (0 for pickup or Zone 1)."""
    if fulfilment == "pickup" or branch is None or not zone_id:
        return 0
    zone = branch.get_zone(zone_id)
    if not zone:
        raise ValueError(f"Unknown delivery zone '{zone_id}' for branch '{branch.id}'.")
    return int(zone.fee)


def discount(
    promo: Optional[Promo],
    subtotal_lkr: int,
    cart: Optional[List[CartLine]] = None,
) -> int:
    """
    Computes the promo discount in integer LKR (ROUND_HALF_UP).
    Applies strictly to the food subtotal (never exceeds subtotal_lkr).
    """
    if promo is None or subtotal_lkr <= 0:
        return 0

    if promo.type == "percent":
        raw = (Decimal(subtotal_lkr) * Decimal(promo.value)) / Decimal(100)
        disc = round_lkr(raw)
    elif promo.type == "fixed":
        disc = int(promo.value)
    else:
        raise ValueError(f"Unsupported promo type '{promo.type}'.")

    return max(0, min(disc, int(subtotal_lkr)))


def total(subtotal_lkr: int, delivery_fee_lkr: int, discount_lkr: int) -> int:
    """
    Computes final order total in integer LKR.
    Discount reduces food subtotal only; delivery fee is added afterwards.
    """
    discounted_food = max(0, int(subtotal_lkr) - int(discount_lkr))
    return discounted_food + int(delivery_fee_lkr)


def format_line_description(line: CartLine, repo: MenuRepo = menu_repo) -> str:
    name = item_display_name(line, repo=repo)
    combo = repo.get_combo(line.item_id)
    if combo:
        if line.combo_choices:
            parts = []
            for slot, chosen_id in line.combo_choices.items():
                item = repo.get_item(chosen_id)
                if item and "pizza" in slot:
                    parts.append(item.name)
            if parts:
                return f"{name} ({', '.join(parts)})"
        return name

    size_label = f" ({line.size.capitalize()})" if line.size.lower() != "regular" else ""
    extra_parts: List[str] = []
    opts = line.options or {}
    if opts.get("crust") and opts["crust"] != "classic_pan":
        crust = repo.get_crust(opts["crust"])
        extra_parts.append(crust["name"] if crust else opts["crust"])
    if opts.get("extra_toppings"):
        tops = [repo.get_topping(t)["name"] if repo.get_topping(t) else t for t in opts["extra_toppings"]]
        extra_parts.append("+ " + ", ".join(tops))
    for k in ("sauce", "flavour"):
        if opts.get(k):
            extra_parts.append(str(opts[k]))

    opt_suffix = f" [{'; '.join(extra_parts)}]" if extra_parts else ""
    return f"{name}{size_label}{opt_suffix}"


def format_receipt(
    session: Session,
    branch: Branch,
    zone: Optional[BranchZone] = None,
    promo: Optional[Promo] = None,
    repo: MenuRepo = menu_repo,
) -> Dict[str, Any]:
    """
    Computes all totals and formats the plain-text WhatsApp order summary receipt.
    Returns both structured breakdown and receipt_text.
    """
    sub = subtotal(session.cart, repo=repo)
    disc = discount(promo, sub, session.cart)
    fee = delivery_fee(branch, zone.id if zone else session.delivery_zone, sub, session.fulfilment)
    grand_total = total(sub, fee, disc)

    lines_out = [f"Your order 🍕  ({branch.name} branch)"]
    line_details = []
    for line in session.cart:
        u_price = unit_price(line, repo=repo)
        l_total = u_price * line.qty
        desc = format_line_description(line, repo=repo)
        lines_out.append(f"{line.qty} x {desc}  LKR {l_total:,}")
        line_details.append({
            "item_id": line.item_id,
            "name": item_display_name(line, repo=repo),
            "description": desc,
            "size": line.size,
            "qty": line.qty,
            "unit_price": u_price,
            "line_total": l_total,
            "notes": line.notes,
            "options": line.options,
            "combo_choices": line.combo_choices,
        })

    lines_out.append(f"Subtotal              LKR {sub:,}")
    if promo and disc > 0:
        lines_out.append(f"Promo {promo.code}        -LKR {disc:,}")
    if session.fulfilment == "delivery":
        lines_out.append(f"Delivery              LKR {fee:,}")
    else:
        lines_out.append("Pickup                LKR 0")
    lines_out.append(f"Total                 LKR {grand_total:,}")

    eta_min = zone.eta_min if (session.fulfilment == "delivery" and zone) else 25
    if session.fulfilment == "delivery":
        addr = session.address or "Pinned location"
        lines_out.append(f"Delivery to: {addr}  | ETA ~{eta_min} min")
    else:
        lines_out.append(f"Pickup at: {branch.name}  | Ready in ~{eta_min} min")

    if promo and promo.requires_student_id:
        lines_out.append("Note: Please show a valid student ID at pickup or on delivery.")

    lines_out.append("Reply YES to confirm.")
    return {
        "subtotal": sub,
        "discount": disc,
        "delivery_fee": fee,
        "total": grand_total,
        "eta_min": eta_min,
        "lines": line_details,
        "receipt_text": "\n".join(lines_out),
    }

