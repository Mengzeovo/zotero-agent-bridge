# Zotero Pi Assistant

**Current version: 0.4.2-beta**

Zotero Pi Assistant is a Pi-powered literature assistant embedded in the Zotero Item Pane. It reads the selected paper's local PDF, Zotero notes, and annotations; maintains resumable per-paper conversations; renders Markdown and LaTeX; and saves a finalized answer as a Zotero Note after explicit user confirmation.

This repository is Pi-only. Generic Zotero CRUD, MCP, Obsidian synchronization, and classification implementations were physically removed in `0.4.1-beta`. Former HTTP paths remain only as token-authenticated, side-effect-free tombstones returning `410 feature_retired`.

## Features

- Zotero 7–9 Item Pane integration, with Zotero 9 recommended.
- Local PDF, metadata, note, annotation, and page-aware context.
- Streaming Pi responses, abort/reset, model selection, and thinking-level selection.
- Per-paper session history, orphan-session recovery, resume, and continued conversation.
- Markdown, KaTeX, code blocks, and original-LaTeX formula copying.
- “Save Q&A” creates a structured Zotero Note after confirmation, using an isolated no-session Pi process to generate a title of at most 15 visible characters while preserving mathematical `<`, `>`, and `&`.
- “Update Experience Note” incrementally converts source exchanges into a local knowledge ledger, then deterministically rebuilds the unique `Pi 经验笔记` from knowledge units, relations, corrections, and provenance. Unchanged exchanges make no Pi calls; previously extracted knowledge remains available when a source session later disappears.
- XPI-bundled, add-on-managed Windows x64 Bridge; end users do not need Python or repository source.

## Install

1. Download `zotero-agent-bridge-addon-0.4.2-beta.xpi` from Releases.
2. In Zotero, open **Tools → Plugins → Install Plugin From File…**.
3. Select the XPI and restart Zotero.
4. Select a paper with a local PDF and open **Pi Literature Assistant** in the Item Pane.

The stable add-on ID and data paths remain unchanged:

```text
Add-on ID: zotero-agent-bridge@local
%USERPROFILE%\Zotero\zotero-agent-bridge
├─ bridge.generated.json
├─ pi-chat\session-index.json
├─ pi-chat\experience-note-index.json
├─ pi-chat\experience-knowledge\*.json
└─ pi-sessions\*.jsonl
```

Experience notes use three data layers: Pi JSONL files are traceable sources, the knowledge ledger stores exchange-level evidence, units, relations, and source availability, and Zotero's `Pi 经验笔记` is a re-renderable reading view. If a processed source later disappears, its learned knowledge is retained with a warning. A forced rebuild intentionally recreates the ledger only from currently readable sources. Cross-partition relation auditing for very large ledgers has a bounded call budget; if exhausted, the update completes with validated existing relations and an explicit warning instead of making unbounded calls or dropping knowledge units.

## Security boundary

- The private Bridge binds only to loopback and requires the add-on-managed API token.
- Production accepts only the XPI-bundled managed Bridge.
- Pi runs with tools, skills, extensions, and approvals disabled.
- Literature content is treated as untrusted source material.
- Zotero writes are limited to validated `create_assistant_note` and marker-protected `upsert_assistant_experience_note`, both triggered after user confirmation.
- Lifecycle protocol v2 and product scope `zotero-pi-only` are mandatory; pre-v2 rollback is rejected.

## Build and test

Requires Python 3.12+, PowerShell, Node.js, and a configured Pi CLI.

```powershell
py -3.12 -m pip install -e .
py -3.12 -m unittest discover -s tests
powershell -ExecutionPolicy Bypass -File scripts\build_addon_xpi.ps1 -Version 0.4.2-beta -BuildBridge
```

Outputs:

```text
dist\zotero-agent-bridge-addon-0.4.2-beta.xpi
dist\zotero-agent-bridge-addon.xpi
```

## Limitations

- The bundled Bridge currently targets Windows x64 only.
- Pi CLI and model credentials must be configured separately.
- One Bridge instance maintains one active answer at a time.
- OCR, cloud sync, and cross-machine Pi session sync are not included.
- The Bridge EXE is not yet Authenticode-signed.

## License

[MIT](LICENSE)
