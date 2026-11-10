from typing import Any, Dict, Literal, Optional
from app.state.session import Session
from app.services.menu_repo import MenuRepo, menu_repo
from app.services.branch_repo import BranchRepo, branch_repo
from app.services.promo_repo import PromoRepo, promo_repo
from app.services import pricing
from app.db.order_repo import OrderRepo, order_repo


def order_set_fulfilment(
    session: Session,
    mode: Literal["delivery", "pickup"],
) -> Dict[str, Any]:
    """Sets the fulfilment mode ('delivery' or 'pickup'). Requires a non-empty cart."""
    if session.stage == "handoff":
        return {
            "ok": False,
            "error": "HANDOFF_ACTIVE",
            "message": "Your conversation has been handed over to a staff member.",
        }

    if not session.cart:
        return {
            "ok": False,
            "error": "CART_EMPTY",
            "message": "Please add at least one item to your cart before choosing delivery or pickup.",
        }

    clean_mode = (mode or "").strip().lower()
    if clean_mode not in ("delivery", "pickup"):
        return {
            "ok": False,
            "error": "INVALID_FULFILMENT",
            "message": f"Fulfilment mode must be 'delivery' or 'pickup' (got '{mode}').",
        }

    session.fulfilment = clean_mode  # type: ignore
    if clean_mode == "pickup":
        session.delivery_zone = None
    session.invalidate_summary()
    session.stage = "collecting_fulfilment"

    return {
        "ok": True,
        "data": {
            "fulfilment": session.fulfilment,
            "stage": session.stage,
        },
    }


def order_set_pickup(
    session: Session,
    branch_id: str,
    branches: BranchRepo = branch_repo,
    promos: PromoRepo = promo_repo,
) -> Dict[str, Any]:
    """Sets pickup fulfilment at a specific branch after verifying the branch exists and is open (D22)."""
    if session.stage == "handoff":
        return {
            "ok": False,
            "error": "HANDOFF_ACTIVE",
            "message": "Your conversation has been handed over to a staff member.",
        }

    branch = branches.get_branch(branch_id)
    if not branch:
        return {
            "ok": False,
            "error": "BRANCH_NOT_FOUND",
            "message": f"Branch '{branch_id}' not found. Available: colombo07, nugegoda, kandy.",
        }

    open_ok, open_msg = branches.check_open(branch.id, mode="pickup")
    if not open_ok:
        return {
            "ok": False,
            "error": "BRANCH_CLOSED",
            "message": open_msg,
        }

    session.fulfilment = "pickup"
    session.branch_id = branch.id
    session.delivery_zone = None
    session.address = None

    if session.promo_code:
        sub = pricing.subtotal(session.cart)
        valid_promo, _, _ = promos.validate(session.promo_code, sub, branch_id=branch.id)
        if not valid_promo:
            session.promo_code = None

    session.invalidate_summary()
    if session.cart and session.stage in ("browsing", "building_cart"):
        session.stage = "collecting_fulfilment"

    return {
        "ok": True,
        "data": {
            "fulfilment": "pickup",
            "branch_id": branch.id,
            "branch_name": branch.name,
            "stage": session.stage,
        },
    }


def _validate_order_ready(
    session: Session,
    menus: MenuRepo,
    branches: BranchRepo,
    promos: PromoRepo,
) -> tuple[bool, Optional[Dict[str, Any]], Any, Any, Any]:
    if not session.cart:
        return (
            False,
            {"ok": False, "error": "CART_EMPTY", "message": "Your cart is empty."},
            None,
            None,
            None,
        )

    if not session.fulfilment or not session.branch_id:
        return (
            False,
            {
                "ok": False,
                "error": "FULFILMENT_INCOMPLETE",
                "message": "Please select delivery (with address) or pickup (with branch) first.",
            },
            None,
            None,
            None,
        )

    branch = branches.get_branch(session.branch_id)
    if not branch:
        return (
            False,
            {"ok": False, "error": "BRANCH_NOT_FOUND", "message": f"Branch '{session.branch_id}' not found."},
            None,
            None,
            None,
        )

    open_ok, open_msg = branches.check_open(branch.id, mode=session.fulfilment)
    if not open_ok:
        return (
            False,
            {"ok": False, "error": "BRANCH_CLOSED", "message": open_msg},
            None,
            None,
            None,
        )

    zone = None
    if session.fulfilment == "delivery":
        if not session.delivery_zone:
            return (
                False,
                {
                    "ok": False,
                    "error": "FULFILMENT_INCOMPLETE",
                    "message": "Delivery zone not resolved. Please set your delivery address first.",
                },
                None,
                None,
                None,
            )
        zone = branch.get_zone(session.delivery_zone)
        if not zone:
            return (
                False,
                {"ok": False, "error": "ZONE_NOT_FOUND", "message": f"Unknown delivery zone '{session.delivery_zone}'."},
                None,
                None,
                None,
            )

    # Check item availability and zone restrictions (e.g. Ice Cream Cup only in z1)
    for line in session.cart:
        if not menus.is_available(line.item_id):
            name = pricing.item_display_name(line, repo=menus)
            return (
                False,
                {
                    "ok": False,
                    "error": "ITEM_UNAVAILABLE",
                    "message": f"Sorry, '{name}' is no longer available.",
                },
                None,
                None,
                None,
            )
        item = menus.get_item(line.item_id)
        if (
            session.fulfilment == "delivery"
            and item
            and item.delivery_zone_limit
            and session.delivery_zone != item.delivery_zone_limit
        ):
            return (
                False,
                {
                    "ok": False,
                    "error": "ZONE_RESTRICTED_ITEM",
                    "message": (
                        f"Sorry, '{item.name}' can only be delivered within Zone 1 (0–3 km) "
                        f"because it may melt (your address is in {session.delivery_zone.upper()})."
                    ),
                },
                None,
                None,
                None,
            )

    sub = pricing.subtotal(session.cart, repo=menus)
    if session.fulfilment == "delivery" and sub < branches.min_order_lkr:
        return (
            False,
            {
                "ok": False,
                "error": "BELOW_MIN_ORDER",
                "message": (
                    f"Minimum food subtotal for delivery is LKR {branches.min_order_lkr:,} "
                    f"(current subtotal is LKR {sub:,})."
                ),
            },
            None,
            None,
            None,
        )

    active_promo = None
    if session.promo_code:
        promo, err_code, msg = promos.validate(session.promo_code, sub, branch_id=branch.id)
        if err_code or not promo:
            return (
                False,
                {"ok": False, "error": err_code or "PROMO_INVALID", "message": msg},
                None,
                None,
                None,
            )
        active_promo = promo

    return True, None, branch, zone, active_promo


def order_show_summary(
    session: Session,
    menus: MenuRepo = menu_repo,
    branches: BranchRepo = branch_repo,
    promos: PromoRepo = promo_repo,
) -> Dict[str, Any]:
    """
    Validates cart, branch open hours, minimum delivery order, zone restrictions, and promo rules.
    Computes the receipt, sets stage='confirming', and records summary_hash and summary_msg_no (D8).
    """
    if session.stage == "handoff":
        return {
            "ok": False,
            "error": "HANDOFF_ACTIVE",
            "message": "Your conversation has been handed over to a staff member.",
        }

    ok, err_resp, branch, zone, active_promo = _validate_order_ready(session, menus, branches, promos)
    if not ok and err_resp:
        return err_resp

    receipt = pricing.format_receipt(session, branch, zone=zone, promo=active_promo, repo=menus)
    session.stage = "confirming"
    session.summary_hash = session.compute_summary_hash()
    session.summary_msg_no = session.message_count

    return {
        "ok": True,
        "data": {
            "stage": session.stage,
            "summary_hash": session.summary_hash,
            "summary_msg_no": session.summary_msg_no,
            "branch_id": branch.id,
            "branch_name": branch.name,
            "fulfilment": session.fulfilment,
            "zone_id": zone.id if zone else None,
            "subtotal": receipt["subtotal"],
            "discount": receipt["discount"],
            "delivery_fee": receipt["delivery_fee"],
            "total": receipt["total"],
            "eta_min": receipt["eta_min"],
            "lines": receipt["lines"],
            "receipt_text": receipt["receipt_text"],
        },
    }


def order_place_order(
    session: Session,
    cart_hash: str,
    menus: MenuRepo = menu_repo,
    branches: BranchRepo = branch_repo,
    promos: PromoRepo = promo_repo,
    orders: OrderRepo = order_repo,
) -> Dict[str, Any]:
    """
    Places the confirmed order after checking the two-step confirmation guards (D8):
    1. Stage must be 'confirming' and summary_hash must exist.
    2. cart_hash must match session.summary_hash (and current cart state).
    3. session.message_count > session.summary_msg_no (cannot confirm on the same turn).
    4. Branch must still be open and items available.
    """
    if session.stage != "confirming" or not session.summary_hash:
        return {
            "ok": False,
            "error": "SUMMARY_REQUIRED",
            "message": "Order summary must be shown to the customer before placing the order.",
        }

    current_hash = session.compute_summary_hash()
    if cart_hash != session.summary_hash or cart_hash != current_hash:
        return {
            "ok": False,
            "error": "HASH_MISMATCH",
            "message": "The order has changed since the summary was shown. Please review the updated summary.",
        }

    if session.summary_msg_no is not None and session.message_count <= session.summary_msg_no:
        return {
            "ok": False,
            "error": "SAME_TURN_CONFIRM",
            "message": "Cannot place an order on the same message turn as show_summary; wait for customer confirmation.",
        }

    ok, err_resp, branch, zone, active_promo = _validate_order_ready(session, menus, branches, promos)
    if not ok and err_resp:
        return err_resp

    receipt = pricing.format_receipt(session, branch, zone=zone, promo=active_promo, repo=menus)
    lat = session.location.get("lat") if session.location else None
    lng = session.location.get("lng") if session.location else None

    persisted = orders.create_order(
        user_id=session.user_id,
        branch_id=branch.id,
        fulfilment=session.fulfilment or "delivery",
        subtotal=receipt["subtotal"],
        delivery_fee=receipt["delivery_fee"],
        discount=receipt["discount"],
        total=receipt["total"],
        items=receipt["lines"],
        address=session.address,
        lat=lat,
        lng=lng,
        zone_id=zone.id if zone else None,
        promo_code=active_promo.code if active_promo else None,
    )

    session.stage = "placed"
    session.last_order_no = persisted.order_no
    session.summary_hash = None
    session.summary_msg_no = None

    return {
        "ok": True,
        "data": {
            "order_no": persisted.order_no,
            "branch_id": branch.id,
            "branch_name": branch.name,
            "fulfilment": persisted.fulfilment,
            "subtotal": persisted.subtotal,
            "discount": persisted.discount,
            "delivery_fee": persisted.delivery_fee,
            "total": persisted.total,
            "eta_min": receipt["eta_min"],
            "status": persisted.status.value,
            "stage": session.stage,
        },
    }


def order_cancel_draft(session: Session) -> Dict[str, Any]:
    """Cancels the current draft order and resets the session back to browsing."""
    session.reset_cart()
    return {
        "ok": True,
        "data": {
            "stage": session.stage,
            "message": "Your draft order has been cleared.",
        },
    }

