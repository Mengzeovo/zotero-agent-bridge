/**
 * Zotero Agent Bridge companion add-on bootstrap.
 *
 * Compatible with Zotero 7/8/9 bootstrapped add-ons.
 */

function install(data, reason) {}

async function writeBootstrapLog(message, details) {
  try {
    const dataDir = Zotero?.DataDirectory?.dir;
    if (!dataDir) {
      return;
    }
    const logPath = PathUtils.join(dataDir, "zotero-agent-bridge-bootstrap.log");
    const entry = JSON.stringify(
      {
        ts: new Date().toISOString(),
        message,
        details: details || null,
      },
      null,
      2,
    );
    const existing = (await IOUtils.exists(logPath)) ? await IOUtils.readUTF8(logPath) : "";
    await IOUtils.writeUTF8(logPath, `${existing}${entry}\n`);
  } catch (error) {}
}

function buildZoteroAgentBridge(rootURI) {
  const ADDON_VERSION = "0.3.3";
  const DEFAULT_POLL_INTERVAL_MS = 1000;
  const DEFAULT_STATUS_INTERVAL_MS = 5000;
  const DEFAULT_BRIDGE_HOST = "127.0.0.1";
  const DEFAULT_BRIDGE_PORT = 8765;
  const DEFAULT_BRIDGE_STARTUP_TIMEOUT_MS = 15000;
  const DEFAULT_BRIDGE_REQUEST_TIMEOUT_MS = 5000;
  const ROOT_CONFIG_PATH = `${rootURI}config/default-config.json`;

  let state = null;

  class BridgeError extends Error {
    constructor(code, message, details = null) {
      super(message);
      this.name = "BridgeError";
      this.code = code;
      this.details = details;
    }
  }

  function createState(config, bridgeHome) {
    const startedAt = new Date().toISOString();
    return {
      addonVersion: ADDON_VERSION,
      startedAt,
      config,
      bridgeHome,
      commandsDir: PathUtils.join(bridgeHome, "commands"),
      responsesDir: PathUtils.join(bridgeHome, "responses"),
      archiveDir: PathUtils.join(bridgeHome, "archive"),
      logsDir: PathUtils.join(bridgeHome, "logs"),
      statusDir: PathUtils.join(bridgeHome, "status"),
      statusFile: PathUtils.join(bridgeHome, "status", "addon-status.json"),
      logFile: PathUtils.join(bridgeHome, "logs", "addon.log"),
      queueRunning: false,
      statusTimer: null,
      pollTimer: null,
      shuttingDown: false,
      menuItems: new Map(),
      chatPanel: null,
      bridgeState: "starting",
      bridgeOwnership: "none",
      bridgeOwnerId: null,
      bridgeOwnerToken: null,
      bridgeLastError: null,
      bridgeStartPromise: null,
      bridgeProcess: null,
      bridgeBundleState: "pending",
      bridgeBundleInfo: null,
      bridgeBundleManager: null,
      bridgeConfigManager: null,
      bridgeManagedConfig: null,
      quitObserver: null,
    };
  }

  async function loadConfig() {
    const defaults = {
      bridgeHome: "",
      bridgeHost: DEFAULT_BRIDGE_HOST,
      bridgePort: DEFAULT_BRIDGE_PORT,
      zoteroLocalApiBase: "http://127.0.0.1:23119/api/users/0",
      apiToken: "",
      autoStartBridge: true,
      stopOwnedBridgeOnShutdown: true,
      bridgeStartupTimeoutMs: DEFAULT_BRIDGE_STARTUP_TIMEOUT_MS,
      bridgeRequestTimeoutMs: DEFAULT_BRIDGE_REQUEST_TIMEOUT_MS,
      bridgeLauncherFile: "bridge-launcher.json",
      pollIntervalMs: DEFAULT_POLL_INTERVAL_MS,
      statusIntervalMs: DEFAULT_STATUS_INTERVAL_MS,
    };
    try {
      const content = Zotero.File.getContentsFromURL(ROOT_CONFIG_PATH);
      if (!content) {
        return defaults;
      }
      return Object.assign(defaults, JSON.parse(content));
    } catch (error) {
      return defaults;
    }
  }

  function getBridgeHome(config) {
    if (config.bridgeHome && String(config.bridgeHome).trim()) {
      return String(config.bridgeHome).trim();
    }
    return PathUtils.join(Zotero.DataDirectory.dir, "zotero-agent-bridge");
  }

  async function ensureDirectories() {
    const directories = [
      state.bridgeHome,
      state.commandsDir,
      state.responsesDir,
      state.archiveDir,
      state.logsDir,
      state.statusDir,
    ];
    for (const directory of directories) {
      await IOUtils.makeDirectory(directory, { ignoreExisting: true });
    }
  }

  async function appendLog(level, message, details = null) {
    const entry = {
      ts: new Date().toISOString(),
      level,
      message,
      details,
    };
    const line = `${JSON.stringify(entry)}\n`;
    try {
      const existing = (await IOUtils.exists(state.logFile))
        ? await IOUtils.readUTF8(state.logFile)
        : "";
      await IOUtils.writeUTF8(state.logFile, existing + line);
    } catch (error) {
      Zotero.debug(`ZoteroAgentBridge log write failed: ${error}`);
    }
  }

  async function readBridgeToken() {
    if (state.config.apiToken && String(state.config.apiToken).trim()) {
      return String(state.config.apiToken).trim();
    }
    const tokenPath = PathUtils.join(state.bridgeHome, "bridge.generated.json");
    if (!(await IOUtils.exists(tokenPath))) {
      throw new BridgeError("bridge_token_missing", `Bridge token file not found: ${tokenPath}`);
    }
    const payload = JSON.parse(await IOUtils.readUTF8(tokenPath));
    if (!payload.api_token) {
      throw new BridgeError("bridge_token_invalid", `Bridge token file is invalid: ${tokenPath}`);
    }
    return String(payload.api_token);
  }

  function bridgeBaseURL() {
    return `http://${state.config.bridgeHost || DEFAULT_BRIDGE_HOST}:${state.config.bridgePort || DEFAULT_BRIDGE_PORT}`;
  }

  function delay(milliseconds) {
    return new Promise((resolve) => setTimeout(resolve, milliseconds));
  }

  function newOwnerValue() {
    return Services.uuid.generateUUID().toString().replace(/[{}-]/g, "");
  }

  async function rawBridgeRequest(method, path, payload = null, options = {}) {
    const token = await readBridgeToken();
    const timeoutMs = Math.max(500, Number(options.timeoutMs || state.config.bridgeRequestTimeoutMs));
    let response;
    try {
      const headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Bridge-Token": token,
      };
      if (options.ownerToken) {
        headers["X-Bridge-Owner-Token"] = options.ownerToken;
      }
      response = await Zotero.HTTP.request(method, `${bridgeBaseURL()}${path}`, {
        headers,
        body: payload ? JSON.stringify(payload) : undefined,
        responseType: "text",
        successCodes: false,
        timeout: timeoutMs,
        errorDelayIntervals: [],
        errorDelayMax: 0,
      });
    } catch (error) {
      throw new BridgeError(
        "bridge_unreachable",
        `Bridge is not responding at ${bridgeBaseURL()}`,
        serializeError(error),
      );
    }
    const text = typeof response.responseText === "string" ? response.responseText : "";
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (error) {
        data = { raw: text };
      }
    }
    if (response.status < 200 || response.status >= 300) {
      const error = data && data.error ? data.error : {};
      throw new BridgeError(
        error.code || "bridge_http_error",
        error.message || `Bridge HTTP request failed with status ${response.status}`,
        error.details || data,
      );
    }
    return data;
  }

  async function checkBridgeHealth() {
    let lifecycleError = null;
    try {
      const lifecycle = await rawBridgeRequest("GET", "/lifecycle", null, { timeoutMs: 2000 });
      return { lifecycle };
    } catch (error) {
      lifecycleError = serializeError(error);
      try {
        return await rawBridgeRequest("GET", "/health", null, { timeoutMs: 3000 });
      } catch (fallbackError) {
        state.bridgeLastError = {
          code: "bridge_health_check_failed",
          message: "Bridge lifecycle and health checks both failed",
          details: {
            lifecycle: lifecycleError,
            health: serializeError(fallbackError),
          },
        };
        return null;
      }
    }
  }

  function classifyLifecycle(lifecycle, { bundled = false } = {}) {
    if (!lifecycle || typeof lifecycle !== "object") {
      throw new BridgeError("bridge_protocol_invalid", "Bridge lifecycle response is invalid");
    }
    if (lifecycle.protocol_version === undefined || lifecycle.protocol_version === null) {
      if (bundled) {
        throw new BridgeError("bridge_protocol_incompatible", "Bundled Bridge did not report a lifecycle protocol version");
      }
      return { compatible: true, legacy: true, protocolVersion: 0, distribution: "legacy-python" };
    }
    if (!Number.isInteger(Number(lifecycle.pid))) {
      throw new BridgeError("bridge_protocol_invalid", "Bridge lifecycle response is invalid");
    }
    const protocolVersion = Number(lifecycle.protocol_version);
    const distribution = String(lifecycle.distribution || "");
    const bridgeVersion = String(lifecycle.bridge_version || "");
    if (protocolVersion !== 1 || !bridgeVersion || !["xpi-bundled", "source"].includes(distribution)) {
      throw new BridgeError("bridge_protocol_incompatible", "Bridge lifecycle protocol or distribution is unsupported", {
        protocol_version: lifecycle.protocol_version,
        bridge_version: lifecycle.bridge_version,
        distribution: lifecycle.distribution,
      });
    }
    if (bundled && (
      distribution !== "xpi-bundled"
      || bridgeVersion !== state.bridgeBundleInfo?.manifest?.bridge_version
    )) {
      throw new BridgeError("bridge_bundle_runtime_mismatch", "Running Bridge does not match the installed Bundle", {
        expected_version: state.bridgeBundleInfo?.manifest?.bridge_version,
        actual_version: bridgeVersion,
        distribution,
      });
    }
    return { compatible: true, legacy: false, protocolVersion, distribution, bridgeVersion };
  }

  async function writeRuntimeLocator(lifecycle) {
    if (!state.bridgeBundleInfo || !state.bridgeManagedConfig?.configPath) {
      return;
    }
    const path = PathUtils.join(state.bridgeHome, "bridge-runtime.json");
    const temporary = `${path}.tmp-${newOwnerValue()}`;
    await IOUtils.writeUTF8(temporary, JSON.stringify({
      runtime_schema_version: 1,
      bridge_version: lifecycle.bridge_version,
      protocol_version: lifecycle.protocol_version,
      distribution: lifecycle.distribution,
      executable: state.bridgeBundleInfo.executable,
      config_path: state.bridgeManagedConfig.configPath,
      manifest_sha256: state.bridgeBundleInfo.manifestSha256,
      updated_at: new Date().toISOString(),
    }, null, 2));
    await IOUtils.move(temporary, path, { noOverwrite: false });
  }

  function validateLauncherDescriptor(descriptor) {
    if (!descriptor || descriptor.schema_version !== 1 || descriptor.platform !== "windows") {
      throw new BridgeError("bridge_launcher_invalid", "Bridge launcher descriptor is invalid or unsupported");
    }
    if (!descriptor.command || !PathUtils.isAbsolute(String(descriptor.command))) {
      throw new BridgeError("bridge_launcher_invalid", "Bridge launcher command must be an absolute path");
    }
    if (!Array.isArray(descriptor.arguments) || descriptor.arguments.some((value) => typeof value !== "string")) {
      throw new BridgeError("bridge_launcher_invalid", "Bridge launcher arguments are invalid");
    }
    if (!descriptor.workdir || !PathUtils.isAbsolute(String(descriptor.workdir))) {
      throw new BridgeError("bridge_launcher_invalid", "Bridge launcher working directory must be absolute");
    }
    if (!descriptor.owner_arguments || !descriptor.owner_arguments.id || !descriptor.owner_arguments.token) {
      throw new BridgeError("bridge_launcher_invalid", "Bridge launcher owner arguments are missing");
    }
    return descriptor;
  }

  async function readProcessPipe(pipe) {
    if (!pipe || typeof pipe.readString !== "function") {
      return "";
    }
    let output = "";
    let chunk;
    while ((chunk = await pipe.readString())) {
      output += chunk;
    }
    return output;
  }

  async function monitorBridgeProcess(process, ownerId) {
    const stdoutPromise = readProcessPipe(process.stdout);
    const stderrPromise = readProcessPipe(process.stderr);
    const result = await process.wait();
    const [stdout, stderr] = await Promise.all([stdoutPromise, stderrPromise]);
    if (state && state.bridgeProcess === process) {
      state.bridgeProcess = null;
      if (!state.shuttingDown && state.bridgeOwnerId === ownerId) {
        state.bridgeState = "unavailable";
        state.bridgeOwnership = "none";
        state.bridgeOwnerId = null;
        state.bridgeOwnerToken = null;
        state.bridgeLastError = {
          code: "bridge_process_exited",
          message: `Bundled Bridge exited with code ${result.exitCode}`,
          details: {
            exit_code: result.exitCode,
            stdout: stdout.trim() || null,
            stderr: stderr.trim() || null,
          },
        };
        await appendLog("error", "bundled_bridge_exited", state.bridgeLastError);
        try {
          await writeStatus();
        } catch (error) {}
      }
    }
  }

  async function launchBridge(ownerId, ownerToken) {
    if (!["ready", "rollback"].includes(state.bridgeBundleState) || !state.bridgeBundleInfo?.executable) {
      if (state.bridgeLastError?.code) {
        throw new BridgeError(
          state.bridgeLastError.code,
          state.bridgeLastError.message || "The bundled Bridge executable is unavailable",
          state.bridgeLastError.details || null,
        );
      }
      throw new BridgeError("bridge_bundle_unavailable", "The bundled Bridge executable is unavailable");
    }
    if (!state.bridgeManagedConfig?.configPath) {
      throw new BridgeError("bridge_config_unavailable", "The managed Bridge configuration is unavailable", state.bridgeManagedConfig?.error || null);
    }
    const { Subprocess } = ChromeUtils.importESModule("resource://gre/modules/Subprocess.sys.mjs");
    const process = await Subprocess.call({
      command: state.bridgeBundleInfo.executable,
      arguments: [],
      workdir: state.bridgeBundleInfo.versionRoot,
      environmentAppend: true,
      environment: {
        ZOTERO_AGENT_BRIDGE_CONFIG: state.bridgeManagedConfig.configPath,
        ZOTERO_AGENT_BRIDGE_OWNER_ID: ownerId,
        ZOTERO_AGENT_BRIDGE_OWNER_TOKEN: ownerToken,
        ZOTERO_AGENT_BRIDGE_HOME_FOR_LOGS: state.bridgeHome,
        ZOTERO_AGENT_BRIDGE_DISTRIBUTION: "xpi-bundled",
        PYTHONUTF8: "1",
      },
      stdout: "pipe",
      stderr: "pipe",
    });
    state.bridgeProcess = process;
    void monitorBridgeProcess(process, ownerId);
    await appendLog("info", "bundled_bridge_launched", {
      pid: process.pid,
      owner_id: ownerId,
      executable: state.bridgeBundleInfo.executable,
      bridge_version: state.bridgeBundleInfo.manifest.bridge_version,
    });
  }

  async function startBundleAndWait(bundleInfo, { rollbackFrom = null } = {}) {
    state.bridgeBundleInfo = bundleInfo;
    state.bridgeState = "starting";
    const ownerId = newOwnerValue();
    const ownerToken = `${newOwnerValue()}${newOwnerValue()}`;
    state.bridgeOwnerId = ownerId;
    state.bridgeOwnerToken = ownerToken;
    await launchBridge(ownerId, ownerToken);

    const deadline = Date.now() + Math.max(1000, Number(state.config.bridgeStartupTimeoutMs));
    while (Date.now() < deadline) {
      const health = await checkBridgeHealth();
      if (health) {
        const lifecycle = health.lifecycle || health;
        classifyLifecycle(lifecycle, { bundled: true });
        const owned = Boolean(lifecycle.managed && lifecycle.owner_id === ownerId);
        if (!owned) {
          throw new BridgeError("bridge_owner_mismatch", "Bundled Bridge started without the expected owner identity", {
            expected_owner_id: ownerId,
            actual_owner_id: lifecycle.owner_id || null,
          });
        }
        state.bridgeState = "ready";
        state.bridgeOwnership = "owned";
        state.bridgeOwnerId = ownerId;
        state.bridgeOwnerToken = ownerToken;
        state.bridgeLastError = rollbackFrom
          ? {
              code: "bridge_bundle_rollback_active",
              message: `Bridge ${rollbackFrom} failed; running last-known-good ${lifecycle.bridge_version}`,
              details: { failed_version: rollbackFrom, rollback_version: lifecycle.bridge_version },
            }
          : null;
        await state.bridgeBundleManager.markLaunchSucceeded(bundleInfo);
        await writeRuntimeLocator(lifecycle);
        await appendLog(rollbackFrom ? "warning" : "info", rollbackFrom ? "bridge_rollback_ready" : "bridge_ready", {
          ownership: state.bridgeOwnership,
          owner_id: state.bridgeOwnerId,
          bridge_version: lifecycle.bridge_version,
          protocol_version: lifecycle.protocol_version,
          distribution: lifecycle.distribution,
          rollback_from: rollbackFrom,
        });
        return health;
      }
      await delay(250);
    }
    throw new BridgeError(
      "bridge_start_timeout",
      `Bridge did not become ready within ${state.config.bridgeStartupTimeoutMs} ms`,
      state.bridgeLastError,
    );
  }

  async function stopFailedBundleProcess() {
    const process = state.bridgeProcess;
    if (!process || (process.exitCode !== null && process.exitCode !== undefined)) {
      return;
    }
    try {
      await process.kill(0);
    } catch (error) {}
    if (state.bridgeProcess === process) {
      state.bridgeProcess = null;
    }
  }

  async function ensureBridgeAvailable({ force = false } = {}) {
    if (!state || state.shuttingDown) {
      throw new BridgeError("bridge_unavailable", "Bridge cannot start while the add-on is shutting down");
    }
    if (state.bridgeStartPromise) {
      return state.bridgeStartPromise;
    }
    state.bridgeStartPromise = (async () => {
      const bundleInstallError = state.bridgeBundleState === "error" ? state.bridgeLastError : null;
      const existing = await checkBridgeHealth();
      if (existing) {
        const lifecycle = existing.lifecycle || existing;
        const compatibility = classifyLifecycle(lifecycle);
        const stillOwned = Boolean(
          lifecycle.managed
          && state.bridgeOwnerId
          && state.bridgeOwnerToken
          && lifecycle.owner_id === state.bridgeOwnerId
        );
        state.bridgeState = "ready";
        state.bridgeOwnership = stillOwned ? "owned" : "shared";
        if (!stillOwned) {
          state.bridgeOwnerId = null;
          state.bridgeOwnerToken = null;
        }
        state.bridgeLastError = compatibility.legacy
          ? {
              code: "bridge_legacy_shared",
              message: "Using a compatible legacy shared Bridge without protocol metadata",
              details: null,
            }
          : null;
        return existing;
      }
      if (bundleInstallError) {
        state.bridgeLastError = bundleInstallError;
      }
      if (!state.config.autoStartBridge) {
        throw new BridgeError("bridge_autostart_disabled", "Bridge automatic startup is disabled");
      }

      const primaryBundle = state.bridgeBundleInfo;
      if (!primaryBundle) {
        if (state.bridgeLastError?.code) {
          throw new BridgeError(
            state.bridgeLastError.code,
            state.bridgeLastError.message || "The bundled Bridge executable is unavailable",
            state.bridgeLastError.details || null,
          );
        }
        throw new BridgeError("bridge_bundle_unavailable", "The bundled Bridge executable is unavailable");
      }
      state.bridgeLastError = null;
      try {
        return await startBundleAndWait(primaryBundle);
      } catch (error) {
        if (!primaryBundle) {
          throw error;
        }
        await state.bridgeBundleManager.recordLaunchFailure(primaryBundle, error);
        await stopFailedBundleProcess();
        const rollback = await state.bridgeBundleManager.rollbackCandidate(primaryBundle.manifest.bridge_version);
        if (!rollback) {
          throw error;
        }
        state.bridgeBundleState = "rollback";
        await appendLog("warning", "bridge_bundle_rollback_attempt", {
          failed_version: primaryBundle.manifest.bridge_version,
          rollback_version: rollback.manifest.bridge_version,
          error: serializeError(error),
        });
        return await startBundleAndWait(rollback, { rollbackFrom: primaryBundle.manifest.bridge_version });
      }
    })();

    try {
      return await state.bridgeStartPromise;
    } catch (error) {
      state.bridgeState = "unavailable";
      state.bridgeOwnership = "none";
      state.bridgeOwnerId = null;
      state.bridgeOwnerToken = null;
      state.bridgeLastError = serializeError(error);
      await appendLog("error", "bridge_autostart_failed", state.bridgeLastError);
      throw error;
    } finally {
      state.bridgeStartPromise = null;
      try {
        await writeStatus();
      } catch (error) {}
    }
  }

  async function bridgeRequest(method, path, payload = null) {
    if (state.bridgeState !== "ready") {
      await ensureBridgeAvailable();
    }
    try {
      return await rawBridgeRequest(method, path, payload);
    } catch (error) {
      if (!(error instanceof BridgeError) || error.code !== "bridge_unreachable") {
        throw error;
      }
      state.bridgeState = "unavailable";
      await ensureBridgeAvailable({ force: true });
      return await rawBridgeRequest(method, path, payload);
    }
  }

  async function stopOwnedBridge(reason) {
    if (
      !state
      || !state.config.stopOwnedBridgeOnShutdown
      || state.bridgeOwnership !== "owned"
      || !state.bridgeOwnerToken
    ) {
      return false;
    }
    try {
      await rawBridgeRequest("POST", "/lifecycle/shutdown", { reason }, {
        ownerToken: state.bridgeOwnerToken,
        timeoutMs: 2000,
      });
      await appendLog("info", "owned_bridge_shutdown_requested", {
        reason,
        owner_id: state.bridgeOwnerId,
      });
      return true;
    } catch (error) {
      await appendLog("error", "owned_bridge_shutdown_failed", serializeError(error));
      return false;
    } finally {
      state.bridgeOwnership = "none";
      state.bridgeOwnerId = null;
      state.bridgeOwnerToken = null;
    }
  }

  function installQuitObserver() {
    if (state.quitObserver) {
      return;
    }
    state.quitObserver = {
      observe() {
        if (!state || state.shuttingDown) {
          return;
        }
        state.shuttingDown = true;
        void writeStatus({ ready: false, last_seen: new Date().toISOString() });
        void stopOwnedBridge("zotero_exit");
      },
    };
    Services.obs.addObserver(state.quitObserver, "quit-application-granted");
  }

  function removeQuitObserver() {
    if (!state || !state.quitObserver) {
      return;
    }
    try {
      Services.obs.removeObserver(state.quitObserver, "quit-application-granted");
    } catch (error) {}
    state.quitObserver = null;
  }

  function createBridgeConfigManager() {
    const scope = {};
    Services.scriptloader.loadSubScript(
      `${rootURI}chrome/content/scripts/bridge_config_manager.js`,
      scope,
    );
    if (!scope.ZoteroAgentBridgeConfigManager || typeof scope.ZoteroAgentBridgeConfigManager.create !== "function") {
      throw new BridgeError("bridge_config_module_missing", "Bridge configuration manager module failed to load");
    }
    return scope.ZoteroAgentBridgeConfigManager.create({
      bridgeHome: state.bridgeHome,
      zoteroDataDir: Zotero.DataDirectory.dir,
      addonConfig: state.config,
      Services,
      IOUtils,
      PathUtils,
      appendLog,
    });
  }

  function createBridgeBundleManager() {
    const scope = {};
    Services.scriptloader.loadSubScript(
      `${rootURI}chrome/content/scripts/bridge_bundle_manager.js`,
      scope,
    );
    if (!scope.ZoteroAgentBridgeBundleManager || typeof scope.ZoteroAgentBridgeBundleManager.create !== "function") {
      throw new BridgeError("bridge_bundle_module_missing", "Bridge Bundle manager module failed to load");
    }
    return scope.ZoteroAgentBridgeBundleManager.create({
      rootURI,
      addonVersion: ADDON_VERSION,
      Services,
      IOUtils,
      PathUtils,
      Zotero,
      appendLog,
    });
  }

  function createPiChatPanel() {
    const hostWindow = (typeof Zotero.getMainWindow === "function" && Zotero.getMainWindow())
      || Services.appShell.hiddenDOMWindow;
    const scope = {
      document: hostWindow.document,
    };
    for (const resource of [
      "chrome/content/vendor/marked/marked.umd.js",
      "chrome/content/vendor/katex/katex.min.js",
      "chrome/content/scripts/markdown_renderer.js",
      "chrome/content/scripts/pi_chat_panel.js",
    ]) {
      Services.scriptloader.loadSubScript(`${rootURI}${resource}`, scope);
    }
    const markedAPI = scope.marked && scope.marked.marked ? scope.marked.marked : scope.marked;
    if (!markedAPI || typeof markedAPI.lexer !== "function") {
      throw new BridgeError("markdown_parser_module_missing", "Bundled Markdown parser failed to load");
    }
    if (!scope.katex || typeof scope.katex.render !== "function") {
      throw new BridgeError("math_renderer_module_missing", "Bundled math renderer failed to load");
    }
    if (!scope.ZoteroAgentBridgeMarkdownRenderer || typeof scope.ZoteroAgentBridgeMarkdownRenderer.create !== "function") {
      throw new BridgeError("markdown_renderer_module_missing", "Markdown renderer module failed to load");
    }
    if (!scope.ZoteroAgentBridgePiChatPanel || typeof scope.ZoteroAgentBridgePiChatPanel.create !== "function") {
      throw new BridgeError("pi_chat_module_missing", "Pi chat panel module failed to load");
    }
    return scope.ZoteroAgentBridgePiChatPanel.create({
      Zotero,
      rootURI,
      locale: Services.locale.appLocaleAsBCP47,
      bridgeRequest,
      appendLog,
      markdownRenderer: scope.ZoteroAgentBridgeMarkdownRenderer.create({
        marked: scope.marked,
        katex: scope.katex,
      }),
      async fileExists(path) {
        try {
          return Boolean(path && await IOUtils.exists(path));
        } catch (error) {
          return false;
        }
      },
    });
  }

  function noteTitle(note) {
    if (typeof note.getNoteTitle === "function") {
      const value = String(note.getNoteTitle() || "").trim();
      if (value) {
        return value;
      }
    }
    const raw = String(note.getNote ? note.getNote() : "");
    const text = raw
      .replace(/<br\s*\/?>/gi, "\n")
      .replace(/<[^>]+>/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    return text.slice(0, 80) || `Note ${note.key}`;
  }

  function parentItemForNote(note) {
    if (!note.parentID) {
      return null;
    }
    return Zotero.Items.get(note.parentID);
  }

  async function reportObsidianSyncStatus(noteKey, payload) {
    try {
      await bridgeRequest("POST", `/obsidian/notes/${encodeURIComponent(noteKey)}/sync-status`, payload);
    } catch (error) {
      await appendLog("error", "obsidian_sync_status_report_failed", serializeError(error));
    }
  }

  async function syncNoteToObsidian(note, win) {
    if (!note || !note.isNote || !note.isNote()) {
      throw new BridgeError("invalid_selection", "Select exactly one Zotero note to sync.");
    }
    const parent = parentItemForNote(note);
    if (!parent) {
      throw new BridgeError("note_parent_missing", "Selected note has no parent item.");
    }
    const betterNotes = Zotero.BetterNotes;
    if (!betterNotes || !betterNotes.api || !betterNotes.api.sync || !betterNotes.api.convert) {
      throw new BridgeError("better_notes_unavailable", "Better Notes is not installed or its API is unavailable.");
    }

    const prepared = await bridgeRequest("POST", "/obsidian/notes/prepare-sync", {
      item_key: parent.key,
      note_key: note.key,
      note_title: noteTitle(note),
    });

    try {
      const syncDir = prepared.sync_dir;
      const filename = prepared.filename;
      const markdownPath = prepared.markdown_path;
      await IOUtils.makeDirectory(syncDir, { ignoreExisting: true });
      const markdown = await betterNotes.api.convert.note2md(note, syncDir, {
        keepNoteLink: false,
        withYAMLHeader: true,
        cachedYAMLHeader: prepared.frontmatter || {},
      });
      await Zotero.File.putContentsAsync(markdownPath, markdown);
      const mdStatus = betterNotes.api.sync.getMDStatusFromContent(markdown);
      if (typeof betterNotes.api.sync.addSyncNote === "function") {
        betterNotes.api.sync.addSyncNote(note.id);
      }
      betterNotes.api.sync.updateSyncStatus(note.id, {
        path: syncDir,
        filename,
        itemID: note.id,
        md5: Zotero.Utilities.Internal.md5(mdStatus.content, false),
        noteMd5: Zotero.Utilities.Internal.md5(note.getNote(), false),
        lastsync: new Date().getTime(),
      });
      await reportObsidianSyncStatus(note.key, {
        item_key: parent.key,
        stable_id: prepared.stable_id,
        status: "synced",
        markdown_path: markdownPath,
        vault_relative_path: prepared.vault_relative_path,
        error: null,
      });
      win.alert(`Synced to Obsidian:\n${prepared.vault_relative_path}`);
      await appendLog("info", "obsidian_sync_completed", {
        item_key: parent.key,
        note_key: note.key,
        markdown_path: markdownPath,
      });
    } catch (error) {
      await reportObsidianSyncStatus(note.key, {
        item_key: parent.key,
        stable_id: prepared.stable_id,
        status: "error",
        markdown_path: prepared.markdown_path,
        vault_relative_path: prepared.vault_relative_path,
        error: error && error.message ? error.message : String(error),
      });
      throw error;
    }
  }

  async function syncSelectedNoteToObsidian(win) {
    try {
      const selected = win.ZoteroPane.getSelectedItems().filter((item) => item.isNote && item.isNote());
      if (selected.length !== 1) {
        throw new BridgeError("invalid_selection", "Select exactly one Zotero note to sync.");
      }
      await syncNoteToObsidian(selected[0], win);
    } catch (error) {
      await appendLog("error", "obsidian_sync_failed", serializeError(error));
      win.alert(`Zotero Agent Bridge Obsidian sync failed:\n${error && error.message ? error.message : String(error)}`);
    }
  }

  function installMenus(win) {
    const doc = win.document;
    const itemMenu = doc.getElementById("zotero-itemmenu");
    if (!itemMenu || state.menuItems.has(win)) {
      return;
    }
    const existing = doc.getElementById("zotero-agent-bridge-sync-obsidian");
    if (existing) {
      state.menuItems.set(win, existing);
      return;
    }
    const menuItem = doc.createXULElement ? doc.createXULElement("menuitem") : doc.createElement("menuitem");
    menuItem.id = "zotero-agent-bridge-sync-obsidian";
    menuItem.setAttribute("label", "Sync to Obsidian via Bridge");
    menuItem.addEventListener("command", () => {
      void syncSelectedNoteToObsidian(win);
    });
    itemMenu.appendChild(menuItem);
    state.menuItems.set(win, menuItem);
  }

  function uninstallMenus(win = null) {
    const entries = win
      ? [[win, state.menuItems.get(win)]]
      : [...state.menuItems.entries()];
    for (const [owner, item] of entries) {
      try {
        item?.remove();
      } catch (error) {}
      state.menuItems.delete(owner);
    }
  }

  async function writeStatus(extra = {}) {
    const payload = Object.assign(
      {
        addon_version: state.addonVersion,
        started_at: state.startedAt,
        last_seen: new Date().toISOString(),
        ready: true,
        bridge_home: state.bridgeHome,
        bridge_state: state.bridgeState,
        bridge_ownership: state.bridgeOwnership,
        bridge_started_by_addon: state.bridgeOwnership === "owned",
        bridge_last_error: state.bridgeLastError,
        bridge_bundle_state: state.bridgeBundleState,
        bridge_bundle_version: state.bridgeBundleInfo?.manifest?.bridge_version || null,
        bridge_bundle_path: state.bridgeBundleInfo?.versionRoot || null,
        bridge_managed_config_path: state.bridgeManagedConfig?.configPath || null,
        bridge_config_source: state.bridgeManagedConfig?.source || null,
      },
      extra,
    );
    await IOUtils.writeUTF8(state.statusFile, JSON.stringify(payload, null, 2));
  }

  function startTimers() {
    state.statusTimer = setInterval(() => {
      void writeStatus();
    }, state.config.statusIntervalMs);
    state.pollTimer = setInterval(() => {
      void pollCommands();
    }, state.config.pollIntervalMs);
  }

  function stopTimers() {
    if (state.statusTimer) {
      clearInterval(state.statusTimer);
      state.statusTimer = null;
    }
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
  }

  async function listCommandFiles() {
    const entries = [];
    for (const entry of await IOUtils.getChildren(state.commandsDir)) {
      if (entry.endsWith(".json")) {
        entries.push(entry);
      }
    }
    return entries.sort();
  }

  async function pollCommands() {
    if (!state || state.shuttingDown || state.queueRunning) {
      return;
    }
    state.queueRunning = true;
    try {
      const commandFiles = await listCommandFiles();
      for (const filePath of commandFiles) {
        await processCommandFile(filePath);
      }
    } catch (error) {
      await appendLog("error", "poll_commands_failed", serializeError(error));
    } finally {
      state.queueRunning = false;
    }
  }

  async function processCommandFile(filePath) {
    let command = null;
    try {
      const rawCommand = await IOUtils.readUTF8(filePath);
      command = JSON.parse(rawCommand);
      const response = await processCommand(command);
      await writeResponse(command.request_id, response);
      await archiveCommandFile(filePath, command.request_id, true);
    } catch (error) {
      const requestId =
        command && command.request_id ? command.request_id : PathUtils.filename(filePath);
      const payload = buildErrorResponse(requestId, error);
      await writeResponse(requestId, payload);
      await archiveCommandFile(filePath, requestId, false);
      await appendLog("error", "process_command_failed", {
        request_id: requestId,
        file_path: filePath,
        error: serializeError(error),
      });
    }
  }

  async function writeResponse(requestId, payload) {
    const responsePath = PathUtils.join(state.responsesDir, `${requestId}.json`);
    await IOUtils.writeUTF8(responsePath, JSON.stringify(payload, null, 2));
  }

  async function archiveCommandFile(filePath, requestId, success) {
    if (!(await IOUtils.exists(filePath))) {
      return;
    }
    const archivedName = `${requestId}.${Date.now()}.${success ? "ok" : "error"}.json`;
    const archivedPath = PathUtils.join(state.archiveDir, archivedName);
    await IOUtils.move(filePath, archivedPath);
  }

  async function processCommand(request) {
    validateRequest(request);
    switch (request.command) {
      case "create_item":
        return await handleCreateItem(request);
      case "update_item":
        return await handleUpdateItem(request);
      case "attach_linked_pdf":
        return await handleAttachLinkedPdf(request);
      case "create_note":
        return await handleCreateNote(request);
      case "create_collection":
        return await handleCreateCollection(request);
      case "update_collection":
        return await handleUpdateCollection(request);
      default:
        throw new BridgeError("unsupported_command", `Unsupported command: ${request.command}`);
    }
  }

  function validateRequest(request) {
    if (!request || typeof request !== "object") {
      throw new BridgeError("invalid_request", "Request must be an object");
    }
    if (!request.request_id || typeof request.request_id !== "string") {
      throw new BridgeError("invalid_request", "request_id is required");
    }
    if (!request.command || typeof request.command !== "string") {
      throw new BridgeError("invalid_request", "command is required");
    }
    if (!("payload" in request) || typeof request.payload !== "object" || !request.payload) {
      throw new BridgeError("invalid_request", "payload is required");
    }
  }

  async function handleCreateItem(request) {
    const payload = request.payload;
    const itemType = payload.item_type || "journalArticle";
    const item = new Zotero.Item(itemType);
    item.libraryID = resolveLibraryID(payload.library_id);
    applyFields(item, payload.fields || {});
    applyCreators(item, payload.creators || []);
    applyTags(item, payload.tags || []);
    applyCollections(item, payload.collections || []);
    await item.saveTx();

    return buildSuccessResponse(request.request_id, {
      library_id: item.libraryID,
      item_key: item.key,
      attachment_key: null,
      note_key: null,
      sync_status: payload.sync_status || "synced",
      version: item.version,
    });
  }

  async function handleUpdateItem(request) {
    const payload = request.payload;
    const item = await getItemByKey(payload.item_key, payload.library_id);
    if (payload.version !== undefined && item.version !== payload.version) {
      throw new BridgeError("version_conflict", "Item version conflict", {
        expected: payload.version,
        actual: item.version,
        item_key: item.key,
      });
    }

    if (payload.fields) {
      applyFields(item, payload.fields);
    }
    if (payload.creators) {
      applyCreators(item, payload.creators);
    }
    if (payload.tags) {
      applyTags(item, payload.tags);
    }
    if (payload.collections) {
      applyCollections(item, payload.collections);
    }

    await item.saveTx();

    return buildSuccessResponse(request.request_id, {
      library_id: item.libraryID,
      item_key: item.key,
      attachment_key: null,
      note_key: null,
      sync_status: payload.sync_status || "synced",
      version: item.version,
    });
  }

  async function handleAttachLinkedPdf(request) {
    const payload = request.payload;
    const parent = await getItemByKey(payload.item_key, payload.library_id);
    const normalized = await normalizeAttachmentPath(payload.path);

    let attachment;
    if (normalized.relativePath) {
      attachment = await Zotero.Attachments.linkFromFileWithRelativePath({
        path: normalized.relativePath,
        title: payload.title || PathUtils.filename(normalized.absolutePath),
        contentType: payload.content_type || "application/pdf",
        parentItemID: parent.id,
      });
    } else {
      attachment = await Zotero.Attachments.linkFromFile({
        file: normalized.absolutePath,
        title: payload.title || PathUtils.filename(normalized.absolutePath),
        contentType: payload.content_type || "application/pdf",
        parentItemID: parent.id,
      });
    }

    return buildSuccessResponse(request.request_id, {
      library_id: parent.libraryID,
      item_key: parent.key,
      attachment_key: attachment.key,
      note_key: null,
      sync_status: payload.sync_status || "synced",
      version: attachment.version,
    });
  }

  async function handleCreateNote(request) {
    const payload = request.payload;
    const parent = await getItemByKey(payload.item_key, payload.library_id);
    const note = new Zotero.Item("note");
    note.libraryID = parent.libraryID;
    note.parentID = parent.id;
    await note.saveTx();
    note.setNote(payload.note_html || "");
    await note.saveTx();

    return buildSuccessResponse(request.request_id, {
      library_id: parent.libraryID,
      item_key: parent.key,
      attachment_key: null,
      note_key: note.key,
      sync_status: payload.sync_status || "synced",
      version: note.version,
    });
  }

  async function handleCreateCollection(request) {
    const payload = request.payload;
    const name = String(payload.name || "").trim();
    if (!name) {
      throw new BridgeError("invalid_request", "Collection name is required");
    }

    const collection = new Zotero.Collection();
    collection.libraryID = resolveLibraryID(payload.library_id);
    collection.name = name;
    if (payload.parent_key) {
      const parent = await getCollectionByKey(payload.parent_key, collection.libraryID, "parent_collection_not_found");
      collection.parentID = parent.id;
    }
    await collection.saveTx();

    return buildSuccessResponse(request.request_id, {
      library_id: collection.libraryID,
      collection_key: collection.key,
      version: collection.version,
      name: collection.name,
      parent_key: payload.parent_key || null,
    });
  }

  async function handleUpdateCollection(request) {
    const payload = request.payload;
    const collection = await getCollectionByKey(payload.collection_key, payload.library_id);
    if (payload.version !== undefined && collection.version !== payload.version) {
      throw new BridgeError("version_conflict", "Collection version conflict", {
        expected: payload.version,
        actual: collection.version,
        collection_key: collection.key,
      });
    }

    if (payload.name !== undefined && payload.name !== null) {
      const name = String(payload.name).trim();
      if (!name) {
        throw new BridgeError("invalid_request", "Collection name is required");
      }
      collection.name = name;
    }
    if (Object.prototype.hasOwnProperty.call(payload, "parent_key")) {
      if (payload.parent_key && payload.parent_key === payload.collection_key) {
        throw new BridgeError("invalid_parent_collection", "Collection cannot be its own parent");
      }
      if (payload.parent_key) {
        const parent = await getCollectionByKey(payload.parent_key, collection.libraryID, "parent_collection_not_found");
        collection.parentID = parent.id;
      } else {
        collection.parentID = null;
      }
    }
    await collection.saveTx();

    return buildSuccessResponse(request.request_id, {
      library_id: collection.libraryID,
      collection_key: collection.key,
      version: collection.version,
      name: collection.name,
      parent_key: Object.prototype.hasOwnProperty.call(payload, "parent_key")
        ? (payload.parent_key || null)
        : (collection.parentKey || null),
    });
  }

  function resolveLibraryID(libraryID) {
    if (libraryID === undefined || libraryID === null || libraryID === 0) {
      return Zotero.Libraries.userLibraryID;
    }
    return libraryID;
  }

  function applyFields(item, fields) {
    for (const [field, value] of Object.entries(fields)) {
      if (value === null || value === undefined) {
        continue;
      }
      item.setField(field, value);
    }
  }

  function applyCreators(item, creators) {
    item.setCreators(creators, { strict: false });
  }

  function applyTags(item, tags) {
    item.setTags(
      tags.map((tag) => {
        if (typeof tag === "string") {
          return tag;
        }
        return {
          tag: tag.tag,
          type: tag.type || 0,
        };
      }),
    );
  }

  function applyCollections(item, collections) {
    item.setCollections(collections);
  }

  async function getItemByKey(itemKey, libraryID) {
    const resolvedLibraryID = resolveLibraryID(libraryID);
    const item = Zotero.Items.getByLibraryAndKey(resolvedLibraryID, itemKey);
    if (!item) {
      throw new BridgeError("item_not_found", `Item not found: ${itemKey}`, {
        library_id: resolvedLibraryID,
      });
    }
    return item;
  }

  async function getCollectionByKey(collectionKey, libraryID, errorCode = "collection_not_found") {
    const resolvedLibraryID = resolveLibraryID(libraryID);
    const collection = Zotero.Collections.getByLibraryAndKey(resolvedLibraryID, collectionKey);
    if (!collection) {
      throw new BridgeError(errorCode, `Collection not found: ${collectionKey}`, {
        library_id: resolvedLibraryID,
      });
    }
    return collection;
  }

  async function normalizeAttachmentPath(inputPath) {
    if (!inputPath || typeof inputPath !== "string") {
      throw new BridgeError("invalid_attachment_path", "Attachment path is required");
    }

    const cleaned = inputPath.replace(/\//g, "\\");
    const basePath = Zotero.Prefs.get("extensions.zotero.baseAttachmentPath");
    const absolutePath = PathUtils.isAbsolute(cleaned)
      ? PathUtils.normalize(cleaned)
      : basePath
        ? PathUtils.normalize(PathUtils.join(basePath, cleaned))
        : PathUtils.normalize(PathUtils.join(state.bridgeHome, cleaned));

    if (!(await IOUtils.exists(absolutePath))) {
      throw new BridgeError("invalid_attachment_path", `Attachment not found: ${inputPath}`);
    }

    const saveRelative = Zotero.Prefs.get("extensions.zotero.saveRelativeAttachmentPath");
    if (basePath && saveRelative) {
      const normalizedBase = PathUtils.normalize(basePath);
      if (absolutePath.startsWith(normalizedBase)) {
        const relativePath = absolutePath
          .slice(normalizedBase.length)
          .replace(/^[\\/]+/, "")
          .replace(/\\/g, "/");
        return {
          absolutePath,
          relativePath,
        };
      }
    }

    return {
      absolutePath,
      relativePath: null,
    };
  }

  function buildSuccessResponse(requestId, result) {
    return {
      request_id: requestId,
      ok: true,
      error: null,
      result,
    };
  }

  function buildErrorResponse(requestId, error) {
    return {
      request_id: requestId,
      ok: false,
      error: serializeError(error),
      result: {
        library_id: null,
        item_key: null,
        attachment_key: null,
        note_key: null,
        sync_status: "error",
      },
    };
  }

  function serializeError(error) {
    if (error instanceof BridgeError || (error && typeof error.code === "string")) {
      return {
        code: error.code,
        message: error.message || String(error),
        details: error.details || null,
      };
    }
    return {
      code: "internal_error",
      message: error && error.message ? error.message : String(error),
      details: null,
    };
  }

  async function initialize() {
    const config = await loadConfig();
    const bridgeHome = getBridgeHome(config);
    state = createState(config, bridgeHome);
    await ensureDirectories();
    state.bridgeConfigManager = createBridgeConfigManager();
    try {
      state.bridgeManagedConfig = await state.bridgeConfigManager.ensureManagedConfig();
      state.config.bridgeHost = state.bridgeManagedConfig.config.host || DEFAULT_BRIDGE_HOST;
      state.config.bridgePort = state.bridgeManagedConfig.config.port || DEFAULT_BRIDGE_PORT;
      state.config.apiToken = state.bridgeManagedConfig.config.api_token || state.config.apiToken;
    } catch (error) {
      state.bridgeManagedConfig = { error: serializeError(error), source: "error" };
      state.bridgeLastError = serializeError(error);
      await appendLog("error", "bridge_config_migration_failed", state.bridgeLastError);
    }
    state.bridgeBundleManager = createBridgeBundleManager();
    state.bridgeBundleState = "installing";
    try {
      state.bridgeBundleInfo = await state.bridgeBundleManager.ensureInstalled();
      state.bridgeBundleState = "ready";
    } catch (error) {
      state.bridgeBundleState = "error";
      state.bridgeLastError = serializeError(error);
      await appendLog("error", "bridge_bundle_install_failed", state.bridgeLastError);
    }
    state.chatPanel = createPiChatPanel();
    const existingWindows = typeof Zotero.getMainWindows === "function" ? Zotero.getMainWindows() : [];
    for (const win of existingWindows) {
      state.chatPanel.installWindow(win);
    }
    await appendLog("info", "addon_started", {
      addon_version: ADDON_VERSION,
      bridge_home: bridgeHome,
    });
    await writeStatus();
    startTimers();
    installQuitObserver();
    try {
      await ensureBridgeAvailable();
    } catch (error) {
      Zotero.debug(`ZoteroAgentBridge automatic Bridge startup failed: ${error}`);
    }
  }

  async function shutdownAddon() {
    if (!state) {
      return;
    }
    state.shuttingDown = true;
    removeQuitObserver();
    stopTimers();
    await writeStatus({
      ready: false,
      last_seen: new Date().toISOString(),
    });
    await stopOwnedBridge("addon_shutdown");
    await appendLog("info", "addon_stopped");
  }

  return {
    hooks: {
      async onStartup() {
        await initialize();
      },
      onMainWindowLoad(window) {
        installMenus(window);
        state.chatPanel?.installWindow(window);
      },
      onMainWindowUnload(window) {
        state.chatPanel?.cleanupWindow(window);
        uninstallMenus(window);
      },
      async onShutdown() {
        state.chatPanel?.shutdown();
        uninstallMenus();
        await shutdownAddon();
      },
    },
  };
}

async function startup({ id, version, resourceURI, rootURI }, reason) {
  await Zotero.initializationPromise;
  try {
    Zotero.ZoteroAgentBridge = buildZoteroAgentBridge(rootURI);
    await Zotero.ZoteroAgentBridge.hooks.onStartup();
    await writeBootstrapLog("startup_ok", { rootURI, version });
  } catch (error) {
    await writeBootstrapLog("startup_failed", {
      message: error?.message || String(error),
      stack: error?.stack || null,
      rootURI,
      version,
    });
    throw error;
  }
}

function onMainWindowLoad({ window }, reason) {
  Zotero.ZoteroAgentBridge?.hooks.onMainWindowLoad(window);
}

function onMainWindowUnload({ window }, reason) {
  Zotero.ZoteroAgentBridge?.hooks.onMainWindowUnload(window);
}

async function shutdown({ id, version, resourceURI, rootURI }, reason) {
  if (reason === APP_SHUTDOWN) {
    return;
  }

  await Zotero.ZoteroAgentBridge?.hooks.onShutdown();
}

function uninstall(data, reason) {}

