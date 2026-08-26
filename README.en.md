# Zotero Pi Assistant

[简体中文](README.md) | **English**

**Current version: 0.4.2** · **Zotero 7–9 supported (Zotero 9 recommended)** · **Current release platform: Windows x64**

Zotero Pi Assistant is a local literature-reading assistant embedded in Zotero. It turns the selected paper's PDF, bibliographic metadata, Zotero notes, and annotations into structured context, sends that context to Pi CLI for question answering, and stores conversations and organized knowledge locally.

Its purpose is not to turn Zotero into a general automation platform. It is designed to shorten the workflow from **reading a paper → asking questions → continuing the discussion → preserving useful knowledge**.

> This project only provides the built-in Zotero Pi literature assistant. The generic Agent Bridge, public CRUD API, MCP tools, Obsidian synchronization, and automatic paper classification were removed starting with `0.4.1-beta`.

## What the project does

| Capability | Description |
| --- | --- |
| Literature context | Reads the selected Zotero item's local PDF, metadata, child notes, PDF annotations, and page information. Stored and linked PDFs are supported when Zotero can resolve their paths. |
| Embedded Zotero chat | Provides Pi chat directly in the Item Pane and PDF Reader sidebar, reducing context switching between Zotero and a separate terminal. |
| Streaming conversations | Supports streaming responses, aborting generation, starting a new session, model selection, and thinking-level selection. |
| Image questions | Supports image-only and text-plus-image prompts using PNG, JPEG, WebP, or GIF files. |
| Session recovery | Maintains a separate Pi session for each paper. The current conversation can be restored after Zotero or Bridge restarts, while archived and orphan sessions can also be discovered and resumed. |
| Content rendering | Renders Markdown, code blocks, and KaTeX formulas. Copying rendered formulas restores their original LaTeX source. |
| Save Q&A | After explicit confirmation, saves the completed question and answer as a Zotero child Note and generates a short title. |
| Experience Note | Incrementally converts new conversations into a local knowledge ledger, then rebuilds the unique `Pi 经验笔记` from knowledge units, relations, corrections, and provenance. |
| Managed Bridge | The XPI bundles a Windows x64 Bridge. The add-on verifies, installs, starts, health-checks, rolls back, and stops it, so normal users do not need Python or a source checkout. |

## Intended use cases

- Ask questions about the concepts, methods, experiments, conclusions, and limitations of the selected paper.
- Discuss a paper using its full text together with Zotero annotations and existing notes.
- Resume a paper-specific conversation across multiple reading sessions.
- Save useful answers as Zotero Notes without losing formulas or manually copying content.
- Organize learning outcomes from multiple conversations into a traceable, rebuildable Experience Note.

The project is **not intended** for:

- OCR of scanned or image-only PDFs.
- General Zotero database CRUD, batch automation, or remote control.
- MCP Server functionality, Obsidian synchronization, paper classification, or unrestricted agent tool execution.
- Cloud knowledge bases, real-time multi-device synchronization, or team collaboration.

## How it works

```text
Zotero Add-on
    │  Selects the item, collects PDF/metadata/notes/annotations, and provides the UI
    ▼
Local Bridge (127.0.0.1 + Token)
    │  Builds reading context and manages Pi processes, sessions, history, and the ledger
    ▼
Pi CLI
    │  Uses the model and credentials configured by the user
    ▼
Model Provider
```

Component responsibilities:

- **Zotero Add-on**: provides the UI, manages the Bridge lifecycle, and performs constrained Zotero Note writes.
- **Local Bridge**: listens only on loopback and manages reading context, Pi RPC, session persistence, and Experience Note generation.
- **Pi CLI**: performs the actual model calls. This project does not install Pi or provide model accounts or API credentials.

## Installation

### Requirements

- Windows x64.
- Zotero 7–9, with Zotero 9 recommended.
- Pi CLI installed and configured with at least one available model and its credentials.
- A Zotero item containing a locally accessible PDF attachment.

### Steps

1. Download `zotero-agent-bridge-addon-0.4.2.xpi` from [Releases](https://github.com/Mengzeovo/zotero-agent-bridge/releases/tag/v0.4.2).
2. In Zotero, open **Tools → Plugins → Install Plugin From File…**.
3. Select the XPI and restart Zotero.
4. Select a paper with a local PDF, then open **Pi Literature Assistant** in the Item Pane or PDF Reader sidebar.

The add-on verifies and installs the bundled Bridge under:

```text
%LOCALAPPDATA%\ZoteroAgentBridge\bridge\0.4.2
```

Upgrades preserve the add-on ID, Bridge token, Pi session paths, and document identity rules.

## Basic usage

1. Select a Zotero paper with an accessible PDF.
2. Open **Pi Literature Assistant**.
3. Select a model and thinking level.
4. Enter a question, optionally attaching images.
5. Wait for the response, or abort generation when necessary.
6. Use **Session History** to restore an earlier conversation.
7. Use **Save Q&A** to write the completed exchange to a Zotero Note.
8. Use **Update Experience Note** to organize newly learned information for the paper.

To prevent an answer from being written to the wrong paper, note saving is allowed only when the active item, attachment, context fingerprint, Pi document ID, and completed response all match.

## Local data

Managed data is stored under:

```text
%USERPROFILE%\Zotero\zotero-agent-bridge
├─ bridge.generated.json
├─ pi-chat\session-index.json
├─ pi-chat\experience-note-index.json
├─ pi-chat\experience-knowledge\*.json
└─ pi-sessions\*.jsonl
```

Experience Notes use three data layers:

1. **Pi JSONL**: the original conversations and traceable source material.
2. **Knowledge ledger**: exchange-level evidence, knowledge units, relations, corrections, and source status.
3. **Zotero `Pi 经验笔记`**: a reading view deterministically rebuilt from the ledger.

If a source session becomes missing or corrupt, previously extracted knowledge is retained with an explicit warning rather than silently deleted. A forced rebuild intentionally recreates the ledger using only currently readable sources.

## Security and privacy boundary

- The Bridge binds only to `127.0.0.1`, and every retained route requires the add-on-managed API token.
- Pi is started with restrictive options including `--no-tools --no-skills --no-extensions --no-approve`.
- PDF text, metadata, notes, and annotations are marked as untrusted source material and must not be treated as system instructions.
- Zotero writes are limited to creating Q&A Notes and updating the marker-protected Experience Note, both initiated after user confirmation.
- Generic CRUD, MCP, Obsidian, and arbitrary script execution have been removed. Former HTTP routes only return `410 feature_retired`.
- The project does not provide cloud synchronization, but Pi sends generation requests to the configured model provider. Data retention, training, and privacy policies therefore depend on that provider and the user's Pi configuration.

## Current limitations

1. **Platform**: the bundled Bridge is currently released for Windows x64 only.
2. **External dependencies**: Pi CLI, a model, and model credentials must be installed and configured separately. Model availability and response quality are outside this project's control.
3. **PDF extraction**: text extraction is used instead of OCR. Scanned, image-only, encrypted, or structurally unusual PDFs may not be read completely.
4. **Context limit**: the complete PDF, metadata, notes, and annotations must remain below the default `500,000`-character context limit. Oversized context produces an explicit error rather than silent truncation.
5. **Concurrency**: one Bridge instance maintains only one active response at a time.
6. **Local persistence**: Pi sessions and knowledge ledgers are stored locally. Cloud backup, cross-machine synchronization, and conflict merging are not included.
7. **Image limits**: each prompt may include up to four images, with a 10 MiB per-image limit and a 20 MiB combined limit.
8. **Product scope**: public OpenAPI, general Zotero automation APIs, MCP, Obsidian synchronization, and paper classification are not provided.
9. **Code signing**: the Bridge executable is not yet Authenticode-signed, so Windows may display source or security warnings.

Backing up Zotero data and `%USERPROFILE%\Zotero\zotero-agent-bridge` before upgrading is still recommended.

## Build and test

Only developers building from source need Python 3.12+, PowerShell, Node.js, and an available Pi CLI:

```powershell
py -3.12 -m pip install -e .
py -3.12 -m unittest discover -s tests
powershell -ExecutionPolicy Bypass -File scripts\build_addon_xpi.ps1 -Version 0.4.2 -BuildBridge
```

Outputs:

```text
dist\zotero-agent-bridge-addon-0.4.2.xpi
dist\zotero-agent-bridge-addon.xpi
```

## Further documentation

- [Pi assistant design and API](docs/PI_LITERATURE_ASSISTANT.md)
- [Add-on capability baseline](docs/PI_PLUGIN_CAPABILITY_BASELINE.md)
- [Pi-only retirement policy](docs/PI_ONLY_RETIREMENT_POLICY.md)
- [Bridge bundle protocol](docs/BRIDGE_BUNDLE_PROTOCOL.md)

## License

[MIT](LICENSE)
