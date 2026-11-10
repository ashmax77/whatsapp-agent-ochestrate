import json
import math
import re
import logging
from datetime import datetime, time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field
from app.config import settings
from app.services import clock

log = logging.getLogger("brain.branch_repo")

# Inner-ring aliases (within ~3 km of the branch -> Zone 1 free delivery).
# Any alias not in this set falls into Zone 2 (3-8 km / 3-6 km).
ZONE_1_ALIASES = frozenset({
    "colombo 02", "colombo 03", "colombo 04", "colombo 05", "colombo 07", "colombo 08",
    "cinnamon gardens", "bambalapitiya", "kollupitiya",
    "nugegoda", "delkanda", "gangodawila", "kotte",
    "kandy", "suduhumpola", "asgiriya",
})

# Known Sri Lankan towns/areas outside our 3 outlets' delivery radii
KNOWN_OUT_OF_AREA = frozenset({
    "colombo 09", "colombo 10", "colombo 11", "colombo 12", "colombo 13", "colombo 14", "colombo 15",
    "dematagoda", "maradana", "wellampitiya", "mattakkuliya", "modara", "kotahena", "grandpass",
    "moratuwa", "panadura", "kalutara", "wadduwa", "beruwala", "bentota",
    "negombo", "katunayake", "ja-ela", "ja ela", "wattala", "kelaniya", "kiribathgoda", "kadawatha",
    "gampaha", "veyangoda", "mirigama", "minuwangoda", "ragama", "kandana",
    "homagama", "kottawa", "pannipitiya", "piliyandala", "kesbewa", "boralesgamuwa",
    "malabe", "battaramulla", "thalawathugoda", "kaduwela", "athurugiriya", "hanwella", "avissawella",
    "galle", "matara", "hambantota", "tangalle", "weligama", "hikkaduwa", "ambalangoda",
    "kurunegala", "puttalam", "chilaw", "kuliyapitiya",
    "anuradhapura", "polonnaruwa", "dambulla", "sigiriya", "matale", "gampola", "nawalapitiya",
    "nuwara eliya", "hatton", "badulla", "bandarawela", "ella", "monaragala",
    "ratnapura", "balangoda", "embilipitiya", "kegalle", "mawanella",
    "jaffna", "kilinochchi", "mannar", "vavuniya", "mullaitivu",
    "trincomalee", "batticaloa", "ampara", "kalmunai",
})


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two WGS84 coordinates in kilometres."""
    r = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))


def _fuzzy_ratio(a: str, b: str) -> float:
    """Returns similarity score 0..100 (uses rapidfuzz if installed, else SequenceMatcher)."""
    try:
        from rapidfuzz import fuzz  # type: ignore
        return float(fuzz.ratio(a, b))
    except ImportError:
        return SequenceMatcher(None, a, b).ratio() * 100.0


def _parse_hhmm(val: str) -> time:
    parts = val.strip().split(":")
    return time(int(parts[0]), int(parts[1]))


class BranchZone(BaseModel):
    id: str
    max_km: float
    fee: int
    eta_min: int


class BranchHours(BaseModel):
    open: str
    close: str


class Branch(BaseModel):
    id: str
    name: str
    lat: float
    lng: float
    max_km: float
    hours: BranchHours
    last_delivery_order: str
    last_dine_in_order: str
    zones: List[BranchZone] = Field(default_factory=list)
    area_aliases: List[str] = Field(default_factory=list)
    closed_dates: List[str] = Field(default_factory=list)

    def zone_for_distance(self, distance_km: float) -> Optional[BranchZone]:
        for zone in sorted(self.zones, key=lambda z: z.max_km):
            if distance_km <= zone.max_km:
                return zone
        return None

    def get_zone(self, zone_id: str) -> Optional[BranchZone]:
        return next((z for z in self.zones if z.id == zone_id), None)


class BranchData(BaseModel):
    min_order_lkr: int = 1500
    branches: List[Branch] = Field(default_factory=list)


class BranchRepo:
    def __init__(self, branches_path: Optional[Path] = None):
        self.branches_path = branches_path or settings.BRANCHES_FILE_PATH
        self._data: BranchData = BranchData()
        self._branches_by_id: Dict[str, Branch] = {}
        self.load()

    def load(self) -> BranchData:
        if not self.branches_path.exists():
            log.warning("Branches file not found at %s", self.branches_path)
            self._data = BranchData()
            self._branches_by_id = {}
            return self._data

        with open(self.branches_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        self._data = BranchData(**raw)
        self._branches_by_id = {b.id: b for b in self._data.branches}
        return self._data

    @property
    def min_order_lkr(self) -> int:
        return self._data.min_order_lkr

    def get_branch(self, branch_id: str) -> Optional[Branch]:
        if not branch_id:
            return None
        key = branch_id.strip().lower().replace("-", "").replace(" ", "")
        if key in self._branches_by_id:
            return self._branches_by_id[key]
        for b in self._data.branches:
            if key == b.name.lower() or key in b.id.lower() or b.id.lower() in key:
                return b
        return None

    def list_branches(self) -> List[Branch]:
        return list(self._data.branches)

    # ------------------------------------------------------------------
    # Opening hours & cut-offs (D22)
    # ------------------------------------------------------------------
    def check_open(
        self,
        branch_id: str,
        now_dt: Optional[datetime] = None,
        mode: Optional[str] = "delivery",
    ) -> Tuple[bool, str]:
        branch = self.get_branch(branch_id)
        if not branch:
            return False, f"Unknown branch '{branch_id}'."

        current = clock.now(now_dt)
        date_str = current.strftime("%Y-%m-%d")
        if date_str in branch.closed_dates:
            return (
                False,
                f"{branch.name} is closed on {date_str} and reopens tomorrow at {branch.hours.open}.",
            )

        open_t = _parse_hhmm(branch.hours.open)
        close_t = _parse_hhmm(branch.hours.close)
        if mode == "delivery":
            cutoff_str = branch.last_delivery_order
            cutoff_t = _parse_hhmm(cutoff_str)
            label = "delivery"
        elif mode in ("pickup", "dine_in"):
            cutoff_str = branch.last_dine_in_order
            cutoff_t = _parse_hhmm(cutoff_str)
            label = "pickup"
        else:
            cutoff_str = branch.hours.close
            cutoff_t = close_t
            label = "orders"

        cur_hm = (current.hour, current.minute)
        open_hm = (open_t.hour, open_t.minute)
        cutoff_hm = (cutoff_t.hour, cutoff_t.minute)

        if open_hm <= cur_hm <= cutoff_hm:
            return True, f"{branch.name} is open for {label} until {cutoff_str}."

        return (
            False,
            f"{branch.name} is currently closed for {label} (open {branch.hours.open}–{branch.hours.close}, "
            f"last {label} order at {cutoff_str}). It reopens at {branch.hours.open}.",
        )

    def is_open(
        self,
        branch_id: str,
        now_dt: Optional[datetime] = None,
        mode: Optional[str] = "delivery",
    ) -> bool:
        ok, _ = self.check_open(branch_id, now_dt=now_dt, mode=mode)
        return ok

    # ------------------------------------------------------------------
    # Location pin & address resolution
    # ------------------------------------------------------------------
    def resolve_by_pin(
        self, lat: float, lng: float
    ) -> Tuple[Optional[Branch], Optional[BranchZone], float, Optional[str]]:
        """
        Finds the nearest branch whose max_km covers (lat, lng), and the matching zone.
        Returns (branch, zone, distance_km, error_code).
        """
        distances: List[Tuple[float, Branch]] = []
        for branch in self._data.branches:
            dist = haversine_km(lat, lng, branch.lat, branch.lng)
            distances.append((dist, branch))

        if not distances:
            return None, None, 0.0, "OUT_OF_AREA"

        distances.sort(key=lambda pair: pair[0])
        for dist, branch in distances:
            if dist <= branch.max_km:
                zone = branch.zone_for_distance(dist)
                if zone:
                    return branch, zone, round(dist, 2), None

        nearest_dist = round(distances[0][0], 2)
        return None, None, nearest_dist, "OUT_OF_AREA"

    @staticmethod
    def _normalize_text(text: str) -> str:
        cleaned = re.sub(r"[^a-z0-9\s]", " ", text.lower())
        # Normalize single-digit Colombo numbers: "colombo 7" -> "colombo 07"
        cleaned = re.sub(r"\bcolombo\s+([1-9])\b", r"colombo 0\1", cleaned)
        return re.sub(r"\s+", " ", cleaned).strip()

    @staticmethod
    def _alias_matches_text(alias: str, norm_text: str, words: List[str]) -> bool:
        norm_alias = BranchRepo._normalize_text(alias)
        # 1. Exact word-boundary phrase match
        if re.search(rf"\b{re.escape(norm_alias)}\b", norm_text):
            return True

        # Do not fuzzy-match aliases that contain digits (e.g. "colombo 07" vs "colombo 10")
        if any(ch.isdigit() for ch in norm_alias):
            return False

        # 2. Fuzzy n-gram match (ratio >= 85)
        alias_words = norm_alias.split()
        n = len(alias_words)
        if len(words) < n:
            return False
        for i in range(len(words) - n + 1):
            candidate = " ".join(words[i : i + n])
            if any(ch.isdigit() for ch in candidate):
                continue
            if _fuzzy_ratio(norm_alias, candidate) >= 85.0:
                return True
        return False

    def resolve_by_address(
        self, address_text: str
    ) -> Tuple[Optional[Branch], Optional[BranchZone], Optional[str]]:
        """
        Matches address_text against branch area_aliases (case-insensitive, fuzzy >= 85).
        Returns (branch, zone, error_code) where error_code is None, OUT_OF_AREA, or NEEDS_CLARIFICATION.
        """
        norm = self._normalize_text(address_text or "")
        if not norm:
            return None, None, "NEEDS_CLARIFICATION"

        # Mask non-Colombo forts ("galle fort", "matara fort", "jaffna fort") so they don't match Colombo Fort
        norm_for_alias = re.sub(r"\b(galle|matara|jaffna|trinco|batticaloa)\s+fort\b", r"\1", norm)

        # Check if the address explicitly names an out-of-coverage town (unless it's just "<town> road")
        for out_area in KNOWN_OUT_OF_AREA:
            if re.search(rf"\b{re.escape(out_area)}(?!\s+(?:road|rd|street|st))\b", norm):
                return None, None, "OUT_OF_AREA"

        words = norm_for_alias.split()
        matched_branches: Dict[str, Tuple[Branch, str]] = {}

        for branch in self._data.branches:
            # Prefer longer/more specific aliases first (e.g. "cinnamon gardens", "colombo 07")
            for alias in sorted(branch.area_aliases, key=len, reverse=True):
                if self._alias_matches_text(alias, norm_for_alias, words):
                    matched_branches[branch.id] = (branch, alias.lower())
                    break

        if len(matched_branches) > 1:
            return None, None, "NEEDS_CLARIFICATION"

        if len(matched_branches) == 1:
            branch, matched_alias = next(iter(matched_branches.values()))
            zone_id = "z1" if matched_alias in ZONE_1_ALIASES else "z2"
            zone = branch.get_zone(zone_id) or (branch.zones[0] if branch.zones else None)
            return branch, zone, None

        return None, None, "NEEDS_CLARIFICATION"


branch_repo = BranchRepo()
