/**
 * Zotero Agent Bridge companion add-on bootstrap.
 *
 * Compatible with Zotero 7/8 bootstrapped add-ons.
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
  const ADDON_VERSION = "0.1.3";
  const DEFAULT_POLL_INTERVAL_MS = 1000;
  const DEFAULT_STATUS_INTERVAL_MS = 5000;
  const DEFAULT_BRIDGE_HOST = "127.0.0.1";
  const DEFAULT_BRIDGE_PORT = 8765;
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
      menuItems: [],
    };
  }

  async function loadConfig() {
    const defaults = {
      bridgeHome: "",
      bridgeHost: DEFAULT_BRIDGE_HOST,
      bridgePort: DEFAULT_BRIDGE_PORT,
      apiToken: "",
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

  async function bridgeRequest(method, path, payload = null) {
    const token = await readBridgeToken();
    const response = await fetch(`${bridgeBaseURL()}${path}`, {
      method,
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Bridge-Token": token,
      },
      body: payload ? JSON.stringify(payload) : undefined,
    });
    const text = await response.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (error) {
        data = { raw: text };
      }
    }
    if (!response.ok) {
      const error = data && data.error ? data.error : {};
      throw new BridgeError(
        error.code || "bridge_http_error",
        error.message || `Bridge HTTP request failed with status ${response.status}`,
        error.details || data,
      );
    }
    return data;
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
    if (!itemMenu || doc.getElementById("zotero-agent-bridge-sync-obsidian")) {
      return;
    }
    const menuItem = doc.createXULElement ? doc.createXULElement("menuitem") : doc.createElement("menuitem");
    menuItem.id = "zotero-agent-bridge-sync-obsidian";
    menuItem.setAttribute("label", "Sync to Obsidian via Bridge");
    menuItem.addEventListener("command", () => {
      void syncSelectedNoteToObsidian(win);
    });
    itemMenu.appendChild(menuItem);
    state.menuItems.push(menuItem);
  }

  function uninstallMenus() {
    for (const item of state.menuItems || []) {
      try {
        item.remove();
      } catch (error) {}
    }
    state.menuItems = [];
  }

  async function writeStatus(extra = {}) {
    const payload = Object.assign(
      {
        addon_version: state.addonVersion,
        started_at: state.startedAt,
        last_seen: new Date().toISOString(),
        ready: true,
        bridge_home: state.bridgeHome,
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
    if (error instanceof BridgeError) {
      return {
        code: error.code,
        message: error.message,
        details: error.details,
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
    await appendLog("info", "addon_started", {
      addon_version: ADDON_VERSION,
      bridge_home: bridgeHome,
    });
    await writeStatus();
    startTimers();
  }

  async function shutdownAddon() {
    if (!state) {
      return;
    }
    state.shuttingDown = true;
    stopTimers();
    await writeStatus({
      ready: false,
      last_seen: new Date().toISOString(),
    });
    await appendLog("info", "addon_stopped");
  }

  return {
    hooks: {
      async onStartup() {
        await initialize();
      },
      onMainWindowLoad(window) {
        installMenus(window);
      },
      onMainWindowUnload(window) {
        uninstallMenus();
      },
      async onShutdown() {
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

