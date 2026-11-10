from typing import Any, Dict, Optional
from app.state.session import Session
from app.services.branch_repo import BranchRepo, branch_repo


def branch_list(
    session: Optional[Session] = None,
    repo: BranchRepo = branch_repo,
) -> Dict[str, Any]:
    """Lists all branches with opening hours, cut-off times, and live open status."""
    items = []
    for b in repo.list_branches():
        open_delivery, _ = repo.check_open(b.id, mode="delivery")
        open_pickup, _ = repo.check_open(b.id, mode="pickup")
        items.append({
            "id": b.id,
            "name": b.name,
            "hours": b.hours.model_dump(),
            "last_delivery_order": b.last_delivery_order,
            "last_dine_in_order": b.last_dine_in_order,
            "max_km": b.max_km,
            "open_now": open_delivery or open_pickup,
            "open_for_delivery": open_delivery,
            "open_for_pickup": open_pickup,
        })
    return {"ok": True, "data": {"branches": items}}

