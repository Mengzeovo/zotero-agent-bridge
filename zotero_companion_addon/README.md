# Zotero Agent Bridge Companion Add-on

This add-on runs inside Zotero and executes write commands for the external `zotero-agent-bridge` service.

## What it does

- Polls a shared runtime directory for queued command JSON files
- Executes write operations through Zotero's JavaScript API
- Writes responses back for the bridge service to consume
- Maintains a heartbeat/status file and a local add-on log

## Runtime directory

The add-on resolves its bridge home in this order:

1. `config/default-config.json` `bridgeHome` if non-empty
2. `<Zotero.DataDirectory.dir>/zotero-agent-bridge`

Under that directory it expects:

- `commands/`
- `responses/`
- `archive/`
- `logs/`
- `status/`

## Install

1. Zip the contents of this folder into an `.xpi` archive.
2. In Zotero, open `Tools -> Plugins`.
3. Install the `.xpi` from file.
4. Restart Zotero if prompted.

## Command format

Each file in `commands/` should be a UTF-8 JSON document with at least:

```json
{
  "request_id": "req-123",
  "command": "create_item",
  "payload": {}
}
```

Supported commands:

- `create_item`
- `update_item`
- `attach_linked_pdf`
- `create_note`

Responses are written to `responses/<request_id>.json`.
