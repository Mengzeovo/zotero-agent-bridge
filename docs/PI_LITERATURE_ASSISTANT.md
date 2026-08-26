# Zotero Pi Assistant 0.4.2-beta

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
- `POST /assistant/experience-note/update`
- `GET /assistant/experience-note/jobs/{job_id}`
- `POST /assistant/session/abort`
- `POST /assistant/session/reset`

The HTTP server is an internal add-on transport, not a public Agent API.

## Removed surfaces

As of `0.4.1-beta`, former CRUD, sync, Obsidian, MCP, session-close, classification, and external-launcher implementations are physically absent. Former HTTP paths remain only as Bridge-token-authenticated, side-effect-free tombstones returning `410 feature_retired`. No removed console entry point or compatibility script is packaged.

## Note-save boundary

“Save Q&A” always creates a new child Note. When the backward-compatible optional title is omitted, an isolated no-session Pi process—with tools, extensions, skills, context files, prompt templates, and themes disabled—generates a title capped at 15 visible characters. Generation failure falls back to the first 15 characters of the question, then answer, then `Pi问答记录`.

“Update Experience Note” is asynchronous and incremental. It reconstructs the active branch of every current, reset, archived, alternate-attachment, changed-path, and recovered JSONL source for the same `library_id + parent item_key`. Each finalized exchange receives a semantic content digest. New or changed exchanges are converted by an isolated no-session Pi process into validated knowledge evidence; unchanged exchanges reuse their ledger entries without a Pi call.

The Bridge keeps three distinct data layers:

1. Pi JSONL sessions are traceable source material.
2. `pi-chat/experience-knowledge/<scope-hash>.json` is the atomic knowledge ledger containing source status, exchange evidence, knowledge units, controlled relations, corrections, and provenance.
3. The marked Zotero `Pi 经验笔记` is a deterministic Markdown/HTML view rendered from the ledger.

The final renderer organizes learning outcomes rather than recursively compressing them. Every active knowledge unit must appear in a section; omitted unit IDs are repaired or appended to `待整理知识`. Missing or corrupt sources retain previously extracted knowledge with an explicit provenance warning. Large catalogs use partitioned planning plus compact cross-partition relation auditing. `pi.experience_cross_link_max_calls` (default `8`, range `0..64`) bounds cross-link Pi calls; if candidate coverage exceeds that budget, validated existing relations and every knowledge unit are retained, the Note is completed, and `knowledge_cross_partition_budget_exhausted` is reported. A request with optional `force_rebuild: true` discards processing marks and rebuilds from currently readable sources. Existing requests remain backward compatible.

Experience jobs preserve the existing top-level status contract (`queued`, `collecting`, `generating`, `writing`, `completed`, `failed`). The `stage` field reports `extracting`, `reconciling`, `linking`, or `rendering`. Optional counters report new/reused exchanges, knowledge units, relations, retained missing-source knowledge, AI calls, and update mode (`initial_build`, `incremental`, `up_to_date`, `migration`, or `full_rebuild`).

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

## Knowledge-ledger recovery

- A corrupt per-paper ledger is quarantined as `*.corrupt-<timestamp>` and the next update performs an initial rebuild without overwriting the Zotero Note until generation and write succeed.
- A missing or corrupt JSONL source keeps previously extracted evidence with `source_missing` provenance and a visible warning.
- `force_rebuild: true` intentionally discards cached processing marks and reconstructs knowledge only from currently readable active branches; it is a recovery operation, not the default UI behavior.
- Knowledge state is committed only after the marked Zotero Note is successfully upserted. If Note writing fails, exchange processing marks remain unchanged. If state persistence fails after Note writing, the next update safely reprocesses the source rather than skipping it.

## Security model

Pi is launched with tools, skills, prompt templates, extensions, context files, and automatic approval disabled. Literature content and existing knowledge fields are delimited as untrusted source material. Structured extraction is schema-validated, unknown exchange/unit IDs are rejected, and invalid JSON receives at most one isolated repair attempt. The ledger stores neither image bytes nor hidden Pi thinking. Markdown/HTML escaping remains outside Pi. Zotero writes remain outside Pi and require an explicit add-on confirmation.

## Build

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_addon_xpi.ps1 -Version 0.4.2-beta -BuildBridge
```

Normal users install the XPI and do not need Python, pip, source checkout, legacy launchers, MCP registration, or Obsidian integration.
