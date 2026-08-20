from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    bridge_home = Path(os.environ["ZOTERO_AGENT_BRIDGE_HOME_FOR_LOGS"])
    log_dir = bridge_home / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / "bridge-stdout.log"
    stderr_path = log_dir / "bridge-stderr.log"
    with stdout_path.open("a", encoding="utf-8", buffering=1) as stdout, stderr_path.open(
        "a", encoding="utf-8", buffering=1
    ) as stderr:
        sys.stdout = stdout
        sys.stderr = stderr
        from zotero_agent_bridge.__main__ import main as bridge_main

        bridge_main()


if __name__ == "__main__":
    main()
