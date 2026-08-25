# Zotero Pi Assistant 0.4.1-beta

## Artifact

- `zotero-agent-bridge-addon-0.4.1-beta.xpi`
- SHA-512: `e4f48c5c7918e0a9a478cdc2279053b44b4fc180579d340e0ef37a5578d588a06cd76a639bba1051f003edaded51705bfa17de01d778c8889ab2ac5cdf2db3ae`
- Platform: Windows x64 bundled Bridge
- Add-on ID: `zotero-agent-bridge@local`
- Lifecycle protocol: `2`
- Product scope: `zotero-pi-only`

## Final removal

This release completes the Pi-only retirement plan after the `0.4.0-beta` automated and real-Zotero acceptance gate:

- former CRUD, sync, Obsidian, MCP, classification, collection, and external-launcher implementations are physically absent;
- transition HTTP routes are unregistered and return ordinary `404 Not Found` responses;
- MCP and retired console/script entry points are absent;
- OpenAPI, Swagger, and ReDoc endpoints are disabled;
- production accepts only the current XPI-bundled, add-on-owned protocol-v2 Bridge;
- protocol-v1 rollback support is physically removed, while verified Pi-only v2 rollback remains available.

## Preserved behavior and data

The Zotero Item Pane Pi literature assistant, per-paper resumable sessions, orphan recovery, Markdown/KaTeX rendering, original-LaTeX copy, and confirmed Zotero Note saving remain covered by the frozen capability suite.

The add-on ID, Bridge home, API Token, Pi session directory, `pi-chat/session-index.json`, and document identity algorithm remain unchanged. Legacy user data is not deleted.

## Validation

- 127 automated tests passed.
- Python compile and Git diff checks passed.
- Release path/token scan passed.
- XPI archive contains no retired module, script, launcher, MCP, or Obsidian resource.
- Bundled EXE smoke verified protocol 2, `zotero-pi-only`, `xpi-bundled`, retired/docs routes returning 404, and owner-authenticated shutdown.
- Independent review verdict: OK.

## Supply chain

- `zotero-pi-assistant-0.4.1-beta-SBOM.cdx.json`
- `THIRD_PARTY_NOTICES-0.4.1-beta.md`
- `SHA512SUMS-0.4.1-beta.txt`

The Bridge executable is currently unsigned.
