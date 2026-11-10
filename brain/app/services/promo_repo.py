import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel
from app.config import settings
from app.services import clock

log = logging.getLogger("brain.promo_repo")


class Promo(BaseModel):
    code: str
    name: str = ""
    type: str = "percent"  # "percent" | "fixed"
    value: int
    min_subtotal: int = 0
    valid_days: Optional[List[str]] = None  # e.g. ["Fri"], ["Tue"]
    valid_from: Optional[str] = None  # YYYY-MM-DD
    valid_until: Optional[str] = None  # YYYY-MM-DD
    branches: Optional[List[str]] = None  # null = all branches
    requires_student_id: bool = False
    stackable: bool = False

    def is_expired_on(self, check_date: date) -> bool:
        if not self.valid_until:
            return False
        return check_date > date.fromisoformat(self.valid_until)


class PromoData(BaseModel):
    promos: List[Promo] = []


class PromoRepo:
    def __init__(self, promos_path: Optional[Path] = None):
        self.promos_path = promos_path or settings.PROMOS_FILE_PATH
        self._data: PromoData = PromoData()
        self._promos_by_code: Dict[str, Promo] = {}
        self.load()

    def load(self) -> PromoData:
        if not self.promos_path.exists():
            log.warning("Promos file not found at %s", self.promos_path)
            self._data = PromoData()
            self._promos_by_code = {}
            return self._data

        with open(self.promos_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        self._data = PromoData(**raw)
        self._promos_by_code = {p.code.upper(): p for p in self._data.promos}
        return self._data

    def get_promo(self, code: str) -> Optional[Promo]:
        if not code:
            return None
        clean = code.strip().upper()
        if clean in self._promos_by_code:
            return self._promos_by_code[clean]
        # Match by name or prefix for expired offers like "Monsoon Special" or "Avurudu Combo"
        for promo in self._data.promos:
            if promo.name and promo.name.upper() == clean:
                return promo
        return None

    def list_promos(self, active_only: bool = False, on_date: Optional[date] = None) -> List[Promo]:
        if not active_only:
            return list(self._data.promos)
        ref_date = on_date or clock.now().date()
        return [p for p in self._data.promos if not p.is_expired_on(ref_date)]

    def validate(
        self,
        code: str,
        subtotal_lkr: int,
        branch_id: Optional[str] = None,
        now_dt: Optional[datetime] = None,
    ) -> Tuple[Optional[Promo], Optional[str], str]:
        """
        Deterministically checks a promo code against date range, day of week,
        branch eligibility, and minimum food subtotal.
        Returns (promo_or_none, error_code_or_none, message).
        """
        promo = self.get_promo(code)
        if not promo:
            return None, "PROMO_INVALID", f"Unknown promo code '{code}'."

        current = clock.now(now_dt)
        today = current.date()

        if promo.valid_until and today > date.fromisoformat(promo.valid_until):
            return (
                None,
                "PROMO_INVALID",
                f"Promo code '{promo.code}' has expired (ended on {promo.valid_until}).",
            )

        if promo.valid_from and today < date.fromisoformat(promo.valid_from):
            return (
                None,
                "PROMO_INVALID",
                f"Promo code '{promo.code}' is not active yet (starts {promo.valid_from}).",
            )

        if promo.valid_days:
            day_abbr = current.strftime("%a")
            allowed_days = [d.strip().capitalize()[:3] for d in promo.valid_days]
            if day_abbr not in allowed_days:
                return (
                    None,
                    "PROMO_INVALID",
                    f"Promo code '{promo.code}' is only valid on {', '.join(allowed_days)} (today is {day_abbr}).",
                )

        if promo.branches is not None:
            allowed_branches = [b.lower() for b in promo.branches]
            if not branch_id:
                return (
                    None,
                    "PROMO_INVALID",
                    f"Promo code '{promo.code}' is only valid at {', '.join(promo.branches)} outlets. "
                    "Please set your delivery address or pickup branch first.",
                )
            if branch_id.lower() not in allowed_branches:
                return (
                    None,
                    "PROMO_INVALID",
                    f"Promo code '{promo.code}' is not valid at branch '{branch_id}' "
                    f"(valid at: {', '.join(promo.branches)}).",
                )

        if subtotal_lkr < promo.min_subtotal:
            return (
                None,
                "PROMO_INVALID",
                f"Promo code '{promo.code}' requires a minimum food subtotal of LKR {promo.min_subtotal:,} "
                f"(current subtotal is LKR {subtotal_lkr:,}).",
            )

        note = f"Promo '{promo.code}' applied ({promo.value}% off food subtotal)."
        if promo.requires_student_id:
            note += " Please show a valid student ID at pickup or on delivery."
        return promo, None, note


promo_repo = PromoRepo()

