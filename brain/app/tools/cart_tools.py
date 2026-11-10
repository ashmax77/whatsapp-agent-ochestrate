from typing import Any, Dict, Optional
from app.state.session import CartLine, Session
from app.services.menu_repo import MenuRepo, menu_repo
from app.services import pricing

MIN_QTY = 1
MAX_QTY = 20


def _ensure_editable_stage(session: Session) -> Optional[Dict[str, Any]]:
    if session.stage == "handoff":
        return {
            "ok": False,
            "error": "HANDOFF_ACTIVE",
            "message": "Your conversation has been handed over to a staff member.",
        }
    if session.stage == "placed":
        session.reset_cart()
    return None


def cart_add_item(
    session: Session,
    item_id: str,
    size: str = "regular",
    qty: int = 1,
    notes: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None,
    repo: MenuRepo = menu_repo,
) -> Dict[str, Any]:
    """
    Adds a menu item to the session cart.
    Validates item existence, availability, size, quantity (1..20), and options.
    Merges identical cart lines and transitions browsing -> building_cart.
    """
    guard_err = _ensure_editable_stage(session)
    if guard_err:
        return guard_err

    if not isinstance(qty, int) or qty < MIN_QTY or qty > MAX_QTY:
        return {
            "ok": False,
            "error": "INVALID_QTY",
            "message": f"Quantity must be between {MIN_QTY} and {MAX_QTY} (got {qty}).",
        }

    item = repo.get_item(item_id) or repo.find_by_name(item_id)
    if not item:
        return {
            "ok": False,
            "error": "ITEM_NOT_FOUND",
            "message": f"Item '{item_id}' was not found on the menu.",
        }

    if not item.available:
        return {
            "ok": False,
            "error": "ITEM_UNAVAILABLE",
            "message": f"Sorry, '{item.name}' is currently out of stock.",
        }

    size_key = (size or "").strip().lower()
    if size_key not in item.sizes:
        valid_sizes = ", ".join(item.sizes.keys())
        return {
            "ok": False,
            "error": "INVALID_SIZE",
            "message": f"Size '{size}' is not valid for '{item.name}'. Available sizes: {valid_sizes}.",
        }

    opt_ok, opt_err, norm_options = repo.validate_item_options(item, size_key, options)
    if not opt_ok:
        return {
            "ok": False,
            "error": "INVALID_OPTIONS",
            "message": opt_err or "Invalid item options.",
        }

    new_line = CartLine(
        item_id=item.id,
        size=size_key,
        qty=qty,
        notes=notes.strip() if notes else None,
        options=norm_options or None,
    )

    merged = False
    for existing in session.cart:
        if existing.same_identity(new_line):
            if existing.qty + qty > MAX_QTY:
                return {
                    "ok": False,
                    "error": "INVALID_QTY",
                    "message": f"Total quantity for '{item.name}' cannot exceed {MAX_QTY}.",
                }
            existing.qty += qty
            merged = True
            break

    if not merged:
        session.cart.append(new_line)

    session.invalidate_summary()
    if session.stage == "browsing":
        session.stage = "building_cart"

    return cart_view(session, repo=repo)


def cart_add_combo(
    session: Session,
    combo_id: str,
    choices: Dict[str, str],
    qty: int = 1,
    notes: Optional[str] = None,
    repo: MenuRepo = menu_repo,
) -> Dict[str, Any]:
    """
    Validates combo slots and choices and adds the combo to the cart.
    """
    guard_err = _ensure_editable_stage(session)
    if guard_err:
        return guard_err

    if not isinstance(qty, int) or qty < MIN_QTY or qty > MAX_QTY:
        return {
            "ok": False,
            "error": "INVALID_QTY",
            "message": f"Quantity must be between {MIN_QTY} and {MAX_QTY} (got {qty}).",
        }

    combo = repo.get_combo(combo_id)
    if not combo:
        return {
            "ok": False,
            "error": "COMBO_NOT_FOUND",
            "message": f"Combo '{combo_id}' was not found on the menu.",
        }

    if not combo.available:
        return {
            "ok": False,
            "error": "ITEM_UNAVAILABLE",
            "message": f"Sorry, '{combo.name}' is currently unavailable.",
        }

    ok, err_msg, resolved_choices = repo.validate_combo_choices(combo, choices)
    if not ok:
        return {
            "ok": False,
            "error": "INVALID_COMBO_CHOICES",
            "message": err_msg or "Invalid combo choices.",
        }

    new_line = CartLine(
        item_id=combo.id,
        size="bundle",
        qty=qty,
        notes=notes.strip() if notes else None,
        combo_choices=resolved_choices,
    )

    merged = False
    for existing in session.cart:
        if existing.same_identity(new_line):
            if existing.qty + qty > MAX_QTY:
                return {
                    "ok": False,
                    "error": "INVALID_QTY",
                    "message": f"Total quantity for '{combo.name}' cannot exceed {MAX_QTY}.",
                }
            existing.qty += qty
            merged = True
            break

    if not merged:
        session.cart.append(new_line)

    session.invalidate_summary()
    if session.stage == "browsing":
        session.stage = "building_cart"

    return cart_view(session, repo=repo)


def cart_update_item(
    session: Session,
    line_index: int,
    qty: Optional[int] = None,
    size: Optional[str] = None,
    notes: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None,
    repo: MenuRepo = menu_repo,
) -> Dict[str, Any]:
    """Updates quantity, size, notes, or options on an existing cart line by 0-based index."""
    guard_err = _ensure_editable_stage(session)
    if guard_err:
        return guard_err

    if line_index < 0 or line_index >= len(session.cart):
        return {
            "ok": False,
            "error": "INVALID_LINE_INDEX",
            "message": f"Line index {line_index} is out of range (cart has {len(session.cart)} line(s)).",
        }

    if qty is not None:
        if qty == 0:
            return cart_remove_item(session, line_index=line_index, repo=repo)
        if qty < MIN_QTY or qty > MAX_QTY:
            return {
                "ok": False,
                "error": "INVALID_QTY",
                "message": f"Quantity must be between {MIN_QTY} and {MAX_QTY} (got {qty}).",
            }

    line = session.cart[line_index]
    combo = repo.get_combo(line.item_id)
    item = repo.get_item(line.item_id)

    new_size = line.size
    if size is not None:
        if combo:
            return {
                "ok": False,
                "error": "INVALID_SIZE",
                "message": f"Cannot change size of combo '{combo.name}'.",
            }
        size_key = size.strip().lower()
        if not item or size_key not in item.sizes:
            valid_sizes = ", ".join(item.sizes.keys()) if item else ""
            return {
                "ok": False,
                "error": "INVALID_SIZE",
                "message": f"Size '{size}' is not valid. Available sizes: {valid_sizes}.",
            }
        new_size = size_key

    new_options = line.options
    if options is not None:
        if combo or not item:
            return {
                "ok": False,
                "error": "INVALID_OPTIONS",
                "message": "Options cannot be set on combos.",
            }
        opt_ok, opt_err, norm_opts = repo.validate_item_options(item, new_size, options)
        if not opt_ok:
            return {
                "ok": False,
                "error": "INVALID_OPTIONS",
                "message": opt_err or "Invalid item options.",
            }
        new_options = norm_opts or None

    line.size = new_size
    if qty is not None:
        line.qty = qty
    if notes is not None:
        line.notes = notes.strip() or None
    if options is not None:
        line.options = new_options

    session.invalidate_summary()
    return cart_view(session, repo=repo)


def cart_remove_item(
    session: Session,
    line_index: int,
    repo: MenuRepo = menu_repo,
) -> Dict[str, Any]:
    """Removes a cart line by 0-based index. Transitions to browsing if cart becomes empty."""
    guard_err = _ensure_editable_stage(session)
    if guard_err:
        return guard_err

    if line_index < 0 or line_index >= len(session.cart):
        return {
            "ok": False,
            "error": "INVALID_LINE_INDEX",
            "message": f"Line index {line_index} is out of range (cart has {len(session.cart)} line(s)).",
        }

    session.cart.pop(line_index)
    session.invalidate_summary()
    if not session.cart:
        session.stage = "browsing"

    return cart_view(session, repo=repo)


def cart_clear(
    session: Session,
    repo: MenuRepo = menu_repo,
) -> Dict[str, Any]:
    """Clears all items from the cart and resets stage to browsing."""
    session.cart = []
    session.promo_code = None
    session.invalidate_summary()
    session.stage = "browsing"
    return cart_view(session, repo=repo)


def cart_view(
    session: Session,
    repo: MenuRepo = menu_repo,
) -> Dict[str, Any]:
    """Returns all cart lines with computed unit prices, line totals, and food subtotal."""
    lines_out = []
    for idx, line in enumerate(session.cart):
        u_price = pricing.unit_price(line, repo=repo)
        l_total = pricing.line_total(line, repo=repo)
        item = repo.get_item(line.item_id)
        lines_out.append({
            "line_index": idx,
            "item_id": line.item_id,
            "name": pricing.item_display_name(line, repo=repo),
            "description": pricing.format_line_description(line, repo=repo),
            "size": line.size,
            "qty": line.qty,
            "unit_price": u_price,
            "line_total": l_total,
            "notes": line.notes,
            "options": line.options,
            "combo_choices": line.combo_choices,
            "delivery_zone_limit": item.delivery_zone_limit if item else None,
        })

    sub = pricing.subtotal(session.cart, repo=repo)
    return {
        "ok": True,
        "data": {
            "stage": session.stage,
            "lines": lines_out,
            "subtotal": sub,
            "item_count": sum(line.qty for line in session.cart),
        },
    }

