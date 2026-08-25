from __future__ import annotations

from .retirement import retired_main


def main() -> None:
    raise SystemExit(retired_main("zotero-agent-bridge-mcp"))


if __name__ == "__main__":
    main()
