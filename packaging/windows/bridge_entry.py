from __future__ import annotations

import multiprocessing
import os
import sys
from pathlib import Path


def _redirect_logs() -> None:
    bridge_home = os.environ.get("ZOTERO_AGENT_BRIDGE_HOME_FOR_LOGS")
    if not bridge_home:
        return
    log_dir = Path(bridge_home).expanduser().resolve() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    sys.stdout = (log_dir / "bridge-stdout.log").open("a", encoding="utf-8", buffering=1)
    sys.stderr = (log_dir / "bridge-stderr.log").open("a", encoding="utf-8", buffering=1)


def main() -> None:
    multiprocessing.freeze_support()
    os.environ.setdefault("ZOTERO_AGENT_BRIDGE_DISTRIBUTION", "xpi-bundled")
    _redirect_logs()
    from zotero_agent_bridge.__main__ import main as bridge_main

    bridge_main()


if __name__ == "__main__":
    main()
