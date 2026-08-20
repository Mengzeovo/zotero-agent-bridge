const { Notice, Plugin, PluginSettingTab, Setting, requestUrl } = require("obsidian");
const { spawn } = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");

const DEFAULT_SETTINGS = {
  autoStartBridge: true,
  restartOnExit: true,
  bridgeExecutablePath: "",
  pythonPath: "python",
  bridgeHost: "127.0.0.1",
  bridgePort: 8765,
  bridgeToken: "",
  bridgeHome: "",
  configPath: "",
  baseAttachmentPath: "",
  zoteroLocalApiBase: "http://127.0.0.1:23119/api/users/0",
  obsidianDefaultNoteDir: "Zotero Notes",
  healthIntervalMs: 5000,
  addonTimeoutSeconds: 30,
  addonStatusTtlSeconds: 15,
};

class ZoteroAgentBridgePlugin extends Plugin {
  async onload() {
    await this.loadSettings();
    this.bridgeProcess = null;
    this.stoppingBridge = false;
    this.lastHealth = null;
    this.lastHealthStatusCode = null;
    this.statusText = "stopped";
    this.outputBuffer = "";
    this.errorBuffer = "";

    this.addSettingTab(new ZoteroAgentBridgeSettingTab(this.app, this));

    this.addCommand({
      id: "start-bridge",
      name: "Start bridge service",
      callback: () => this.startBridge(),
    });
    this.addCommand({
      id: "stop-bridge",
      name: "Stop bridge service",
      callback: () => this.stopBridge(),
    });
    this.addCommand({
      id: "restart-bridge",
      name: "Restart bridge service",
      callback: () => this.restartBridge(),
    });
    this.addCommand({
      id: "refresh-bridge-status",
      name: "Refresh bridge status",
      callback: async () => {
        await this.refreshHealth();
        new Notice(`Zotero Agent Bridge: ${this.statusText}`);
      },
    });
    this.addCommand({
      id: "open-bridge-config",
      name: "Open generated bridge config",
      callback: () => this.openRuntimeFile("bridge-config.json"),
    });
    this.addCommand({
      id: "open-bridge-log",
      name: "Open bridge log",
      callback: () => this.openRuntimeFile("bridge.log"),
    });

    this.registerInterval(
      window.setInterval(() => {
        void this.refreshHealth();
      }, Math.max(this.settings.healthIntervalMs, 1000)),
    );

    if (this.settings.autoStartBridge) {
      void this.startBridge();
    }
  }

  async onunload() {
    await this.stopBridge();
  }

  async loadSettings() {
    this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
    if (!this.settings.bridgeToken) {
      this.settings.bridgeToken = crypto.randomBytes(24).toString("hex");
      await this.saveSettings();
    }
  }

  async saveSettings() {
    await this.saveData(this.settings);
  }

  getVaultBasePath() {
    const adapter = this.app.vault.adapter;
    if (!adapter || typeof adapter.getBasePath !== "function") {
      throw new Error("Zotero Agent Bridge can only manage the bridge process on Obsidian Desktop.");
    }
    return adapter.getBasePath();
  }

  pluginRuntimeDir() {
    return path.join(this.getVaultBasePath(), ".obsidian", "plugins", this.manifest.id, "runtime");
  }

  defaultBridgeHome() {
    return path.join(os.homedir(), "Zotero", "zotero-agent-bridge");
  }

  defaultConfigPath() {
    return path.join(this.pluginRuntimeDir(), "bridge-config.json");
  }

  runtimeFilePath(filename) {
    return path.join(this.pluginRuntimeDir(), filename);
  }

  resolveSettings() {
    const vaultPath = this.getVaultBasePath();
    const metadataDir = path.join(vaultPath, ".zotero-agent-bridge", "metadata");
    const notesDir = path.join(vaultPath, ".zotero-agent-bridge", "notes");
    const bridgeHome = this.settings.bridgeHome || this.defaultBridgeHome();
    const configPath = this.settings.configPath || this.defaultConfigPath();
    return {
      vaultPath,
      metadataDir,
      notesDir,
      bridgeHome,
      configPath,
      baseUrl: `http://${this.settings.bridgeHost}:${this.settings.bridgePort}`,
    };
  }

  ensureRuntimeDir() {
    fs.mkdirSync(this.pluginRuntimeDir(), { recursive: true });
  }

  writeBridgeConfig() {
    this.ensureRuntimeDir();
    const resolved = this.resolveSettings();
    const config = {
      host: this.settings.bridgeHost,
      port: Number(this.settings.bridgePort),
      api_token: this.settings.bridgeToken,
      zotero_local_api_base: this.settings.zoteroLocalApiBase,
      bridge_home: resolved.bridgeHome,
      metadata_dir: resolved.metadataDir,
      notes_dir: resolved.notesDir,
      base_attachment_path: this.settings.baseAttachmentPath || null,
      obsidian: {
        vault_name: this.app.vault.getName(),
        vault_path: resolved.vaultPath,
        default_note_dir: this.settings.obsidianDefaultNoteDir || "Zotero Notes",
        index_path: path.join(resolved.metadataDir, "obsidian-index.json"),
        bridge_open_base_url: resolved.baseUrl,
      },
      addon_timeout_seconds: Number(this.settings.addonTimeoutSeconds),
      addon_status_ttl_seconds: Number(this.settings.addonStatusTtlSeconds),
      user_agent: "ZoteroAgentBridgeObsidianPlugin/0.1",
    };
    fs.writeFileSync(resolved.configPath, JSON.stringify(config, null, 2), "utf8");
    return resolved.configPath;
  }

  async startBridge() {
    if (this.bridgeProcess) {
      new Notice("Zotero Agent Bridge is already managed by Obsidian.");
      return;
    }
    const existing = await this.refreshHealth({ silent: true });
    if (existing) {
      this.statusText = "running-external";
      new Notice("Zotero Agent Bridge is already running.");
      return;
    }
    if (this.lastHealthStatusCode) {
      new Notice(`Port ${this.settings.bridgePort} is already responding with HTTP ${this.lastHealthStatusCode}. Check the bridge token or choose another port.`);
      return;
    }

    let configPath;
    try {
      configPath = this.writeBridgeConfig();
    } catch (error) {
      this.statusText = "config-error";
      new Notice(`Bridge config failed: ${error.message || error}`);
      throw error;
    }

    const env = Object.assign({}, process.env, {
      ZOTERO_AGENT_BRIDGE_CONFIG: configPath,
      PYTHONUTF8: "1",
    });
    const command = this.settings.bridgeExecutablePath || this.settings.pythonPath || "python";
    const args = this.settings.bridgeExecutablePath ? [] : ["-m", "zotero_agent_bridge"];

    this.ensureRuntimeDir();
    this.appendLog(`starting: ${command} ${args.join(" ")}\nconfig: ${configPath}\n`);
    this.stoppingBridge = false;
    this.bridgeProcess = spawn(command, args, {
      env,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    this.statusText = "starting";

    this.bridgeProcess.stdout.on("data", (data) => {
      this.appendLog(data.toString());
    });
    this.bridgeProcess.stderr.on("data", (data) => {
      this.appendLog(data.toString());
    });
    this.bridgeProcess.on("error", (error) => {
      this.statusText = "start-error";
      this.bridgeProcess = null;
      this.appendLog(`bridge process error: ${error.message || error}\n`);
      new Notice(`Bridge start failed: ${error.message || error}`);
    });
    this.bridgeProcess.on("exit", (code, signal) => {
      this.appendLog(`bridge exited: code=${code} signal=${signal}\n`);
      this.bridgeProcess = null;
      this.statusText = this.stoppingBridge ? "stopped" : "exited";
      if (!this.stoppingBridge && this.settings.restartOnExit) {
        window.setTimeout(() => {
          void this.startBridge();
        }, 2000);
      }
    });

    window.setTimeout(() => {
      void this.refreshHealth();
    }, 1500);
    new Notice("Zotero Agent Bridge is starting.");
  }

  async stopBridge() {
    this.stoppingBridge = true;
    if (!this.bridgeProcess) {
      this.statusText = this.statusText === "running-external" ? "running-external" : "stopped";
      return;
    }
    const processToStop = this.bridgeProcess;
    this.bridgeProcess = null;
    processToStop.kill();
    this.statusText = "stopping";
    await new Promise((resolve) => window.setTimeout(resolve, 500));
    this.statusText = "stopped";
  }

  async restartBridge() {
    await this.stopBridge();
    this.statusText = "restarting";
    await this.startBridge();
  }

  authHeaders() {
    return {
      "Accept": "application/json",
      "X-Bridge-Token": this.settings.bridgeToken,
    };
  }

  async bridgeRequest(pathname) {
    const resolved = this.resolveSettings();
    return requestUrl({
      url: `${resolved.baseUrl}${pathname}`,
      method: "GET",
      headers: this.authHeaders(),
      throw: false,
    });
  }

  async refreshHealth(options = {}) {
    try {
      const response = await this.bridgeRequest("/health");
      if (response.status >= 200 && response.status < 300) {
        this.lastHealth = response.json;
        this.lastHealthStatusCode = response.status;
        this.statusText = this.bridgeProcess ? "running-managed" : "running-external";
        return true;
      }
      this.lastHealth = null;
      this.lastHealthStatusCode = response.status;
      if (this.bridgeProcess) {
        this.statusText = "starting";
      } else if (response.status === 401) {
        this.statusText = "auth-failed";
      } else {
        this.statusText = "unavailable";
      }
      return false;
    } catch (error) {
      this.lastHealth = null;
      this.lastHealthStatusCode = null;
      if (this.bridgeProcess) {
        this.statusText = "starting";
      } else {
        this.statusText = "stopped";
      }
      if (!options.silent) {
        this.appendLog(`health check failed: ${error.message || error}\n`);
      }
      return false;
    }
  }

  appendLog(text) {
    try {
      this.ensureRuntimeDir();
      fs.appendFileSync(this.runtimeFilePath("bridge.log"), text, "utf8");
    } catch (error) {
      console.error("Zotero Agent Bridge log write failed", error);
    }
  }

  openRuntimeFile(filename) {
    try {
      this.ensureRuntimeDir();
      const filePath = this.runtimeFilePath(filename);
      if (!fs.existsSync(filePath)) {
        fs.writeFileSync(filePath, "", "utf8");
      }
      window.open(`file://${filePath.replace(/\\/g, "/")}`);
    } catch (error) {
      new Notice(`Unable to open ${filename}: ${error.message || error}`);
    }
  }
}

class ZoteroAgentBridgeSettingTab extends PluginSettingTab {
  constructor(app, plugin) {
    super(app, plugin);
    this.plugin = plugin;
  }

  display() {
    const { containerEl } = this;
    containerEl.empty();
    containerEl.createEl("h2", { text: "Zotero Agent Bridge" });

    const status = containerEl.createDiv({ cls: "zab-status" });
    this.addStatusRow(status, "Bridge status", this.plugin.statusText);
    this.addStatusRow(status, "Bridge URL", `http://${this.plugin.settings.bridgeHost}:${this.plugin.settings.bridgePort}`);
    try {
      this.addStatusRow(status, "Runtime directory", this.plugin.pluginRuntimeDir(), "zab-log-path");
    } catch (error) {
      this.addStatusRow(status, "Runtime directory", "Desktop vault required");
    }

    new Setting(containerEl)
      .setName("Start bridge")
      .setDesc("Start, stop, restart, or check the local bridge process.")
      .addButton((button) => button.setButtonText("Start").onClick(() => this.plugin.startBridge()))
      .addButton((button) => button.setButtonText("Stop").onClick(() => this.plugin.stopBridge()))
      .addButton((button) => button.setButtonText("Restart").onClick(() => this.plugin.restartBridge()))
      .addButton((button) =>
        button.setButtonText("Check").onClick(async () => {
          await this.plugin.refreshHealth();
          this.display();
        }),
      );

    new Setting(containerEl)
      .setName("Auto-start bridge")
      .setDesc("Start the bridge when Obsidian loads this plugin.")
      .addToggle((toggle) =>
        toggle.setValue(this.plugin.settings.autoStartBridge).onChange(async (value) => {
          this.plugin.settings.autoStartBridge = value;
          await this.plugin.saveSettings();
        }),
      );

    new Setting(containerEl)
      .setName("Restart on exit")
      .setDesc("Restart the managed bridge process if it exits unexpectedly.")
      .addToggle((toggle) =>
        toggle.setValue(this.plugin.settings.restartOnExit).onChange(async (value) => {
          this.plugin.settings.restartOnExit = value;
          await this.plugin.saveSettings();
        }),
      );

    new Setting(containerEl)
      .setName("Bridge executable path")
      .setDesc("Optional packaged bridge executable. If empty, the plugin starts Python with -m zotero_agent_bridge.")
      .addText((text) =>
        text.setPlaceholder("C:\\path\\to\\zotero-agent-bridge.exe").setValue(this.plugin.settings.bridgeExecutablePath).onChange(async (value) => {
          this.plugin.settings.bridgeExecutablePath = value.trim();
          await this.plugin.saveSettings();
        }),
      );

    new Setting(containerEl)
      .setName("Python executable path")
      .setDesc("Used only when no bridge executable path is configured.")
      .addText((text) =>
        text.setPlaceholder("python").setValue(this.plugin.settings.pythonPath).onChange(async (value) => {
          this.plugin.settings.pythonPath = value.trim() || "python";
          await this.plugin.saveSettings();
        }),
      );

    new Setting(containerEl)
      .setName("Bridge host")
      .addText((text) =>
        text.setValue(this.plugin.settings.bridgeHost).onChange(async (value) => {
          this.plugin.settings.bridgeHost = value.trim() || "127.0.0.1";
          await this.plugin.saveSettings();
        }),
      );

    new Setting(containerEl)
      .setName("Bridge port")
      .addText((text) =>
        text.setValue(String(this.plugin.settings.bridgePort)).onChange(async (value) => {
          const port = Number(value);
          if (Number.isInteger(port) && port > 0 && port < 65536) {
            this.plugin.settings.bridgePort = port;
            await this.plugin.saveSettings();
          }
        }),
      );

    new Setting(containerEl)
      .setName("Bridge token")
      .setDesc("Stored in Obsidian plugin data and written to the generated bridge config.")
      .addText((text) =>
        text.setValue(this.plugin.settings.bridgeToken).onChange(async (value) => {
          this.plugin.settings.bridgeToken = value.trim();
          await this.plugin.saveSettings();
        }),
      )
      .addButton((button) =>
        button.setButtonText("Regenerate").onClick(async () => {
          this.plugin.settings.bridgeToken = crypto.randomBytes(24).toString("hex");
          await this.plugin.saveSettings();
          this.display();
        }),
      );

    new Setting(containerEl)
      .setName("Bridge home")
      .setDesc("Must match the Zotero companion add-on bridgeHome if you override the default.")
      .addText((text) =>
        text.setPlaceholder(this.plugin.defaultBridgeHome()).setValue(this.plugin.settings.bridgeHome).onChange(async (value) => {
          this.plugin.settings.bridgeHome = value.trim();
          await this.plugin.saveSettings();
        }),
      );

    new Setting(containerEl)
      .setName("PDF attachment base path")
      .setDesc("Optional base path for linked PDF attachment imports.")
      .addText((text) =>
        text.setPlaceholder("E:\\papers").setValue(this.plugin.settings.baseAttachmentPath).onChange(async (value) => {
          this.plugin.settings.baseAttachmentPath = value.trim();
          await this.plugin.saveSettings();
        }),
      );

    new Setting(containerEl)
      .setName("Obsidian note directory")
      .setDesc("Vault-relative directory for synced Zotero notes.")
      .addText((text) =>
        text.setPlaceholder("Zotero Notes").setValue(this.plugin.settings.obsidianDefaultNoteDir).onChange(async (value) => {
          this.plugin.settings.obsidianDefaultNoteDir = value.trim() || "Zotero Notes";
          await this.plugin.saveSettings();
        }),
      );

    new Setting(containerEl)
      .setName("Generated files")
      .setDesc("Open the generated bridge config or process log.")
      .addButton((button) => button.setButtonText("Config").onClick(() => this.plugin.openRuntimeFile("bridge-config.json")))
      .addButton((button) => button.setButtonText("Log").onClick(() => this.plugin.openRuntimeFile("bridge.log")));
  }

  addStatusRow(parent, label, value, valueClass) {
    const row = parent.createDiv({ cls: "zab-status-row" });
    row.createSpan({ text: label });
    row.createSpan({ text: value, cls: valueClass || "zab-status-value" });
  }
}

module.exports = ZoteroAgentBridgePlugin;
