# Zotero Pi Assistant Add-on

This bootstrapped Zotero add-on provides the Pi literature assistant panel and manages its bundled private Bridge.

## Responsibilities

- Register the Item Pane and reader-side Pi chat panels.
- Verify, install, start, health-check, roll back, and stop the bundled Bridge.
- Maintain the managed loopback configuration and API token.
- Render Markdown and KaTeX while preserving original LaTeX for copy operations.
- Execute the single allowed Zotero write command: `create_assistant_note`.

## Private queue command

```json
{
  "request_id": "<uuid>",
  "command": "create_assistant_note",
  "payload": {
    "item_key": "ABCD1234",
    "attachment_key": "PDFD1234",
    "document_id": "<sha256>",
    "context_fingerprint": "<sha256>",
    "markdown": "# Pi 阅读助手记录",
    "note_html": "<h1>Pi 阅读助手记录</h1>"
  }
}
```

All former generic queue commands are rejected as `unsupported_command` and cannot mutate Zotero.

## Stable identity

- Add-on ID: `zotero-agent-bridge@local`
- Bridge home: `<Zotero data directory>/zotero-agent-bridge`
- Managed binary root: `%LOCALAPPDATA%\ZoteroAgentBridge\bridge`

These identifiers remain unchanged for upgrade compatibility.
