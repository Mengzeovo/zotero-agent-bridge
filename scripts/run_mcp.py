from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "bridge-config.json"


def _load_runtime_config(config_path: Path) -> tuple[str, str]:
    payload = json.loads(config_path.read_text(encoding="utf-8-sig"))
    host = str(payload.get("host") or "127.0.0.1")
    port = int(payload.get("port") or 8765)
    base_url = f"http://{host}:{port}"

    api_token = payload.get("api_token")
    if api_token:
        return base_url, str(api_token)

    bridge_home = Path(str(payload.get("bridge_home") or "")).expanduser()
    token_path = bridge_home / "bridge.generated.json"
    if not token_path.exists():
        raise SystemExit(
            f"Token not found. Either set api_token in config or start the bridge once first: {token_path}"
        )

    token_payload = json.loads(token_path.read_text(encoding="utf-8"))
    token = token_payload.get("api_token")
    if not token:
        raise SystemExit(f"Invalid token file: {token_path}")
    return base_url, str(token)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Zotero Agent Bridge MCP server")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to bridge-config.json",
    )
    args = parser.parse_args(argv)

    config_path = Path(args.config).expanduser().resolve()
    base_url, token = _load_runtime_config(config_path)
    os.environ["ZOTERO_AGENT_BRIDGE_CONFIG"] = str(config_path)

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from zotero_agent_bridge.mcp_server import build_server

    server = build_server(base_url=base_url, token=token)
    server.serve_forever()


if __name__ == "__main__":
    main()
