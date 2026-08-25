# Zotero Pi Plugin Capability Baseline

Status: frozen for the Pi-only cleanup

Baseline source version: `0.3.5`

This document defines the user-visible and compatibility-critical behavior that must remain functional while the repository is narrowed from a general Agent Bridge to the Zotero Pi Assistant product. MCP, generic Zotero automation, Obsidian integration, local mirror export, classification tools, and external launchers are deliberately excluded from this baseline.

## 1. Installation and managed Bridge lifecycle

The Zotero add-on must continue to:

- keep the add-on ID `zotero-agent-bridge@local` and the existing update chain;
- install an XPI-bundled Windows x64 Bridge without requiring Python or pip on the user machine;
- verify the bundled Bridge manifest, file set, sizes, and hashes before launch;
- install versioned Bridge files below `%LOCALAPPDATA%\ZoteroAgentBridge\bridge\<version>`;
- preserve the existing Bridge home, generated API Token, owner credentials, logs, and Pi session paths during upgrades;
- quarantine an invalid same-version installed bundle and reinstall the verified bundle;
- start the managed Bridge when Zotero starts and Pi only when a literature session is opened;
- distinguish Bridge readiness and ownership before sending assistant requests;
- perform owner-authenticated shutdown and stale-add-on watchdog cleanup;
- retain a working last-known-good bundle until the replacement Bridge has passed startup and compatibility checks.

## 2. Zotero document and reading context

For the selected Zotero parent item, the assistant must continue to:

- select a requested local PDF attachment or choose an appropriate local PDF automatically;
- support stored and linked PDF attachments when Zotero can resolve their path;
- preserve `attachments:` path fallback through the configured base attachment directory;
- read the parent item metadata, collection names, child notes, attachment annotations, and annotation warnings;
- extract paginated PDF text through `pdftotext` when available and `pypdf` otherwise;
- mark Zotero/PDF material as untrusted source content before injecting it into Pi;
- compute a stable context fingerprint from the PDF and Zotero context;
- reinject context after the fingerprint changes;
- run Pi with the selected PDF directory as its working directory.

## 3. Pi chat behavior

The Zotero Item Pane must continue to support:

- opening a document-scoped Pi session;
- sending text messages and receiving cursor-polled streaming events;
- restoring the authoritative transcript after Bridge or Zotero restart;
- aborting an active generation without discarding the persisted session;
- resetting to a new session while archiving the previous session;
- displaying errors without silently losing prepared context;
- changing the selected Pi model;
- changing the thinking level between `off`, `minimal`, `low`, `medium`, `high`, `xhigh`, and `max`;
- keeping model and thinking selectors on the same row;
- preserving pending item-selection changes until streaming or note-save operations finish.

## 4. Image input

The message flow must continue to support image-only and text-plus-image prompts with:

- MIME types `image/png`, `image/jpeg`, `image/webp`, and `image/gif`;
- at most 4 images per message;
- at most 10 MiB per image;
- at most 20 MiB total decoded image data per message;
- clipboard image extraction and safe base64 validation;
- the same document/session scope guards used for text messages.

## 5. Session persistence and history

The cleanup must preserve:

- existing Pi `.jsonl` session files;
- `pi-chat/session-index.json` and its document registry semantics;
- the current document identity algorithm and session naming convention;
- one current session per document;
- up to 20 archived sessions per document;
- reset-as-archive behavior rather than destructive deletion;
- history entries containing timestamp, model, and first-question preview;
- restoration of an archived session through the original Pi session file;
- continued conversation after resuming an archived session;
- discovery of older orphan session files whose `session_info.name` matches the Zotero item and document ID prefix;
- fresh context injection on the first question after a historical session is resumed.

Changing the add-on ID, Bridge home, Pi session directory, session-index schema, or document identity inputs requires an explicit migration and is not permitted as incidental cleanup.

## 6. Markdown, formulas, and copying

The assistant panel must continue to:

- render Markdown without allowing source content to inject unsafe HTML;
- render inline and block mathematics;
- retain the original math source in `data-zab-math-source`;
- restore original LaTeX when a copied selection contains rendered formulas;
- preserve `$...$`, `$$...$$`, `\(...\)`, and `\[...\]` delimiters;
- use the normal Zotero/browser copy behavior when the selection contains no formula;
- preserve inline code and fenced code without treating literal math delimiters as formulas.

## 7. Saving a Pi answer as a Zotero Note

The add-on must continue to:

- require an explicit Zotero confirmation before writing a note;
- reject partial, stale, cross-document, cross-session, and still-streaming answers;
- save only an authoritative assistant message whose `stopReason` is `stop`;
- bind the request to item key, attachment key, context fingerprint, and Pi document ID;
- create a Zotero child Note and return its note key to the panel;
- include literature metadata, attachment, document ID, generation time, model, question, and answer;
- normalize `\(...\)` and `\[...\]` into Zotero-compatible math markup;
- support inline math, block math, `aligned` environments, and TeX containing `<`, `>`, and `&`;
- escape prose HTML while preserving TeX and code spans/blocks;
- use Better Notes Markdown conversion when available and the built-in safe HTML fallback otherwise.

## 8. Private add-on/Bridge contract

These route/method pairs are the minimum currently consumed by the Zotero add-on and must remain compatible throughout the cleanup transition:

### Lifecycle and readiness

- `GET /health`
- `GET /lifecycle`
- `POST /lifecycle/shutdown`

### Pi assistant

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

Every retained route must remain loopback-only and Token-authenticated. Shutdown must additionally remain owner-authenticated. Route paths may only change in an atomic XPI update that changes the add-on and Bridge together.

## 9. UI and resource baseline

The built XPI must continue to include and load:

- `bootstrap.js`;
- `bridge_config_manager.js`;
- `bridge_bundle_manager.js`;
- `markdown_renderer.js`;
- `pi_chat_panel.js`;
- Pi panel styles, icons, locale strings, and bundled Markdown renderer assets;
- the versioned Bridge bundle and its manifest/supply-chain metadata.

The panel must continue to:

- register and unregister its Zotero Item Pane section cleanly;
- clean up timers, events, windows, and pending asynchronous work;
- keep the history popup fully visible above its action row;
- preserve accessibility labels and localization resources;
- avoid rendering external content through unsafe `innerHTML` paths.

## 10. Automated regression suites that protect the baseline

The following suites are the current evidence for this baseline and must remain green or be replaced by narrower tests before their covered code is removed:

- `tests/test_assistant_http.py`
- `tests/test_pi_chat.py`
- `tests/test_reading_context.py`
- `tests/test_zotero_chat_ui.py`
- `tests/test_lifecycle.py`
- the Pi/add-on portions of `tests/test_bundle_packaging.py`
- configuration tests that preserve Token, Bridge home, and Pi session paths

A cleanup change is not complete merely because obsolete tests were deleted. Each retained capability above must still have executable automated coverage or a documented real-Zotero acceptance check.

## 11. Real Zotero acceptance baseline

Before publishing a cleanup build, validate in an upgraded existing profile rather than only a fresh profile:

1. Start Zotero and confirm the bundled Bridge installs and reaches ready state.
2. Open a paper with a local PDF and verify PDF, notes, and annotations are prepared.
3. Send text, image-only, and text-plus-image prompts.
4. Change model and thinking level.
5. Abort one response and send another question successfully.
6. Reset, open history, resume an older session, and continue the conversation.
7. Restart Zotero and confirm current/history sessions remain available.
8. Copy inline and block formulas and verify original LaTeX is placed on the clipboard.
9. Save an answer containing inline math, an `aligned` block, `<`, `>`, and `&` to a Zotero Note.
10. Corrupt an installed same-version bundle in an isolated test profile and verify quarantine/reinstallation.

## 12. Excluded product surfaces

The following current repository capabilities are not part of the frozen Pi plugin baseline and may be deprecated or removed according to the cleanup plan:

- MCP tools and resources;
- generic collection/item CRUD HTTP APIs;
- generic linked-PDF import and generic note endpoints;
- mirror export/search/fallback storage;
- Obsidian plugin, sync routes, and menu actions;
- paper classification and collection restructuring scripts;
- external Bridge panels, launchers, stack scripts, and shared/source Bridge support;
- public OpenAPI/Swagger documentation.
