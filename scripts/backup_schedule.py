"""InvoSync automated backup scheduler.
Designed to run via cron (Linux) or Task Scheduler (Windows).

Rotation strategy (stored in BACKUP_DIR):
  - Hourly: last 24 hours (24 backups)
  - Daily: last 30 days (30 backups)
  - Monthly: last 12 months (12 backups)

Usage (cron — runs hourly):
    0 * * * * cd /opt/invosync && python scripts/backup_schedule.py

Usage (Task Scheduler — runs daily at 2 AM):
    python scripts/backup_schedule.py --retain-daily 30

Env vars:
    MONGODB_URI   — MongoDB connection string
    BACKUP_DIR    — where backups are stored (default: ./backups/)
"""
import argparse, gzip, json, os, shutil, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backup_mongo import backup

BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "")) or Path(__file__).resolve().parent.parent / "backups"


def prune(backup_dir: Path, hourly: int, daily: int, monthly: int, dry_run: bool = False):
    """Remove old backups beyond retention limits."""
    backups = sorted(
        [d for d in backup_dir.iterdir() if d.is_dir() and d.name.startswith("invo_sync_backup_")],
        reverse=True,
    )
    if not backups:
        return

    now = datetime.now(timezone.utc)
    kept = 0
    daily_seen: set[str] = set()
    monthly_seen: set[str] = set()

    for b in backups:
        try:
            ts_str = b.name.replace("invo_sync_backup_", "")
            ts = datetime.strptime(ts_str, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue

        age_hours = (now - ts).total_seconds() / 3600

        # Hourly: keep last N hours
        if age_hours <= hourly:
            kept += 1
            continue

        # Daily: keep one per day for last N days
        day_key = ts.strftime("%Y%m%d")
        age_days = age_hours / 24
        if age_days <= daily and day_key not in daily_seen:
            daily_seen.add(day_key)
            kept += 1
            continue

        # Monthly: keep one per month for last N months
        month_key = ts.strftime("%Y%m")
        age_months = age_days / 30
        if age_months <= monthly and month_key not in monthly_seen:
            monthly_seen.add(month_key)
            kept += 1
            continue

        # Prune
        if dry_run:
            print(f"  [DRY-RUN] Would delete: {b.name}")
        else:
            shutil.rmtree(b)
            print(f"  [PRUNE] Deleted: {b.name}")


def main():
    parser = argparse.ArgumentParser(description="InvoSync backup scheduler")
    parser.add_argument("--retain-hourly", type=int, default=24, help="Keep hourly backups for N hours (default: 24)")
    parser.add_argument("--retain-daily", type=int, default=30, help="Keep daily backups for N days (default: 30)")
    parser.add_argument("--retain-monthly", type=int, default=12, help="Keep monthly backups for N months (default: 12)")
    parser.add_argument("--out", default=str(BACKUP_DIR), help="Backup directory")
    parser.add_argument("--uri", default=os.getenv("MONGODB_URI", "mongodb://localhost:27017"), help="MongoDB URI")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be pruned without deleting")
    parser.add_argument("--quiet", action="store_true", help="Suppress output")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Run backup
    if not args.quiet:
        print(f"[{now_str}] Starting backup...")
    backup(args.uri, str(out_dir), quiet=args.quiet)

    # Prune old backups
    if not args.quiet:
        print(f"[{now_str}] Pruning old backups...")
    prune(out_dir, args.retain_hourly, args.retain_daily, args.retain_monthly, dry_run=args.dry_run)

    if not args.quiet:
        print(f"[{now_str}] Backup complete.")

    # Exit code: 0 if backup dir has at least one valid backup
    valid = [d for d in out_dir.iterdir() if d.is_dir() and d.name.startswith("invo_sync_backup_")]
    sys.exit(0 if valid else 1)


if __name__ == "__main__":
    main()
