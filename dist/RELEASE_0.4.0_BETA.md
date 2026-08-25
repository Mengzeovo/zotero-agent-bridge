# Zotero Pi Assistant 0.4.0-beta

## Artifact

- `zotero-agent-bridge-addon-0.4.0-beta.xpi`
- SHA-512: `8652cf8de62cb80daf07f23103fd7177b5d4010ad525532c53d847c8dd7dde1831e71897858ec005d5188ff07ffdec1c7914f7eef4a334b34da912d74a4905ee`
- Platform: Windows x64 bundled Bridge
- Add-on ID: `zotero-agent-bridge@local`
- Lifecycle protocol: `2`
- Product scope: `zotero-pi-only`

## Product scope

This release contains the Zotero Item Pane Pi literature assistant, per-paper resumable sessions, Markdown/KaTeX rendering, original-LaTeX copy, and confirmed save-to-Zotero-Note support.

Former CRUD, sync, Obsidian, MCP, and general automation surfaces are retired. HTTP and CLI compatibility shells return `feature_retired` without side effects during the 0.4.0-beta transition.

## Upgrade safety

The add-on preserves Bridge home, API token, Pi session files, `pi-chat/session-index.json`, document identity, and add-on ID. A verified bundled 0.3.5 Bridge can be used only once as emergency fallback before the first successful protocol-v2 startup.

## Supply chain

- `zotero-pi-assistant-0.4.0-beta-SBOM.cdx.json`
- `THIRD_PARTY_NOTICES-0.4.0-beta.md`
- `SHA512SUMS-0.4.0-beta.txt`

The Bridge executable is currently unsigned.
