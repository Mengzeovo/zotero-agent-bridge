/**
 * Zotero Pi Assistant add-on bootstrap.
 *
 * Compatible with Zotero 7/8/9 bootstrapped add-ons.
 */

async function convertMarkdownNoteHTML(payload, betterNotes) {
  const fallbackHTML = typeof payload?.note_html === "string" ? payload.note_html : "";
  const markdown = typeof payload?.markdown === "string" ? payload.markdown : "";
  const convert = betterNotes?.api?.convert;
  if (!markdown.trim() || !convert || typeof convert.md2html !== "function") {
    return { html: fallbackHTML, renderer: "bridge", error: null };
  }
  try {
    const html = await convert.md2html(markdown);
    if (typeof html !== "string" || !html.trim()) {
      throw new Error("Better Notes returned empty note HTML");
    }
    return { html, renderer: "better-notes", error: null };
  } catch (error) {
    return { html: fallbackHTML, renderer: "bridge", error };
  }
}

const EXPERIENCE_NOTE_MARKER = "Zotero Pi Assistant · Experience Note v1";
const PI_ONLY_LIFECYCLE_PROTOCOL_VERSION = 2;
const TRANSITIONAL_LIFECYCLE_PROTOCOL_VERSION = 1;
const PI_ONLY_PRODUCT_SCOPE = "zotero-pi-only";
const SUPPORTED_BRIDGE_DISTRIBUTIONS = Object.freeze(["xpi-bundled", "source"]);

class BridgeProtocolError extends Error {
  constructor(code, message, details = null) {
    super(message);
    this.name = "BridgeError";
    this.code = code;
    this.details = details;
  }
}

function classifyBridgeLifecycle(lifecycle, {
  bundled = false,
  expectedBundleVersion = null,
  expectedBundleProtocolVersion = null,
  expectedProductScope = PI_ONLY_PRODUCT_SCOPE,
} = {}) {
  if (!lifecycle || typeof lifecycle !== "object") {
    throw new BridgeProtocolError("bridge_protocol_invalid", "Bridge lifecycle response is invalid");
  }
  if (lifecycle.protocol_version === undefined || lifecycle.protocol_version === null) {
    if (bundled) {
      throw new BridgeProtocolError(
        "bridge_protocol_incompatible",
        "Bundled Bridge did not report a lifecycle protocol version",
      );
    }
    return {
      compatible: true,
      legacy: true,
      transitional: true,
      piOnly: false,
      protocolVersion: 0,
      distribution: "legacy-python",
      bridgeVersion: String(lifecycle.bridge_version || ""),
      productScope: "legacy-unknown",
    };
  }
  if (!Number.isInteger(Number(lifecycle.pid))) {
    throw new BridgeProtocolError("bridge_protocol_invalid", "Bridge lifecycle response is invalid");
  }
  const protocolVersion = Number(lifecycle.protocol_version);
  const distribution = String(lifecycle.distribution || "");
  const bridgeVersion = String(lifecycle.bridge_version || "");
  const productScope = String(lifecycle.product_scope || "");
  const supportedProtocol = (
    protocolVersion === PI_ONLY_LIFECYCLE_PROTOCOL_VERSION
    || protocolVersion === TRANSITIONAL_LIFECYCLE_PROTOCOL_VERSION
  );
  if (!supportedProtocol || !bridgeVersion || !SUPPORTED_BRIDGE_DISTRIBUTIONS.includes(distribution)) {
    throw new BridgeProtocolError(
      "bridge_protocol_incompatible",
      "Bridge lifecycle protocol or distribution is unsupported",
      {
        protocol_version: lifecycle.protocol_version,
        bridge_version: lifecycle.bridge_version,
        product_scope: lifecycle.product_scope,
        distribution: lifecycle.distribution,
      },
    );
  }
  if (protocolVersion === PI_ONLY_LIFECYCLE_PROTOCOL_VERSION && productScope !== expectedProductScope) {
    throw new BridgeProtocolError(
      "bridge_protocol_incompatible",
      "Bridge lifecycle product scope is unsupported",
      {
        expected_product_scope: expectedProductScope,
        product_scope: lifecycle.product_scope,
        protocol_version: lifecycle.protocol_version,
      },
    );
  }
  if (bundled && (
    distribution !== "xpi-bundled"
    || (expectedBundleVersion && bridgeVersion !== expectedBundleVersion)
    || (expectedBundleProtocolVersion !== null && protocolVersion !== Number(expectedBundleProtocolVersion))
  )) {
    throw new BridgeProtocolError(
      "bridge_bundle_runtime_mismatch",
      "Running Bridge does not match the installed Bundle",
      {
        expected_version: expectedBundleVersion,
        actual_version: bridgeVersion,
        expected_protocol_version: expectedBundleProtocolVersion,
        actual_protocol_version: protocolVersion,
        distribution,
      },
    );
  }
  const piOnly = protocolVersion === PI_ONLY_LIFECYCLE_PROTOCOL_VERSION;
  return {
    compatible: true,
    legacy: !piOnly,
    transitional: !piOnly,
    piOnly,
    protocolVersion,
    distribution,
    bridgeVersion,
    productScope: piOnly ? productScope : (productScope || "legacy-agent-bridge"),
  };
}

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
  const ADDON_VERSION = "0.4.2-beta";
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
    return classifyBridgeLifecycle(lifecycle, {
      bundled,
      expectedBundleVersion: state.bridgeBundleInfo?.manifest?.bridge_version || null,
      expectedBundleProtocolVersion: state.bridgeBundleInfo?.manifest?.protocol_version ?? null,
      expectedProductScope: state.bridgeBundleInfo?.manifest?.product_scope || PI_ONLY_PRODUCT_SCOPE,
    });
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
      product_scope: lifecycle.product_scope || null,
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
              details: {
                failed_version: rollbackFrom,
                rollback_version: lifecycle.bridge_version,
                rollback_protocol_version: lifecycle.protocol_version,
              },
            }
          : null;
        await state.bridgeBundleManager.markLaunchSucceeded(bundleInfo);
        await writeRuntimeLocator(lifecycle);
        await appendLog(rollbackFrom ? "warning" : "info", rollbackFrom ? "bridge_rollback_ready" : "bridge_ready", {
          ownership: state.bridgeOwnership,
          owner_id: state.bridgeOwnerId,
          bridge_version: lifecycle.bridge_version,
          protocol_version: lifecycle.protocol_version,
          product_scope: lifecycle.product_scope || null,
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
        const rollback = await state.bridgeBundleManager.rollbackCandidate(primaryBundle);
        if (!rollback) {
          throw error;
        }
        state.bridgeBundleState = "rollback";
        await appendLog("warning", "bridge_bundle_rollback_attempt", {
          failed_version: primaryBundle.manifest.bridge_version,
          rollback_version: rollback.manifest.bridge_version,
          rollback_protocol_version: rollback.manifest.protocol_version,
          error: serializeError(error),
        });
        try {
          return await startBundleAndWait(rollback, { rollbackFrom: primaryBundle.manifest.bridge_version });
        } catch (rollbackError) {
          await state.bridgeBundleManager.recordLaunchFailure(rollback, rollbackError);
          await stopFailedBundleProcess();
          await appendLog("error", "bridge_bundle_rollback_failed", {
            failed_version: primaryBundle.manifest.bridge_version,
            rollback_version: rollback.manifest.bridge_version,
            rollback_protocol_version: rollback.manifest.protocol_version,
            error: serializeError(rollbackError),
          });
          throw new BridgeError(
            "bridge_rollback_failed",
            "The primary Bridge and its rollback candidate both failed to start",
            {
              primary: serializeError(error),
              rollback: serializeError(rollbackError),
            },
          );
        }
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

  async function bridgeRequest(method, path, payload = null, options = {}) {
    if (state.bridgeState !== "ready") {
      await ensureBridgeAvailable();
    }
    try {
      return await rawBridgeRequest(method, path, payload, options);
    } catch (error) {
      if (
        options.retryOnUnreachable === false
        || !(error instanceof BridgeError)
        || error.code !== "bridge_unreachable"
      ) {
        throw error;
      }
      state.bridgeState = "unavailable";
      await ensureBridgeAvailable({ force: true });
      return await rawBridgeRequest(method, path, payload, options);
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
      case "create_assistant_note":
        return await handleCreateAssistantNote(request);
      case "upsert_assistant_experience_note":
        return await handleUpsertAssistantExperienceNote(request);
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

  async function handleCreateAssistantNote(request) {
    const payload = request.payload;
    if (!/^[0-9a-f]{64}$/i.test(String(payload.document_id || ""))) {
      throw new BridgeError("invalid_request", "Assistant document_id must be a SHA-256 hex digest");
    }
    if (!/^[0-9a-f]{64}$/i.test(String(payload.context_fingerprint || ""))) {
      throw new BridgeError("invalid_request", "Assistant context_fingerprint must be a SHA-256 hex digest");
    }
    if (!String(payload.attachment_key || "").trim()) {
      throw new BridgeError("invalid_request", "Assistant attachment_key is required");
    }
    return await createAssistantNoteItem(request);
  }

  async function handleUpsertAssistantExperienceNote(request) {
    const payload = request.payload;
    if (!/^[0-9a-f]{64}$/i.test(String(payload.document_id || ""))) {
      throw new BridgeError("invalid_request", "Assistant document_id must be a SHA-256 hex digest");
    }
    if (!/^[0-9a-f]{64}$/i.test(String(payload.context_fingerprint || ""))) {
      throw new BridgeError("invalid_request", "Assistant context_fingerprint must be a SHA-256 hex digest");
    }
    if (payload.marker !== EXPERIENCE_NOTE_MARKER) {
      throw new BridgeError("invalid_request", "Experience note marker is invalid");
    }
    return await upsertAssistantExperienceNoteItem(request);
  }

  function experienceHTML(html) {
    return `<p><small>${EXPERIENCE_NOTE_MARKER}</small></p>${String(html || "")}`;
  }

  async function findExperienceNote(parent, requestedKey) {
    if (requestedKey) {
      const requested = Zotero.Items.getByLibraryAndKey(parent.libraryID, String(requestedKey));
      if (
        requested
        && requested.isNote
        && requested.isNote()
        && requested.parentID === parent.id
        && String(requested.getNote() || "").includes(EXPERIENCE_NOTE_MARKER)
      ) {
        return requested;
      }
    }
    const matches = [];
    for (const noteID of parent.getNotes()) {
      const note = Zotero.Items.get(noteID);
      if (note && note.isNote && note.isNote() && String(note.getNote() || "").includes(EXPERIENCE_NOTE_MARKER)) {
        matches.push(note);
      }
    }
    if (matches.length > 1) {
      throw new BridgeError("experience_note_conflict", "Multiple Pi experience notes exist for this Zotero item", {
        item_key: parent.key,
        note_keys: matches.map((note) => note.key),
      });
    }
    return matches[0] || null;
  }

  async function upsertAssistantExperienceNoteItem(request) {
    const payload = request.payload;
    const parent = await getItemByKey(payload.item_key, payload.library_id);
    const converted = await convertMarkdownNoteHTML(payload, Zotero.BetterNotes);
    let note = await findExperienceNote(parent, payload.note_key);
    const created = !note;
    if (!note) {
      note = new Zotero.Item("note");
      note.libraryID = parent.libraryID;
      note.parentID = parent.id;
      await note.saveTx();
    }
    note.setNote(experienceHTML(converted.html));
    await note.saveTx();
    return buildSuccessResponse(request.request_id, {
      library_id: parent.libraryID,
      item_key: parent.key,
      attachment_key: null,
      note_key: note.key,
      sync_status: payload.sync_status || "synced",
      version: note.version,
      created,
    });
  }

  async function createAssistantNoteItem(request) {
    const payload = request.payload;
    const parent = await getItemByKey(payload.item_key, payload.library_id);
    const converted = await convertMarkdownNoteHTML(payload, Zotero.BetterNotes);
    if (converted.renderer === "better-notes") {
      await appendLog("info", "note_markdown_converted_with_better_notes", {
        item_key: parent.key,
      });
    } else if (converted.error) {
      await appendLog("warning", "better_notes_note_conversion_failed", {
        item_key: parent.key,
        error: serializeError(converted.error),
      });
    }
    const note = new Zotero.Item("note");
    note.libraryID = parent.libraryID;
    note.parentID = parent.id;
    await note.saveTx();
    note.setNote(converted.html);
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

  function resolveLibraryID(libraryID) {
    if (libraryID === undefined || libraryID === null || Number(libraryID) === 0) {
      return Zotero.Libraries.userLibraryID;
    }
    const numericID = Number(libraryID);
    if (!Number.isFinite(numericID)) {
      return libraryID;
    }
    try {
      const currentUserID = Number(Zotero.Users?.getCurrentUserID?.());
      if (Number.isFinite(currentUserID) && numericID === currentUserID) {
        return Zotero.Libraries.userLibraryID;
      }
    } catch (_) {}
    try {
      if (Zotero.Libraries.get(numericID)) {
        return numericID;
      }
    } catch (_) {}
    try {
      for (const entry of Zotero.Libraries.getAll?.() || []) {
        const library = typeof entry === "number" ? Zotero.Libraries.get(entry) : entry;
        if (library && Number(library.groupID) === numericID) {
          return library.libraryID;
        }
      }
    } catch (_) {}
    return numericID;
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
          state.chatPanel?.installWindow(window);
      },
      onMainWindowUnload(window) {
        state.chatPanel?.cleanupWindow(window);
        },
      async onShutdown() {
        state.chatPanel?.shutdown();
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

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    __test: {
      convertMarkdownNoteHTML,
      classifyBridgeLifecycle,
      PI_ONLY_LIFECYCLE_PROTOCOL_VERSION,
      TRANSITIONAL_LIFECYCLE_PROTOCOL_VERSION,
      PI_ONLY_PRODUCT_SCOPE,
    },
  };
}

