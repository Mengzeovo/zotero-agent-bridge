from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from zotero_agent_bridge.addon_client import AddonClient
from zotero_agent_bridge.config import Settings
from zotero_agent_bridge.mirror import MirrorStore
from zotero_agent_bridge.paper_classifier import classify_library
from zotero_agent_bridge.service import BridgeService
from zotero_agent_bridge.write_queue import SerialWriteExecutor
from zotero_agent_bridge.zotero_local import ZoteroLocalClient


def build_service(settings: Settings) -> BridgeService:
    local_client = ZoteroLocalClient(
        settings.zotero_local_api_base,
        settings.user_agent,
        base_attachment_path=str(settings.base_attachment_path) if settings.base_attachment_path else None,
    )
    mirror = MirrorStore(settings.metadata_dir, settings.notes_dir)
    writer = SerialWriteExecutor(
        AddonClient(
            commands_dir=settings.commands_dir,
            responses_dir=settings.responses_dir,
            archive_dir=settings.archive_dir,
            status_path=settings.addon_status_path,
            timeout_seconds=settings.addon_timeout_seconds,
            status_ttl_seconds=settings.addon_status_ttl_seconds,
        ),
        settings.operations_log_path,
    )
    return BridgeService(settings, local_client=local_client, mirror=mirror, writer=writer)


def main() -> None:
    parser = argparse.ArgumentParser(description="Install the current Zotero collection tree and sort papers into it.")
    parser.add_argument(
        "--config",
        default=str(PROJECT_ROOT / "config" / "bridge-config.json"),
        help="Path to the bridge config JSON file.",
    )
    parser.add_argument("--start", type=int, default=0, help="Start offset for top-level Zotero items.")
    parser.add_argument("--limit", type=int, default=500, help="Maximum number of top-level items to scan.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write collection updates back to Zotero. Without this flag the script only previews changes.",
    )
    parser.add_argument(
        "--collection-key",
        default=None,
        help="Only sort items that are currently inside the given Zotero collection key.",
    )
    parser.add_argument(
        "--skip-backup",
        action="store_true",
        help="Do not write a preview backup JSON before applying changes.",
    )
    parser.add_argument(
        "--backup-dir",
        default=str(PROJECT_ROOT / "tmp"),
        help="Directory used for preview backups when --apply is set.",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=None,
        help="Alias of --start kept for convenience.",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=None,
        help="Alias of --limit kept for convenience.",
    )
    parser.add_argument(
        "--dry-run-label",
        default="preview",
        help="Label written into the backup JSON when previewing changes.",
    )
    parser.add_argument(
        "--item-note",
        default="",
        help="Optional note written into the backup JSON for this batch run.",
    )
    parser.add_argument(
        "--stdout-summary",
        action="store_true",
        help="Print a one-line summary before the JSON payload.",
    )
    args = parser.parse_args()

    os.environ["ZOTERO_AGENT_BRIDGE_CONFIG"] = str(Path(args.config).resolve())
    settings = Settings.from_env()
    settings.prepare_runtime()
    service = build_service(settings)

    start = args.offset if args.offset is not None else args.start
    limit = args.max_items if args.max_items is not None else args.limit
    preview = classify_library(
        service,
        apply=False,
        limit=limit,
        start=start,
        collection_key=args.collection_key,
    )

    if args.apply and not args.skip_backup:
        backup_dir = Path(args.backup_dir).resolve()
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_path = backup_dir / f"paper-classify-preview-{timestamp}.json"
        backup_payload = {
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "label": args.dry_run_label,
            "note": args.item_note,
            "config": str(Path(args.config).resolve()),
            "collection_key": args.collection_key,
            "start": start,
            "limit": limit,
            "preview": preview,
        }
        backup_path.write_text(json.dumps(backup_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        backup_path = None

    result = (
        classify_library(service, apply=True, limit=limit, start=start, collection_key=args.collection_key)
        if args.apply
        else preview
    )
    if backup_path is not None:
        result["backup_path"] = str(backup_path)
    result["start"] = start
    result["limit"] = limit

    if args.stdout_summary:
        stats = result["stats"]
        print(
            f"scanned={stats['scanned']} candidates={stats['candidates']} changed={stats['changed']} updated={stats['updated']}"
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
