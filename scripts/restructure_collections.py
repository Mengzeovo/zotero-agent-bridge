from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from zotero_agent_bridge.addon_client import AddonClient
from zotero_agent_bridge.collection_tree import apply_default_collection_tree
from zotero_agent_bridge.config import Settings
from zotero_agent_bridge.write_queue import SerialWriteExecutor
from zotero_agent_bridge.zotero_local import ZoteroLocalClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Restructure the Zotero collection tree to the recommended layout.")
    parser.add_argument(
        "--config",
        default=str(PROJECT_ROOT / "config" / "bridge-config.json"),
        help="Path to the bridge config JSON file.",
    )
    args = parser.parse_args()

    os.environ["ZOTERO_AGENT_BRIDGE_CONFIG"] = str(Path(args.config).resolve())
    settings = Settings.from_env()
    local_client = ZoteroLocalClient(
        settings.zotero_local_api_base,
        settings.user_agent,
        base_attachment_path=str(settings.base_attachment_path) if settings.base_attachment_path else None,
    )
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

    result = apply_default_collection_tree(local_client, writer)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
