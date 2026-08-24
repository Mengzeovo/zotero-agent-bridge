var ZoteroAgentBridge = (() => {
  const ADDON_VERSION = "0.3.5";
  const DEFAULT_POLL_INTERVAL_MS = 1000;
  const DEFAULT_STATUS_INTERVAL_MS = 5000;
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
    };
  }

  async function loadConfig() {
    const defaults = {
      bridgeHome: "",
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
      onMainWindowLoad(window) {},
      onMainWindowUnload(window) {},
      async onShutdown() {
        await shutdownAddon();
      },
    },
  };
})();

Zotero.ZoteroAgentBridge = ZoteroAgentBridge;




