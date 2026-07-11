"""Standalone MongoDB backup script for InvoSync.
Safe to run while app is live (no locks). Dumps each collection to JSON.gz.

Usage:
    python scripts/backup_mongo.py
    python scripts/backup_mongo.py --uri "mongodb://..." --out ./backups
    python scripts/backup_mongo.py --quiet
"""
import argparse, gzip, json, os, sys
from datetime import datetime
from pathlib import Path

try:
    from pymongo import MongoClient
except ImportError:
    print("pymongo not installed. Run: pip install pymongo")
    sys.exit(1)

URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
OUT = os.getenv("BACKUP_DIR", str(Path(__file__).resolve().parent.parent / "backups"))
DB_NAME = "invoice_tally"


def backup(uri: str, out_dir: str, quiet: bool = False):
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out = Path(out_dir) / f"invo_sync_backup_{ts}"
    out.mkdir(parents=True, exist_ok=True)

    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    db = client[DB_NAME]
    collections = db.list_collection_names()

    if not collections:
        print(f"[WARN] No collections found in '{DB_NAME}'")

    count_total = 0
    for col_name in sorted(collections):
        docs = list(db[col_name].find({}))
        count_total += len(docs)
        path = out / f"{col_name}.json.gz"
        with gzip.open(str(path), "wt", encoding="utf-8") as f:
            json.dump(docs, f, default=str, indent=2, ensure_ascii=False)
        if not quiet:
            print(f"  {col_name}: {len(docs)} docs -> {path.name}")

    meta = {
        "backup_time": ts,
        "uri_redacted": uri.replace(uri.split("@")[-1] if "@" in uri else uri, "***"),
        "database": DB_NAME,
        "collections": len(collections),
        "total_docs": count_total,
    }
    with open(str(out / "_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    client.close()

    if not quiet:
        print(f"\nDone: {count_total} docs across {len(collections)} collections")
        print(f"Path: {out}")
    return str(out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="InvoSync MongoDB backup")
    parser.add_argument("--uri", default=URI, help="MongoDB URI (default: $MONGODB_URI or localhost)")
    parser.add_argument("--out", default=OUT, help="Output directory (default: ./backups/)")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-collection output")
    args = parser.parse_args()
    backup(args.uri, args.out, args.quiet)
