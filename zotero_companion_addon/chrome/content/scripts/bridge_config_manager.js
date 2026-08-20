"use strict";

var ZoteroAgentBridgeConfigManager = (() => {
  const MANAGED_SCHEMA_VERSION = 1;
  const MIGRATION_SCHEMA_VERSION = 1;
  const MANAGED_CONFIG_FILE = "bridge-config.managed.json";
  const MIGRATION_STATE_FILE = "migration-state.json";
  const LEGACY_LAUNCHER_FILE = "bridge-launcher.json";

  class ConfigError extends Error {
    constructor(code, message, details = null) {
      super(message);
      this.name = "ConfigError";
      this.code = code;
      this.details = details;
    }
  }

  function loopbackHost(value) {
    const host = String(value || "127.0.0.1").trim().toLowerCase().replace(/^\[|\]$/g, "").replace(/\.$/, "");
    if (host === "localhost" || host === "127.0.0.1" || host === "::1") {
      return host;
    }
    return "127.0.0.1";
  }

  function positivePort(value, fallback = 8765) {
    const port = Number(value);
    return Number.isInteger(port) && port > 0 && port <= 65535 ? port : fallback;
  }

  function legacyConfigPath(descriptor, PathUtils) {
    if (!descriptor || descriptor.schema_version !== 1 || descriptor.platform !== "windows" || !Array.isArray(descriptor.arguments)) {
      return null;
    }
    const index = descriptor.arguments.findIndex((value) => String(value).toLowerCase() === "-configpath");
    if (index < 0 || index + 1 >= descriptor.arguments.length) {
      return null;
    }
    const candidate = String(descriptor.arguments[index + 1] || "").trim();
    return candidate && PathUtils.isAbsolute(candidate) ? PathUtils.normalize(candidate) : null;
  }

  function legacyWorkdir(descriptor, PathUtils) {
    const candidate = String(descriptor?.workdir || "").trim();
    return candidate && PathUtils.isAbsolute(candidate) ? PathUtils.normalize(candidate) : null;
  }

  function resolveOptionalPath(value, baseDir, PathUtils) {
    const text = String(value || "").trim();
    if (!text) {
      return null;
    }
    const platformText = /^[A-Za-z]:[\\/]/.test(text) || /^[\\/]{2}/.test(text)
      ? text.replace(/\//g, "\\")
      : text;
    if (PathUtils.isAbsolute(platformText)) {
      return PathUtils.normalize(platformText);
    }
    let resolved = baseDir;
    for (const segment of text.split(/[\\/]+/)) {
      if (!segment || segment === ".") {
        continue;
      }
      resolved = segment === ".." ? PathUtils.parent(resolved) : PathUtils.join(resolved, segment);
    }
    return PathUtils.normalize(resolved);
  }

  function migrateConfig(legacy, context) {
    const { bridgeHome, zoteroDataDir, legacyBaseDir, PathUtils, defaults = {} } = context;
    const config = {
      managed_config_schema_version: MANAGED_SCHEMA_VERSION,
      host: loopbackHost(legacy?.host || defaults.bridgeHost),
      port: positivePort(legacy?.port || defaults.bridgePort),
      zotero_data_dir: zoteroDataDir,
      zotero_local_api_base: String(legacy?.zotero_local_api_base || defaults.zoteroLocalApiBase || "http://127.0.0.1:23119/api/users/0"),
      bridge_home: bridgeHome,
      metadata_dir: resolveOptionalPath(legacy?.metadata_dir, legacyBaseDir, PathUtils)
        || PathUtils.join(bridgeHome, "mirror", "metadata"),
      notes_dir: resolveOptionalPath(legacy?.notes_dir, legacyBaseDir, PathUtils)
        || PathUtils.join(bridgeHome, "mirror", "notes"),
      addon_timeout_seconds: Number(legacy?.addon_timeout_seconds) > 0 ? Number(legacy.addon_timeout_seconds) : 30,
      addon_status_ttl_seconds: Number(legacy?.addon_status_ttl_seconds) > 0 ? Number(legacy.addon_status_ttl_seconds) : 15,
      lifecycle_addon_exit_grace_seconds: Number(legacy?.lifecycle_addon_exit_grace_seconds) > 0
        ? Number(legacy.lifecycle_addon_exit_grace_seconds)
        : 30,
      lifecycle_watchdog_interval_seconds: Number(legacy?.lifecycle_watchdog_interval_seconds) > 0
        ? Number(legacy.lifecycle_watchdog_interval_seconds)
        : 1,
      user_agent: String(legacy?.user_agent || "ZoteroAgentBridge/0.3.3"),
    };
    const baseAttachment = resolveOptionalPath(legacy?.base_attachment_path, legacyBaseDir, PathUtils);
    if (baseAttachment) {
      config.base_attachment_path = baseAttachment;
    }
    const explicitToken = String(legacy?.api_token || defaults.apiToken || "").trim();
    if (explicitToken) {
      config.api_token = explicitToken;
    }

    const legacyPi = legacy?.pi && typeof legacy.pi === "object" ? legacy.pi : {};
    config.pi = {
      executable: String(legacyPi.executable || "pi"),
      session_dir: resolveOptionalPath(legacyPi.session_dir, legacyBaseDir, PathUtils)
        || PathUtils.join(bridgeHome, "pi-sessions"),
      cwd_mode: "selected_pdf_directory",
      model: String(legacyPi.model || ""),
      thinking_level: ["off", "minimal", "low", "medium", "high", "xhigh", "max"].includes(legacyPi.thinking_level)
        ? legacyPi.thinking_level
        : "medium",
      idle_timeout_seconds: Number(legacyPi.idle_timeout_seconds) > 0 ? Number(legacyPi.idle_timeout_seconds) : 1800,
      max_context_chars: Number(legacyPi.max_context_chars) > 0 ? Number(legacyPi.max_context_chars) : 500000,
      poll_interval_ms: Number(legacyPi.poll_interval_ms) >= 100 ? Number(legacyPi.poll_interval_ms) : 300,
    };
    const customPrompt = resolveOptionalPath(legacyPi.system_prompt_path, legacyBaseDir, PathUtils);
    if (customPrompt && !/[\\/]config[\\/]literature-assistant\.md$/i.test(customPrompt)) {
      config.pi.system_prompt_path = customPrompt;
    }

    if (legacy?.obsidian && typeof legacy.obsidian === "object") {
      const obsidian = {};
      for (const key of ["vault_name", "default_note_dir", "bridge_open_base_url"]) {
        if (legacy.obsidian[key]) {
          obsidian[key] = String(legacy.obsidian[key]);
        }
      }
      for (const key of ["vault_path", "index_path"]) {
        const path = resolveOptionalPath(legacy.obsidian[key], legacyBaseDir, PathUtils);
        if (path) {
          obsidian[key] = path;
        }
      }
      config.obsidian = obsidian;
    }
    return config;
  }

  function create(options) {
    const { bridgeHome, zoteroDataDir, addonConfig = {}, IOUtils, PathUtils, Services, appendLog } = options;
    const managedConfigPath = PathUtils.join(bridgeHome, MANAGED_CONFIG_FILE);
    const migrationStatePath = PathUtils.join(bridgeHome, MIGRATION_STATE_FILE);
    const legacyLauncherPath = PathUtils.join(bridgeHome, LEGACY_LAUNCHER_FILE);

    async function writeAtomic(path, payload) {
      const temporary = `${path}.tmp-${Services.uuid.generateUUID().toString().replace(/[{}-]/g, "")}`;
      await IOUtils.writeUTF8(temporary, JSON.stringify(payload, null, 2));
      await IOUtils.move(temporary, path, { noOverwrite: false });
    }

    async function readJson(path) {
      return JSON.parse(await IOUtils.readUTF8(path));
    }

    async function ensureManagedConfig() {
      await IOUtils.makeDirectory(bridgeHome, { ignoreExisting: true });
      if (await IOUtils.exists(managedConfigPath)) {
        const existing = await readJson(managedConfigPath);
        if (existing.managed_config_schema_version !== MANAGED_SCHEMA_VERSION) {
          throw new ConfigError("managed_config_schema_unsupported", "Managed Bridge configuration schema is unsupported");
        }
        return { configPath: managedConfigPath, config: existing, migrated: false, source: "managed" };
      }

      let legacy = {};
      let legacyPath = null;
      let legacyBaseDir = bridgeHome;
      if (await IOUtils.exists(legacyLauncherPath)) {
        try {
          const descriptor = await readJson(legacyLauncherPath);
          legacyPath = legacyConfigPath(descriptor, PathUtils);
          legacyBaseDir = legacyWorkdir(descriptor, PathUtils)
            || (legacyPath ? PathUtils.parent(legacyPath) : bridgeHome);
          if (legacyPath && await IOUtils.exists(legacyPath)) {
            legacy = await readJson(legacyPath);
          }
        } catch (error) {
          await appendLog("warning", "legacy_bridge_config_read_failed", {
            message: error?.message || String(error),
          });
          legacy = {};
          legacyPath = null;
          legacyBaseDir = bridgeHome;
        }
      }
      const config = migrateConfig(legacy, {
        bridgeHome,
        zoteroDataDir,
        legacyBaseDir,
        PathUtils,
        defaults: addonConfig,
      });
      await writeAtomic(managedConfigPath, config);
      await writeAtomic(migrationStatePath, {
        migration_schema_version: MIGRATION_SCHEMA_VERSION,
        migrated_at: new Date().toISOString(),
        source: legacyPath ? "legacy-launcher" : "defaults",
        legacy_config_path: legacyPath,
        managed_config_path: managedConfigPath,
      });
      await appendLog("info", "bridge_config_migrated", {
        source: legacyPath ? "legacy-launcher" : "defaults",
        legacy_config_path: legacyPath,
        managed_config_path: managedConfigPath,
      });
      return { configPath: managedConfigPath, config, migrated: true, source: legacyPath ? "legacy-launcher" : "defaults" };
    }

    return { ensureManagedConfig, managedConfigPath };
  }

  return {
    create,
    ConfigError,
    __test: {
      legacyConfigPath,
      legacyWorkdir,
      loopbackHost,
      migrateConfig,
      positivePort,
      resolveOptionalPath,
    },
  };
})();

if (typeof module !== "undefined" && module.exports) {
  module.exports = ZoteroAgentBridgeConfigManager;
}
