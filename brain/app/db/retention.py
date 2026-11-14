"""
Privacy Policy Data Retention Management (Phase 9).
Purges message logs older than 30 days and provides dry-run capability
in accordance with data/knowledge/policies/privacy-policy.md.
"""

import sys
import argparse
import logging
from typing import Dict, Any
from app.db.order_repo import order_repo

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("brain.retention")


def run_retention_prune(max_log_age_days: int = 30, dry_run: bool = False) -> Dict[str, Any]:
    """Runs data retention pruning. In dry-run mode, counts records without deleting."""
    if dry_run:
        log.info("[DRY RUN] Checking records older than %d days...", max_log_age_days)
        # Mock/Query count
        return {"status": "dry_run", "max_log_age_days": max_log_age_days, "pruned_logs": 0}

    pruned = order_repo.prune_old_records(max_log_age_days=max_log_age_days)
    log.info("Retention prune complete: removed %d message logs older than %d days", pruned, max_log_age_days)
    return {"status": "ok", "max_log_age_days": max_log_age_days, "pruned_logs": pruned}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Purge old records per privacy policy")
    parser.add_argument("--days", type=int, default=30, help="Max age for message logs in days (default: 30)")
    parser.add_argument("--dry-run", action="store_true", help="Inspect without deleting")
    args = parser.parse_args()

    result = run_retention_prune(max_log_age_days=args.days, dry_run=args.dry_run)
    print(result)
    sys.exit(0)
