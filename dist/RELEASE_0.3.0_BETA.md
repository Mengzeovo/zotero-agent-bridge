# Zotero Agent Bridge 0.3.0 Beta

## Status

Windows x64 Beta. The bundled Bridge executable is self-contained but not Authenticode-signed. Do not describe this build as a stable signed release.

## Highlights

- One XPI contains the Zotero 9 add-on and a PyInstaller `onedir` Windows x64 Bridge.
- Normal installation requires no Python, pip, repository checkout, or launcher registration.
- Secure versioned installation uses a cross-window lock, staging directory, size and SHA-256 validation, install sentinel, and atomic rename.
- Compatible 0.2.2 configuration and API Token values are migrated through an allowlist; legacy launcher commands are never executed.
- The add-on starts the bundled EXE directly and verifies Bundle version, protocol version, distribution, and ownership through `/lifecycle`.
- Existing compatible Bridges remain shared and survive Zotero shutdown.
- Failed upgrades are recorded and can fall back to a verified last-known-good Bundle.
- Pi remains external, starts lazily, and runs with `--no-tools`; Zotero Note writes require explicit confirmation.
- The XPI includes a CycloneDX SBOM and third-party notices.

## Install

1. Install Pi CLI and confirm that `pi` runs from a terminal.
2. In Zotero 9, choose **Tools → Plugins → Install Plugin From File…**.
3. Select `zotero-agent-bridge-addon-0.3.0.xpi`.
4. Restart Zotero if requested and open **Pi Literature Assistant** for an item with a local PDF.

## Upgrade from 0.2.2

Install the 0.3.0 XPI over the existing add-on. On startup, the add-on detects compatible legacy launcher/config files under the Bridge home, migrates approved settings and token values into `bridge-config.managed.json`, installs the bundled Bridge, and no longer invokes the old launcher command.

Keep the old files until the Beta has been validated in your environment. The migration is non-destructive.

## Rollback

To return to 0.2.2, install the previous 0.2.2 XPI. The 0.3.0 versioned Bridge installation and managed configuration are retained rather than recursively deleted. If a newly installed Bundle fails runtime validation, 0.3.0 records the failure and attempts the verified last-known-good Bundle automatically.

## Known limitations

- Windows x64 only for the bundled Bridge.
- No Authenticode signature; Windows SmartScreen or antivirus products may warn or quarantine the EXE.
- Pi CLI is not bundled or installed automatically.
- OCR, multiple concurrent document answers, and automatic Zotero writes remain out of scope.

## Validation summary

The release gate covers deterministic XPI contents, Bundle schema and hashes, SBOM/notices, sensitive-data scanning, Python and JavaScript checks, Windows Defender scanning, isolated Zotero 9 startup, secure extraction, owned/shared lifecycle behavior, real PDF context, Pi RPC question/answer polling, confirmed Zotero Note save, tamper rejection, failed-upgrade rollback, and clean shutdown.
