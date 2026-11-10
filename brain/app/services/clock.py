"""
Timezone-aware clock helper with injectable/freezable time for deterministic testing.
Defaults to Asia/Colombo (+05:30).
"""
from datetime import datetime, timezone, timedelta
from typing import Callable, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from app.config import settings

try:
    COLOMBO_TZ = ZoneInfo(settings.TIMEZONE)
except ZoneInfoNotFoundError:
    # Fallback fixed offset +05:30 on Windows systems without tzdata installed
    COLOMBO_TZ = timezone(timedelta(hours=5, minutes=30))

_clock_override: Optional[Callable[[], datetime]] = None


def now(override: Optional[datetime] = None) -> datetime:
    """Returns current time in Asia/Colombo timezone, or the overridden/frozen time."""
    if override is not None:
        if override.tzinfo is None:
            return override.replace(tzinfo=COLOMBO_TZ)
        return override.astimezone(COLOMBO_TZ)
    if _clock_override is not None:
        dt = _clock_override()
        if dt.tzinfo is None:
            return dt.replace(tzinfo=COLOMBO_TZ)
        return dt.astimezone(COLOMBO_TZ)
    return datetime.now(COLOMBO_TZ)


def set_clock(fixed_dt: datetime | str | Callable[[], datetime]) -> None:
    """Freezes or overrides the clock for tests and simulations."""
    global _clock_override
    if callable(fixed_dt):
        _clock_override = fixed_dt
    elif isinstance(fixed_dt, str):
        parsed = datetime.fromisoformat(fixed_dt)
        _clock_override = lambda: parsed
    else:
        _clock_override = lambda: fixed_dt


def reset_clock() -> None:
    """Restores real wall-clock time."""
    global _clock_override
    _clock_override = None

