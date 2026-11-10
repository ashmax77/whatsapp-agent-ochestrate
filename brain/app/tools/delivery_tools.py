from typing import Any, Dict, Optional
from app.state.session import Session
from app.services.branch_repo import BranchRepo, branch_repo
from app.services.promo_repo import PromoRepo, promo_repo
from app.services import pricing


def delivery_set_address(
    session: Session,
    address_text: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    repo: BranchRepo = branch_repo,
    promos: PromoRepo = promo_repo,
) -> Dict[str, Any]:
    """
    Resolves a customer's delivery address or location pin to a branch and delivery zone.
    Enforces max_km radius and branch opening hours (before last_delivery_order).
    """
    if session.stage == "handoff":
        return {
            "ok": False,
            "error": "HANDOFF_ACTIVE",
            "message": "Your conversation has been handed over to a staff member.",
        }

    if lat is None and lng is None and not (address_text and address_text.strip()):
        return {
            "ok": False,
            "error": "NEEDS_CLARIFICATION",
            "message": "Please provide a delivery address with a landmark or share a WhatsApp location pin.",
        }

    distance_km: Optional[float] = None
    if lat is not None and lng is not None:
        branch, zone, distance_km, err = repo.resolve_by_pin(float(lat), float(lng))
        if err == "OUT_OF_AREA" or not branch or not zone:
            return {
                "ok": False,
                "error": "OUT_OF_AREA",
                "message": (
                    f"Sorry, your location is {distance_km} km from our nearest outlet, "
                    "which is outside our delivery radius."
                ),
            }
    else:
        branch, zone, err = repo.resolve_by_address(address_text or "")
        if err == "OUT_OF_AREA":
            return {
                "ok": False,
                "error": "OUT_OF_AREA",
                "message": f"Sorry, '{address_text}' is outside our delivery coverage area.",
            }
        if err == "NEEDS_CLARIFICATION" or not branch or not zone:
            return {
                "ok": False,
                "error": "NEEDS_CLARIFICATION",
                "message": (
                    "Could you share a WhatsApp location pin or a nearby area/landmark "
                    "(e.g. Colombo 01–08, Nugegoda, Maharagama, Kandy, Peradeniya)?"
                ),
            }

    open_ok, open_msg = repo.check_open(branch.id, mode="delivery")
    if not open_ok:
        return {
            "ok": False,
            "error": "BRANCH_CLOSED",
            "message": open_msg,
        }

    session.fulfilment = "delivery"
    session.branch_id = branch.id
    session.delivery_zone = zone.id
    if address_text and address_text.strip():
        session.address = address_text.strip()
    elif lat is not None and lng is not None:
        session.address = f"Location pin ({lat:.4f}, {lng:.4f})"
    if lat is not None and lng is not None:
        session.location = {"lat": float(lat), "lng": float(lng)}

    # If a promo was already set, check that it is valid at this branch
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
            "branch_id": branch.id,
            "branch_name": branch.name,
            "zone_id": zone.id,
            "delivery_fee": zone.fee,
            "eta_min": zone.eta_min,
            "distance_km": distance_km,
            "address": session.address,
            "stage": session.stage,
        },
    }


def delivery_quote(
    session: Session,
    repo: BranchRepo = branch_repo,
) -> Dict[str, Any]:
    """Returns the delivery fee and estimated delivery time for the session's current branch and zone."""
    if not session.branch_id or not session.delivery_zone:
        return {
            "ok": False,
            "error": "ADDRESS_NOT_SET",
            "message": "Delivery address or location pin has not been set yet.",
        }

    branch = repo.get_branch(session.branch_id)
    if not branch:
        return {
            "ok": False,
            "error": "BRANCH_NOT_FOUND",
            "message": f"Branch '{session.branch_id}' not found.",
        }

    zone = branch.get_zone(session.delivery_zone)
    if not zone:
        return {
            "ok": False,
            "error": "ZONE_NOT_FOUND",
            "message": f"Zone '{session.delivery_zone}' not found for branch '{branch.id}'.",
        }

    return {
        "ok": True,
        "data": {
            "branch_id": branch.id,
            "branch_name": branch.name,
            "zone_id": zone.id,
            "delivery_fee": zone.fee,
            "eta_min": zone.eta_min,
            "min_order_lkr": repo.min_order_lkr,
        },
    }

