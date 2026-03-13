# Zotero Agent Bridge

`zotero-agent-bridge` is a local bridge that lets any agent talk to Zotero through:

- a token-protected HTTP JSON API on `127.0.0.1`
- an MCP stdio wrapper that forwards the same operations
- a Zotero companion add-on that performs write operations inside Zotero

## What it does

- reads items, notes, attachments, tags, and collections from Zotero Local API
- creates and updates items through a companion add-on
- links PDFs from an external paper vault instead of copying them into Zotero storage
- stores an agent-friendly mirror in this repository under:
  - `metadata/zotero_bridge/`
  - `notes/zotero_bridge/`
- stores the bridge runtime queue, logs, add-on status, and generated token under the bridge home

## HTTP API

All HTTP requests require either:

- `X-Bridge-Token: <token>`
- `Authorization: Bearer <token>`

Endpoints:

- `GET /health`
- `GET /capabilities`
- `GET /items/search?q=...`
- `GET /items/{itemKey}`
- `POST /items`
- `PATCH /items/{itemKey}`
- `POST /items/{itemKey}/attachments/linked-pdf`
- `POST /items/{itemKey}/notes`
- `POST /sync/export`

## Configuration

The bridge reads optional config from:

- `ZOTERO_AGENT_BRIDGE_CONFIG`
- or `./zotero_agent_bridge.json`

Environment variables override file values:

- `ZOTERO_AGENT_BRIDGE_TOKEN`
- `ZOTERO_AGENT_BRIDGE_HOME`
- `ZOTERO_AGENT_BRIDGE_HOST`
- `ZOTERO_AGENT_BRIDGE_PORT`
- `ZOTERO_AGENT_BRIDGE_LOCAL_API_BASE`
- `ZOTERO_AGENT_BRIDGE_METADATA_DIR`
- `ZOTERO_AGENT_BRIDGE_NOTES_DIR`

If no token is provided, the bridge generates one and persists it under the bridge home.

Default bridge home:

- Windows: `%USERPROFILE%\\Zotero\\zotero-agent-bridge`

## Run

```powershell
python -m pip install -e .
python -m zotero_agent_bridge
```

## MCP

Run the MCP wrapper after the HTTP service is up:

```powershell
python scripts/run_mcp.py
```

Supported MCP tools:

- `search_items`
- `create_item`
- `update_item`
- `import_pdf`
- `create_note`
- `export_item`

The server also advertises lightweight MCP resources for desktop clients:

- `zotero://server/info`
- `zotero://bridge/health`
- `zotero://bridge/capabilities`
- `zotero://items/{item_key}`

For Codex Desktop or Codex CLI, the most reliable registration is a direct Python entrypoint with an absolute interpreter path, a fixed `cwd`, and a longer startup timeout. Example:

```toml
[mcp_servers.zotero-agent-bridge]
command = 'C:\Path\To\python.exe'
args = ['E:\0-CodeVault\zotero-agent-bridge\scripts\run_mcp.py']
cwd = 'E:\0-CodeVault\zotero-agent-bridge'
startup_timeout_sec = 30
env = { PYTHONUTF8 = '1' }
```

## Companion add-on

The companion add-on lives in `zotero_companion_addon/` and is responsible for:

- creating items
- updating items
- linking PDFs
- creating notes

It watches the shared bridge home, processes queued commands, and writes response files back for the Python bridge to pick up.
