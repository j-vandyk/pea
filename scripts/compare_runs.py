"""
compare_runs.py — compare two PEA pipeline run summaries side by side.

Supports local file paths and Azure blob URLs (az://container/prefix).

Usage:
    # Compare against saved baseline
    python scripts/compare_runs.py az://pea-data/runs/summary_<run_id>.json

    # Set a blob summary as the new baseline
    python scripts/compare_runs.py --set-baseline az://pea-data/runs/summary_<run_id>.json

    # List available summary files in blob storage
    python scripts/compare_runs.py --list

    # Compare two specific summaries (local or blob)
    python scripts/compare_runs.py az://pea-data/runs/summary_A.json az://pea-data/runs/summary_B.json

Requires AZURE_STORAGE_CONNECTION_STRING in environment (or .env file).
"""

import argparse
import io
import json
import os
import shutil
import sys
from pathlib import Path

BASELINE_PATH = Path("data/validation/baseline_summary.json")


def _blob_client():
    from azure.storage.blob import BlobServiceClient
    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if not conn_str:
        print("ERROR: AZURE_STORAGE_CONNECTION_STRING not set. Run: set -a; source .env; set +a")
        sys.exit(1)
    return BlobServiceClient.from_connection_string(conn_str)


def _parse_blob_url(url: str):
    """az://container/path/to/blob → (container, blob_path)"""
    parts = url[5:].split("/", 1)
    return parts[0], parts[1] if len(parts) > 1 else ""


def _load(path: str) -> dict:
    if path.startswith("az://"):
        container, blob_path = _parse_blob_url(path)
        client = _blob_client().get_blob_client(container, blob_path)
        data = client.download_blob().readall()
        return json.loads(data)
    with open(path) as f:
        return json.load(f)


def _save(data: dict, path: str):
    if path.startswith("az://"):
        container, blob_path = _parse_blob_url(path)
        client = _blob_client().get_blob_client(container, blob_path)
        client.upload_blob(json.dumps(data, indent=2).encode(), overwrite=True)
    else:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)


def _list_summaries(container: str = "pea-data", prefix: str = "runs/summary_"):
    blobs = _blob_client().get_container_client(container).list_blobs(name_starts_with=prefix)
    results = sorted([b.name for b in blobs], reverse=True)
    if not results:
        print("No summary files found in blob storage.")
        return
    print(f"\nAvailable summaries in az://{container}/{prefix}*\n")
    for name in results:
        print(f"  az://{container}/{name}")
    print()


def _pct_change(old: float, new: float) -> str:
    if old == 0:
        return "+∞" if new > 0 else "—"
    change = (new - old) / old * 100
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.1f}%"


def _compare_dicts(label: str, old: dict, new: dict):
    keys = sorted(set(list(old.keys()) + list(new.keys())))
    print(f"\n  {label}")
    print(f"  {'':30s} {'baseline':>10s} {'new run':>10s} {'change':>10s}")
    print(f"  {'-'*62}")
    for k in keys:
        a = old.get(k, 0)
        b = new.get(k, 0)
        print(f"  {k:30s} {a:>10} {b:>10} {_pct_change(a, b):>10s}")


def compare(baseline_path: str, new_path: str):
    baseline = _load(baseline_path)
    new = _load(new_path)

    print(f"\n{'='*66}")
    print(f"  PEA Run Comparison")
    print(f"  Baseline : {baseline.get('run_id', baseline_path)}")
    print(f"  New run  : {new.get('run_id', new_path)}")
    print(f"{'='*66}")

    print(f"\n  {'METRIC':30s} {'baseline':>10s} {'new run':>10s} {'change':>10s}")
    print(f"  {'-'*62}")
    for key, label in [("total_events", "total events"), ("total_failures", "failures")]:
        a = baseline.get(key, 0)
        b = new.get(key, 0)
        print(f"  {label:30s} {a:>10} {b:>10} {_pct_change(a, b):>10s}")

    _compare_dicts("Events by country", baseline.get("events_by_country", {}), new.get("events_by_country", {}))
    _compare_dicts("Events by type", baseline.get("events_by_type", {}), new.get("events_by_type", {}))
    _compare_dicts("Events by turmoil level", baseline.get("events_by_turmoil_level", {}), new.get("events_by_turmoil_level", {}))
    _compare_dicts("Events by confidence", baseline.get("events_by_confidence", {}), new.get("events_by_confidence", {}))

    print(f"\n{'='*66}\n")


def set_baseline(source_path: str):
    data = _load(source_path)
    _save(data, str(BASELINE_PATH))
    print(f"Baseline saved: {BASELINE_PATH}  (run_id: {data.get('run_id', source_path)})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare two PEA run summaries (local or Azure blob)")
    parser.add_argument("--set-baseline", metavar="PATH", help="Save a summary as the new baseline (local or az://)")
    parser.add_argument("--list", action="store_true", help="List available summary files in blob storage")
    parser.add_argument("new_run", nargs="?", help="New run summary to compare (local path or az://container/blob)")
    parser.add_argument("baseline", nargs="?", default=str(BASELINE_PATH), help="Baseline to compare against (default: data/validation/baseline_summary.json)")
    args = parser.parse_args()

    if args.list:
        _list_summaries()
    elif args.set_baseline:
        set_baseline(args.set_baseline)
    elif args.new_run:
        if not args.new_run.startswith("az://") and not Path(args.baseline).exists():
            print(f"No baseline found at {args.baseline}. Run with --set-baseline first.")
            sys.exit(1)
        compare(args.baseline, args.new_run)
    else:
        parser.print_help()
