# Zotero Pi Assistant 0.4.0-beta

Zotero Pi Assistant embeds a Pi-powered literature chat panel in the Zotero Item Pane. The XPI bundles a private Windows x64 Bridge; the add-on owns Bridge lifecycle, while the Bridge owns Pi RPC lifecycle.

## Retained product surface

- Open the selected Zotero paper and resolve its local PDF attachment.
- Build structured context from metadata, paginated PDF text, child notes, and PDF annotations.
- Start Pi lazily with the PDF directory as `cwd`.
- Stream responses through authenticated cursor polling.
- Select Pi model and thinking level.
- Archive, list, recover, resume, and continue per-paper Pi sessions.
- Save a finalized answer as a Zotero child Note after explicit user confirmation.

## Private HTTP routes

Every route requires the managed Bridge token.

- `GET /health`
- `GET /lifecycle`
- `POST /lifecycle/shutdown`
- `POST /assistant/session/open`
- `POST /assistant/session/message`
- `GET /assistant/session/events`
- `GET /assistant/session/messages`
- `GET /assistant/session/history`
- `POST /assistant/session/resume`
- `GET /assistant/models`
- `POST /assistant/session/model`
- `GET /assistant/thinking-levels`
- `POST /assistant/session/thinking-level`
- `GET /assistant/session/status`
- `POST /assistant/session/save-note`
- `POST /assistant/session/abort`
- `POST /assistant/session/reset`

The HTTP server is an internal add-on transport, not a public Agent API.

## Retired compatibility surface

During `0.4.0-beta`, former CRUD, sync, Obsidian, MCP, and session-close routes remain authenticated but return:

```json
{
  "error": {
    "code": "feature_retired",
    "message": "This integration surface is no longer supported by Zotero Pi Assistant."
  }
}
```

They perform no Zotero or filesystem side effects. The compatibility shells are scheduled for physical removal in `0.4.1-beta` after release validation.

## Note-save boundary

Saving is accepted only when all of the following match the active context:

- Zotero item key
- attachment key
- context fingerprint
- Pi document ID
- finalized assistant answer (`stopReason == "stop"`)

The Bridge submits only `create_assistant_note` to the add-on queue. The add-on validates the document/fingerprint format, resolves the parent Zotero item, converts Markdown with Better Notes when available, and writes one child Note.

## Session identity and persistence

Stable paths are preserved:

```text
%USERPROFILE%\Zotero\zotero-agent-bridge\pi-chat\session-index.json
%USERPROFILE%\Zotero\zotero-agent-bridge\pi-sessions\*.jsonl
```

A document ID continues to derive from library/item identity, attachment identity, and canonical PDF path. Reset archives rather than deletes the current session. Up to 20 archived sessions are indexed per paper, and orphan JSONL sessions can be recovered by their exact Pi session name.

## Security model

Pi is launched with tools, skills, prompt templates, extensions, context files, and automatic approval disabled. Literature content is delimited as untrusted source material. Zotero writes remain outside Pi and require an explicit add-on confirmation.

## Build

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_addon_xpi.ps1 -Version 0.4.0-beta -BuildBridge
```

Normal users install the XPI and do not need Python, pip, source checkout, legacy launchers, MCP registration, or Obsidian integration.
