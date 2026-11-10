from typing import Any, Dict
from app.state.session import Session
from app.services.promo_repo import PromoRepo, promo_repo
from app.services.menu_repo import MenuRepo, menu_repo
from app.services import pricing


def promo_apply(
    session: Session,
    code: str,
    promos: PromoRepo = promo_repo,
    menus: MenuRepo = menu_repo,
) -> Dict[str, Any]:
    """
    Deterministically validates and applies a promo code to the session.
    Checks active dates, day of week, branch restriction, and minimum food subtotal.
    """
    if session.stage == "handoff":
        return {
            "ok": False,
            "error": "HANDOFF_ACTIVE",
            "message": "Your conversation has been handed over to a staff member.",
        }

    sub = pricing.subtotal(session.cart, repo=menus)
    promo, err_code, msg = promos.validate(
        code=code,
        subtotal_lkr=sub,
        branch_id=session.branch_id,
    )
    if err_code or not promo:
        return {
            "ok": False,
            "error": err_code or "PROMO_INVALID",
            "message": msg,
        }

    session.promo_code = promo.code
    session.invalidate_summary()
    disc = pricing.discount(promo, sub, session.cart)

    return {
        "ok": True,
        "data": {
            "promo_code": promo.code,
            "discount_lkr": disc,
            "subtotal_lkr": sub,
            "requires_student_id": promo.requires_student_id,
            "message": msg,
        },
    }


def promo_remove(session: Session) -> Dict[str, Any]:
    """Removes any active promo code from the session."""
    removed = session.promo_code
    session.promo_code = None
    session.invalidate_summary()
    return {
        "ok": True,
        "data": {
            "removed_promo_code": removed,
            "promo_code": None,
        },
    }

