# Zotero Pi Assistant

**Current version: 0.4.1-beta**

Zotero Pi Assistant is a Pi-powered literature assistant embedded in the Zotero Item Pane. It reads the selected paper's local PDF, Zotero notes, and annotations; maintains resumable per-paper conversations; renders Markdown and LaTeX; and saves a finalized answer as a Zotero Note after explicit user confirmation.

This repository is Pi-only. Generic Zotero CRUD APIs, MCP, Obsidian synchronization, classification tools, external launchers, and their transition compatibility shells were physically removed in `0.4.1-beta`. Former HTTP paths now return ordinary `404 Not Found` responses.

## Features

- Zotero 7–9 Item Pane integration, with Zotero 9 recommended.
- Local PDF, metadata, note, annotation, and page-aware context.
- Streaming Pi responses, abort/reset, model selection, and thinking-level selection.
- Per-paper session history, orphan-session recovery, resume, and continued conversation.
- Markdown, KaTeX, code blocks, and original-LaTeX formula copying.
- Confirmed Zotero Note saving with mathematical `<`, `>`, and `&` preserved.
- XPI-bundled, add-on-managed Windows x64 Bridge; end users do not need Python or repository source.

## Install

1. Download `zotero-agent-bridge-addon-0.4.1-beta.xpi` from Releases.
2. In Zotero, open **Tools → Plugins → Install Plugin From File…**.
3. Select the XPI and restart Zotero.
4. Select a paper with a local PDF and open **Pi Literature Assistant** in the Item Pane.

The stable add-on ID and data paths remain unchanged:

```text
Add-on ID: zotero-agent-bridge@local
%USERPROFILE%\Zotero\zotero-agent-bridge
├─ bridge.generated.json
├─ pi-chat\session-index.json
└─ pi-sessions\*.jsonl
```

## Security boundary

- The private Bridge binds only to loopback and requires the add-on-managed API token.
- Production accepts only the XPI-bundled managed Bridge.
- Pi runs with tools, skills, extensions, and approvals disabled.
- Literature content is treated as untrusted source material.
- The only Zotero write command is validated `create_assistant_note`, triggered after user confirmation.
- Lifecycle protocol v2 and product scope `zotero-pi-only` are mandatory; pre-v2 rollback is rejected.

## Build and test

Requires Python 3.12+, PowerShell, Node.js, and a configured Pi CLI.

```powershell
py -3.12 -m pip install -e .
py -3.12 -m unittest discover -s tests
powershell -ExecutionPolicy Bypass -File scripts\build_addon_xpi.ps1 -Version 0.4.1-beta -BuildBridge
```

Outputs:

```text
dist\zotero-agent-bridge-addon-0.4.1-beta.xpi
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
