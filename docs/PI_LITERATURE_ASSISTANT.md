# Pi Literature Assistant for Zotero 9

The Zotero companion add-on embeds a Pi-powered literature chat panel in the Zotero 9 Item Pane. Version 0.3.0 Beta bundles a self-contained Windows x64 Bridge inside the XPI. The Bridge alone owns and manages Pi RPC processes, so Zotero never launches or kills Pi directly.

## Capabilities

- Selects a local PDF attachment from the active Zotero item.
- Sends metadata, complete paginated PDF text, Zotero child notes, and PDF annotations as structured untrusted context.
- Runs Pi with the selected PDF directory as `cwd`.
- Persists one Pi session per Zotero document and restores its transcript after Bridge restarts.
- Streams responses through authenticated HTTP cursor polling.
- Saves a completed answer as a Zotero child Note only after an explicit confirmation in Zotero.

## Requirements

- Zotero 9 (`9.0.*` is declared by add-on version `0.3.0`).
- Windows x64 for the bundled 0.3.0 Bridge.
- Pi installed and available through the configured executable.
- A local PDF attachment. Linked-file and stored-file attachments are supported when Zotero can resolve the local path.

`pdftotext` is optional. The Bridge falls back to `pypdf` when Poppler is unavailable.

## Build and install the add-on

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_addon_xpi.ps1
```

Install `dist/zotero-agent-bridge-addon-0.3.0.xpi` from Zotero **Tools → Plugins → Install Plugin From File…**. The XPI verifies and installs the Bridge under `%LOCALAPPDATA%\ZoteroAgentBridge\bridge\<version>` and keeps Bridge configuration, API Token, status, logs, and Pi sessions under the Bridge home.

Normal users do not need Python, pip, a repository checkout, or launcher registration. The 0.3.0 Beta executable is unsigned; Authenticode signing is a release blocker for a stable build.

The manifest uses the repository's real update channel:

- update manifest: `https://raw.githubusercontent.com/Mengzeovo/zotero-agent-bridge/main/updates.json`
- XPI: `https://raw.githubusercontent.com/Mengzeovo/zotero-agent-bridge/main/dist/zotero-agent-bridge-addon-0.3.0.xpi`

## Bridge configuration

Copy `config/bridge-config.example.json` and adjust the `pi` block:

```json
{
  "host": "127.0.0.1",
  "port": 8765,
  "pi": {
    "executable": "pi",
    "session_dir": "./runtime/pi-sessions",
    "cwd_mode": "selected_pdf_directory",
    "system_prompt_path": "./config/literature-assistant.md",
    "thinking_level": "medium",
    "idle_timeout_seconds": 1800,
    "max_context_chars": 500000,
    "poll_interval_ms": 300
  }
}
```

Relevant environment overrides begin with `ZOTERO_AGENT_BRIDGE_PI_`, including `EXECUTABLE`, `SESSION_DIR`, `SYSTEM_PROMPT_PATH`, `MODEL`, `THINKING_LEVEL`, `IDLE_TIMEOUT`, `MAX_CONTEXT_CHARS`, and `POLL_INTERVAL_MS`.

On first 0.3.0 startup, the add-on creates a managed Bridge configuration and API Token. Compatible settings from a 0.2.2 `bridge-launcher.json` or referenced JSON config are migrated through an explicit allowlist; old launcher commands are never executed. The legacy registration script remains available only for source-development and compatibility workflows.

Opening Zotero automatically starts the verified bundled Bridge when none is running. Pi remains lazy and starts only when a literature session is opened. A compatible Bridge already started by Obsidian, MCP, or the user is treated as shared and is not stopped when Zotero exits. A Bridge started by the add-on is stopped through the owner-authenticated lifecycle API; stale add-on heartbeat detection provides crash cleanup.

For multiple Zotero instances, assign each instance a distinct `extensions.zotero.httpServer.port` and point `zotero_local_api_base` to that port.

## Assistant HTTP API

All endpoints require the normal Bridge token.

- `POST /assistant/session/open`
- `GET /assistant/session/status`
- `POST /assistant/session/message`
- `GET /assistant/session/events?after=<cursor>`
- `GET /assistant/session/messages`
- `POST /assistant/session/abort`
- `POST /assistant/session/reset`
- `GET /assistant/session/history`
- `POST /assistant/session/resume`
- `POST /assistant/session/save-note`
- `GET /lifecycle`
- `POST /lifecycle/shutdown` (requires the matching add-on owner token)

The save request is bound to the current `item_key`, `attachment_key`, context fingerprint, and Pi document ID. Only an authoritative assistant message with `stopReason == "stop"` can be saved.

## Security model

Pi is launched with:

```text
--no-context-files --no-skills --no-prompt-templates --no-extensions --no-tools --no-approve
```

PDF text, metadata, notes, and annotations are marked as untrusted source material. They cannot grant tools or change the system role. Zotero writes remain outside Pi and require a confirmed add-on action.

External text is rendered with `textContent` in the panel. Saved-note metadata, questions, and answers are HTML-escaped before Markdown conversion.

## Session and context behavior

- Only one Pi RPC process is active in the MVP.
- A document identity includes library/item identity and the canonical PDF path.
- Context fingerprints cover the PDF hash and stable metadata, note, and annotation content.
- The complete context is injected on the first question and reinjected after the fingerprint changes.
- Session JSONL files and the document registry are stored under the configured Pi session directory.
- Resetting archives the current session file into the document's history list (capped at 20); the History button lists archived sessions with a preview of the first question and can resume one so the conversation continues where it left off. Resuming archives the previously current session and requires a fresh context injection on the next question.
- Idle processes are reaped; reopening the document resumes the persisted session.

## Deferred scope

The following are intentionally not part of this MVP:

- WebSocket or Server-Sent Events; cursor-based HTTP short polling is used.
- Multiple concurrent Pi processes or simultaneous answers for multiple papers.
- OCR for scanned/image-only PDFs.
- Automatic Zotero writes, autonomous note creation, or Pi tool access.
- Cross-machine/cloud transcript synchronization.
- Arbitrary file browsing outside the server-prepared literature context.
- macOS/Linux bundled executables and automatic launchers.
- Authenticode signing; 0.3.0 is distributed only as an unsigned Beta.

## Validation

The implementation is covered by Python, HTTP, Pi RPC, reading-context, and Node-based UI tests. The production validation command is:

```powershell
py -3.12 -m unittest discover -s tests -q
py -3.12 -m compileall -q zotero_agent_bridge tests
powershell -ExecutionPolicy Bypass -File scripts/build_addon_xpi.ps1
```
