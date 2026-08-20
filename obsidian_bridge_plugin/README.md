# Zotero Agent Bridge Obsidian Plugin

This plugin is the product-facing host for Zotero Agent Bridge inside Obsidian Desktop.

It does not reimplement the Python bridge. Instead, it manages the bridge as a local child process and talks to it through the HTTP API.

## Responsibilities

- Write the bridge config for the current Obsidian vault.
- Start, stop, and restart the local bridge process.
- Poll `/health` and `/capabilities`.
- Store bridge settings in Obsidian plugin data.
- Keep Zotero-specific writes delegated to the Zotero companion add-on.

## Directory Boundary

- `obsidian_bridge_plugin/`: Obsidian plugin and lifecycle manager.
- `zotero_companion_addon/`: Zotero companion add-on that runs inside Zotero.
- `zotero_agent_bridge/`: Python bridge core service.

## Development Install

Copy these files into an Obsidian vault plugin directory:

```text
<vault>/.obsidian/plugins/zotero-agent-bridge/
  manifest.json
  main.js
  styles.css
```

Then enable `Zotero Agent Bridge` from Obsidian community plugin settings.

For development, set either:

- `Bridge executable path` to a packaged bridge executable, or
- `Python executable path` to a Python 3.12 environment where `zotero-agent-bridge` is installed.

The plugin writes its generated runtime config under:

```text
<vault>/.obsidian/plugins/zotero-agent-bridge/runtime/bridge-config.json
```
