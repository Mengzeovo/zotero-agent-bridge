# Zotero Pi Assistant Two-Stage Retirement Policy

Status: adopted before implementation

Policy source: [`config/pi-only-transition.json`](../config/pi-only-transition.json)

Capability baseline: [`PI_PLUGIN_CAPABILITY_BASELINE.md`](PI_PLUGIN_CAPABILITY_BASELINE.md)

## Purpose

The repository is being narrowed from a general Zotero Agent Bridge into the Zotero Pi Assistant product. The cleanup must stop supporting MCP, arbitrary HTTP clients, Obsidian, general Zotero automation, classification tools, external launchers, and shared/source Bridge processes without breaking the Pi literature assistant installed in Zotero.

The removal is intentionally split across two releases. Code must not be physically deleted before the retained Pi contract and upgrade behavior are covered by executable tests.

## Release 1: `0.4.0-beta` transition

`0.4.0-beta` changes the public product name to **Zotero Pi Assistant** and establishes lifecycle protocol v2 with product scope `zotero-pi-only`.

### Retained behavior

- The add-on ID, update chain, Bridge home, generated Token, Pi session directory, session index, and document identity algorithm remain unchanged.
- All routes required by the current Pi panel remain request/response compatible.
- The bundled Bridge remains responsible for reading Zotero/PDF context, running Pi, persisting sessions, streaming events, and validating assistant-note saves.
- Bundle verification, invalid-install quarantine, owner-authenticated shutdown, and one-time upgrade rollback remain available.

### Retired HTTP behavior

The retired HTTP routes listed in `config/pi-only-transition.json` remain registered for one transition release, but they:

1. still require the normal Bridge Token;
2. perform no Zotero, filesystem, mirror, or Obsidian side effects;
3. return HTTP `410 Gone`;
4. return error code `feature_retired`;
5. identify the Pi-only product scope and final removal release.

Unknown routes continue to return `404`.

### Retired queue command behavior

Only the dedicated assistant-note write path remains supported. A retired generic queue command must receive a terminal error response and be archived as failed. It must not be retried forever, silently discarded, or partially executed.

### Retired CLI and script behavior

MCP and legacy operator scripts may remain as small transition stubs in `0.4.0-beta`. A stub must print that the feature is unsupported by Zotero Pi Assistant and exit non-zero without starting a server or mutating Zotero.

No transition stub is included in user-facing installation documentation.

### User data behavior

The transition does not delete:

- Pi `.jsonl` sessions;
- `pi-chat/session-index.json`;
- generated Bridge configuration or Tokens;
- Obsidian vault files or indexes;
- mirror metadata or exported Markdown notes;
- old installed bundle directories.

Obsolete user data may be documented for manual archival/removal but is never deleted as an incidental upgrade action.

## Release 2: `0.4.1-beta` final removal

After `0.4.0-beta` passes automated and real-Zotero upgrade acceptance:

- 410 transition routes are unregistered and return 404;
- MCP, Obsidian, mirror, DOI import, classification, and collection-tree implementations are physically deleted;
- retired console entry points and scripts are deleted;
- retired add-on queue handlers and the unused legacy add-on script are deleted;
- configuration models and examples no longer expose removed settings;
- rollback candidates below the Pi-only lifecycle protocol floor are rejected.

Release 2 must rerun the same capability baseline used by Release 1. Deleting obsolete tests is not evidence that retained behavior still works.

## Upgrade and rollback gate

The first `0.4.0-beta` launch uses the following gate:

1. Preserve the installed `0.3.5` bundle and last-known-good metadata.
2. Install and verify the v2 bundled Bridge in a new version directory.
3. Start the v2 Bridge and require the expected add-on owner, bridge version, protocol version, distribution, and product scope.
4. Open an existing Pi document/session and verify that the registry is readable.
5. Mark the Pi-only protocol floor as established only after the v2 Bridge reaches healthy ready state.
6. Before that success marker, permit a single emergency fallback to the bundled `0.3.5` baseline if v2 startup fails.
7. After the success marker, do not select or start a pre-v2 broad Bridge as shared or last-known-good runtime.

The emergency fallback protects availability during first upgrade; it is not renewed support for the retired API surface.

## Implementation rules

- Tests for retained and retired contracts are added before route or module deletion.
- The add-on and Bridge are shipped atomically in the same XPI.
- Production accepts only the XPI-bundled managed Bridge. Source Bridge execution may remain an internal development activity but is not accepted by the production add-on.
- Loopback binding, Bridge Token authentication, and owner-authenticated shutdown remain mandatory.
- FastAPI OpenAPI, Swagger, and ReDoc endpoints are disabled in the Pi-only product.
- Saved-note validation remains server-authoritative; moving note creation directly to unvalidated UI code is not an acceptable simplification.
- Every destructive cleanup commit must have a smaller preceding refactor commit that leaves the capability baseline green.

## Completion gates

### Transition release gate

`0.4.0-beta` is ready only when:

- all frozen Pi capabilities pass automated tests;
- retired routes return authenticated, side-effect-free 410 responses;
- retired queue commands terminate safely;
- an existing profile upgrades without losing current or historical Pi sessions;
- formula copying and mathematical Zotero Note saving still work;
- the v2 bundle can recover from an invalid same-version installation;
- the release XPI, hash, SBOM, and update manifest are generated from the transition tree.

### Final removal gate

`0.4.1-beta` is ready only when:

- the transition release has passed real usage acceptance;
- no removed module, script, route, Obsidian resource, MCP entry point, or old launcher is present in the release archive;
- all frozen Pi capabilities pass again;
- pre-v2 runtime rollback is rejected without affecting Pi sessions or Tokens.
