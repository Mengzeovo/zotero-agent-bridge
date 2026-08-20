"use strict";

var ZoteroAgentBridgePiChatPanel = (() => {
  const HTML_NS = "http://www.w3.org/1999/xhtml";
  const XUL_NS = "http://www.mozilla.org/keymaster/gatekeeper/there.is.only.xul";
  const PANE_ID = "zotero-agent-bridge-pi-chat";
  const PLUGIN_ID = "zotero-agent-bridge@local";
  const SIDEBAR_CONTEXTS = Object.freeze({
    library: Object.freeze({
      sidenavSelector: "#zotero-view-item-sidenav",
      deckSelector: "#zotero-item-pane-content",
      panelID: `${PANE_ID}-library-pane`,
    }),
    reader: Object.freeze({
      sidenavSelector: "#zotero-context-pane-sidenav",
      deckSelector: "#zotero-context-pane-inner deck",
      panelID: `${PANE_ID}-reader-pane`,
    }),
  });

  const STRINGS = {
    "zh-CN": {
      title: "Pi 文献助手",
      sidenav: "Pi 文献助手",
      noPaper: "请选择带有本地 PDF 的文献",
      ready: "已选择文献，发送问题时启动 Pi",
      opening: "正在打开文献会话…",
      open: "打开会话",
      opened: "会话已就绪",
      contextRequired: "首个问题将加载 PDF 全文、笔记和批注",
      contextUpdated: "文献内容已更新，下个问题将加载最新上下文",
      contextLoaded: "文献上下文已加载",
      model: "模型",
      modelOpenHint: "打开会话后选择模型",
      modelLoading: "正在读取可用模型…",
      modelUnavailable: "没有可用模型",
      modelChanged: "已切换模型：{model}",
      modelFailed: "切换模型失败",
      thinkingLabel: "思考程度",
      thinkingOpenHint: "打开会话后选择思考程度",
      thinkingLoading: "正在读取思考程度…",
      thinkingUnavailable: "当前模型不支持思考程度",
      thinkingChanged: "已切换思考程度：{level}",
      thinkingFailed: "切换思考程度失败",
      thinking: "Pi 正在阅读和回答…",
      stopped: "已停止生成",
      switchPending: "Pi 正在回答。停止或等待完成后再切换文献。",
      inputPlaceholder: "询问研究问题、方法、实验、公式或局限…",
      send: "发送",
      stop: "停止",
      reset: "新会话",
      save: "保存为 Zotero Note",
      savePending: "等待一条完整的 Pi 回答后即可保存",
      saveConfirm: "将当前完整回答保存为这篇文献的 Zotero Note？",
      saveSuccess: "已保存 Zotero Note：{noteKey}",
      saveFailed: "保存 Zotero Note 失败",
      empty: "从当前论文开始提问。回答将优先依据 PDF、笔记和批注。",
      user: "你",
      assistant: "Pi",
      system: "状态",
      resetConfirm: "为当前论文开始一个新会话？旧会话文件会保留，但不会再自动恢复。",
      resetDone: "新会话已就绪",
      bridgeError: "无法连接文献助手",
      noPdf: "当前条目没有可用的本地 PDF",
      pages: "页",
      warning: "上下文有警告",
      retry: "插件会自动安装并启动内置 Bridge；请打开日志查看详细原因后重试。",
      retryStart: "重试启动",
      piMissing: "未检测到 Pi CLI",
      piMissingHelp: "Bridge 已就绪，但 Pi 未安装或路径无效。请安装 Pi，或在迁移后的 Bridge 配置中设置 pi.executable，然后重试。",
    },
    "en-US": {
      title: "Pi Literature Assistant",
      sidenav: "Pi Literature Assistant",
      noPaper: "Select an item with a local PDF",
      ready: "Paper selected. Pi starts when you send a question.",
      opening: "Opening the literature session…",
      open: "Open session",
      opened: "Session ready",
      contextRequired: "Your first question will load the PDF, notes, and annotations",
      contextUpdated: "The paper changed; the next question will load updated context",
      contextLoaded: "Literature context loaded",
      model: "Model",
      modelOpenHint: "Open the session to choose a model",
      modelLoading: "Loading available models…",
      modelUnavailable: "No models available",
      modelChanged: "Model changed: {model}",
      modelFailed: "Could not change model",
      thinkingLabel: "Thinking",
      thinkingOpenHint: "Open the session to choose a thinking level",
      thinkingLoading: "Loading thinking levels…",
      thinkingUnavailable: "This model does not support thinking levels",
      thinkingChanged: "Thinking level changed: {level}",
      thinkingFailed: "Could not change thinking level",
      thinking: "Pi is reading and answering…",
      stopped: "Generation stopped",
      switchPending: "Pi is answering. Stop or wait before switching papers.",
      inputPlaceholder: "Ask about the research question, method, experiments, equations, or limitations…",
      send: "Send",
      stop: "Stop",
      reset: "New session",
      save: "Save as Zotero Note",
      savePending: "A complete Pi answer is required before saving",
      saveConfirm: "Save the current complete answer as a Zotero Note for this paper?",
      saveSuccess: "Saved Zotero Note: {noteKey}",
      saveFailed: "Could not save the Zotero Note",
      empty: "Ask about the current paper. Answers prioritize its PDF, notes, and annotations.",
      user: "You",
      assistant: "Pi",
      system: "Status",
      resetConfirm: "Start a new session for this paper? The old session file will remain, but will no longer resume automatically.",
      resetDone: "New session ready",
      bridgeError: "The literature assistant is unavailable",
      noPdf: "This item has no usable local PDF",
      pages: "pages",
      warning: "Context warning",
      retry: "The add-on installs and starts its bundled Bridge automatically. Check the logs and try again.",
      retryStart: "Retry startup",
      piMissing: "Pi CLI was not found",
      piMissingHelp: "Bridge is ready, but Pi is not installed or its path is invalid. Install Pi or set pi.executable in the migrated Bridge configuration, then retry.",
    },
  };

  function createElement(doc, tag, className, text) {
    const element = doc.createElementNS(HTML_NS, tag);
    if (className) {
      element.className = className;
    }
    if (text !== undefined && text !== null) {
      element.textContent = String(text);
    }
    return element;
  }

  function createDeckContainer(doc, className) {
    const element = typeof doc.createXULElement === "function"
      ? doc.createXULElement("vbox")
      : doc.createElementNS(XUL_NS, "vbox");
    if (className) {
      element.classList.add(className);
    }
    return element;
  }

  function contentText(content) {
    if (typeof content === "string") {
      return content;
    }
    if (!Array.isArray(content)) {
      return "";
    }
    return content
      .filter((block) => block && block.type === "text" && typeof block.text === "string")
      .map((block) => block.text)
      .join("\n");
  }

  function errorMessage(error, strings) {
    const code = error && error.code ? String(error.code) : "";
    const message = error && error.message ? String(error.message) : String(error || strings.bridgeError);
    if (code === "pi_executable_not_found" || code === "pi_executable_unsupported" || code === "pi_start_failed") {
      return `${strings.piMissing}: ${message}\n${strings.piMissingHelp}`;
    }
    return `${message}\n${strings.retry}`;
  }

  function isFinalAssistantMessage(message) {
    if (!message || message.role !== "assistant") {
      return false;
    }
    const text = contentText(message.content).trim();
    return Boolean(text) && message.stopReason === "stop";
  }

  function scopesEqual(left, right) {
    return Boolean(
      left
      && right
      && left.selectionGeneration === right.selectionGeneration
      && left.sessionGeneration === right.sessionGeneration
    );
  }

  function documentsEqual(left, right) {
    return Boolean(
      left
      && right
      && left.itemKey === right.itemKey
      && left.attachmentKey === right.attachmentKey
      && left.contextFingerprint === right.contextFingerprint
      && left.documentId === right.documentId
    );
  }

  function canSaveSnapshot({ sessionOpen, streaming, sending, answer, finalScope, currentScope, finalDocument, currentDocument }) {
    return Boolean(
      sessionOpen
      && !streaming
      && !sending
      && String(answer || "").trim()
      && scopesEqual(finalScope, currentScope)
      && documentsEqual(finalDocument, currentDocument)
    );
  }

  function isPdfAttachment(item) {
    if (!item || !item.isAttachment || !item.isAttachment()) {
      return false;
    }
    const contentType = String(item.attachmentContentType || "").toLowerCase();
    return contentType === "application/pdf";
  }

  class ChatPanel {
    constructor(controller, doc, body) {
      this.controller = controller;
      this.doc = doc;
      this.win = doc.defaultView;
      this.body = body;
      this.strings = controller.strings;
      this.selection = null;
      this.pendingSelection = null;
      this.hasPendingSelection = false;
      this.selectionVersion = 0;
      this.selectionGeneration = 0;
      this.sessionGeneration = 0;
      this.sessionOpen = false;
      this.sessionIdentity = null;
      this.contextInjectionRequired = false;
      this.contextUpdated = false;
      this.streaming = false;
      this.sending = false;
      this.modelLoading = false;
      this.models = [];
      this.currentModelIndex = -1;
      this.thinkingLoading = false;
      this.thinkingLevels = [];
      this.currentThinkingLevel = "";
      this.cursor = 0;
      this.pollIntervalMs = 300;
      this.pollTimer = null;
      this.pollCount = 0;
      this.currentAssistant = null;
      this.currentAssistantText = "";
      this.activeQuestion = null;
      this.lastFinalAnswer = null;
      this.lastFinalQuestion = null;
      this.lastFinalScope = null;
      this.lastFinalDocument = null;
      this.lastErrorMessage = null;
      this.lastErrorContent = null;
      this.disposed = false;
      this._build();
    }

    _build() {
      const doc = this.doc;
      this.root = createElement(doc, "section", "zab-chat");
      this.root.setAttribute("aria-label", this.strings.title);

      const paperRow = createElement(doc, "div", "zab-chat__paper");
      const paperCopy = createElement(doc, "div", "zab-chat__paper-copy");
      this.paperTitle = createElement(doc, "div", "zab-chat__paper-title", this.strings.noPaper);
      this.paperMeta = createElement(doc, "div", "zab-chat__paper-meta", "");
      paperCopy.append(this.paperTitle, this.paperMeta);
      this.openButton = this._button(this.strings.open, "zab-chat__button zab-chat__button--quiet", () => this.openSession());
      paperRow.append(paperCopy, this.openButton);

      const statusRow = createElement(doc, "div", "zab-chat__status");
      this.statusDot = createElement(doc, "span", "zab-chat__status-dot");
      this.statusDot.setAttribute("aria-hidden", "true");
      this.statusText = createElement(doc, "span", "zab-chat__status-text", this.strings.noPaper);
      this.statusText.setAttribute("role", "status");
      statusRow.append(this.statusDot, this.statusText);

      const modelRow = createElement(doc, "label", "zab-chat__model-row");
      const modelLabel = createElement(doc, "span", "zab-chat__model-label", this.strings.model);
      this.modelSelect = createElement(doc, "select", "zab-chat__model-select");
      this.modelSelect.setAttribute("aria-label", this.strings.model);
      this.modelSelect.addEventListener("change", () => void this._changeModel());
      modelRow.append(modelLabel, this.modelSelect);
      this._setModelPlaceholder(this.strings.modelOpenHint);

      const thinkingRow = createElement(doc, "label", "zab-chat__model-row");
      const thinkingLabel = createElement(doc, "span", "zab-chat__model-label", this.strings.thinkingLabel);
      this.thinkingSelect = createElement(doc, "select", "zab-chat__model-select");
      this.thinkingSelect.setAttribute("aria-label", this.strings.thinkingLabel);
      this.thinkingSelect.addEventListener("change", () => void this._changeThinkingLevel());
      thinkingRow.append(thinkingLabel, this.thinkingSelect);
      this._setThinkingPlaceholder(this.strings.thinkingOpenHint);

      this.transcript = createElement(doc, "div", "zab-chat__transcript");
      this.transcript.setAttribute("role", "log");
      this.transcript.setAttribute("aria-live", "polite");
      this.emptyState = createElement(doc, "p", "zab-chat__empty", this.strings.empty);
      this.transcript.append(this.emptyState);

      this.input = createElement(doc, "textarea", "zab-chat__input");
      this.input.rows = 3;
      this.input.placeholder = this.strings.inputPlaceholder;
      this.input.setAttribute("aria-label", this.strings.inputPlaceholder);
      this.input.addEventListener("input", () => this._updateControls());
      this.input.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
          event.preventDefault();
          void this.send();
        }
      });

      const actionRow = createElement(doc, "div", "zab-chat__actions");
      const primaryActions = createElement(doc, "div", "zab-chat__actions-primary");
      this.sendButton = this._button(this.strings.send, "zab-chat__button zab-chat__button--primary", () => this.send());
      this.stopButton = this._button(this.strings.stop, "zab-chat__button zab-chat__button--danger", () => this.stop());
      primaryActions.append(this.sendButton, this.stopButton);
      const secondaryActions = createElement(doc, "div", "zab-chat__actions-secondary");
      this.resetButton = this._button(this.strings.reset, "zab-chat__button zab-chat__button--quiet", () => this.reset());
      this.saveButton = this._button(this.strings.save, "zab-chat__button zab-chat__button--quiet", () => this.save());
      this.saveButton.disabled = true;
      this.saveButton.title = this.strings.savePending;
      secondaryActions.append(this.resetButton, this.saveButton);
      actionRow.append(primaryActions, secondaryActions);

      this.root.append(paperRow, statusRow, this.transcript, modelRow, thinkingRow, this.input, actionRow);
      this.body.replaceChildren(this.root);
      this._setStatus("idle", this.strings.noPaper);
      this._updateControls();
    }

    _button(label, className, handler) {
      const button = createElement(this.doc, "button", className, label);
      button.type = "button";
      button.addEventListener("click", () => void handler());
      return button;
    }

    _setStatus(kind, text) {
      this.root.dataset.status = kind;
      this.statusText.textContent = text;
    }

    _setModelPlaceholder(text) {
      const option = createElement(this.doc, "option", "", text);
      option.value = "";
      this.modelSelect.replaceChildren(option);
      this.modelSelect.value = "";
    }

    _setThinkingPlaceholder(text) {
      const option = createElement(this.doc, "option", "", text);
      option.value = "";
      this.thinkingSelect.replaceChildren(option);
      this.thinkingSelect.value = "";
    }

    _updateControls() {
      const hasSelection = Boolean(this.selection);
      const busy = this.sending || this.streaming;
      this.input.disabled = !hasSelection || busy;
      this.sendButton.disabled = !hasSelection || busy || !this.input.value.trim();
      this.stopButton.disabled = !this.streaming;
      this.openButton.disabled = !hasSelection || busy || this.sessionOpen;
      this.resetButton.disabled = !this.sessionOpen || busy;
      this.modelSelect.disabled = !this.sessionOpen || busy || this.modelLoading || !this.models.length;
      this.thinkingSelect.disabled = !this.sessionOpen || busy || this.thinkingLoading || !this.thinkingLevels.length;
      const canSave = canSaveSnapshot({
        sessionOpen: this.sessionOpen,
        streaming: this.streaming,
        sending: this.sending,
        answer: this.lastFinalAnswer,
        finalScope: this.lastFinalScope,
        currentScope: this._captureScope(),
        finalDocument: this.lastFinalDocument,
        currentDocument: this.sessionIdentity,
      });
      this.saveButton.disabled = !canSave;
      this.saveButton.title = canSave ? "" : this.strings.savePending;
    }

    async setItem(item) {
      const version = ++this.selectionVersion;
      let selection = null;
      try {
        selection = await this._resolveSelection(item);
      } catch (error) {
        this.controller.log("error", "pi_chat_selection_failed", error);
      }
      if (this.disposed || version !== this.selectionVersion) {
        return;
      }
      const currentIdentity = this.selection ? this.selection.identity : null;
      const nextIdentity = selection ? selection.identity : null;
      if (currentIdentity === nextIdentity) {
        if (selection) {
          this.selection = selection;
          this.paperTitle.textContent = selection.title;
        }
        return;
      }
      if (this.streaming || this.sending) {
        this.pendingSelection = selection;
        this.hasPendingSelection = true;
        this._setStatus("warning", this.strings.switchPending);
        return;
      }
      this._applySelection(selection);
    }

    async _resolveSelection(item) {
      if (!item) {
        return null;
      }
      let parent = item;
      let attachment = null;
      if (isPdfAttachment(item)) {
        if (await this._localPdfPath(item)) {
          attachment = item;
        }
        parent = item.parentID ? this.controller.Zotero.Items.get(item.parentID) : null;
      } else if (item.isRegularItem && item.isRegularItem()) {
        const ids = typeof item.getAttachments === "function" ? item.getAttachments() : [];
        const values = ids.length ? this.controller.Zotero.Items.get(ids) : [];
        const attachments = (Array.isArray(values) ? values : [values])
          .filter(isPdfAttachment)
          .sort((left, right) => String(left.key).localeCompare(String(right.key)));
        for (const candidate of attachments) {
          if (await this._localPdfPath(candidate)) {
            attachment = candidate;
            break;
          }
        }
      } else {
        return null;
      }
      if (!parent || !attachment || !parent.key || !attachment.key) {
        return null;
      }
      const title = String(parent.getField ? parent.getField("title") : "").trim() || String(parent.key);
      return {
        itemKey: String(parent.key),
        attachmentKey: String(attachment.key),
        title,
        identity: `${parent.libraryID || ""}:${parent.key}:${attachment.key}`,
      };
    }

    async _localPdfPath(attachment) {
      if (!attachment || typeof attachment.getFilePathAsync !== "function") {
        return null;
      }
      try {
        const path = String(await attachment.getFilePathAsync() || "").trim();
        if (!path || !path.toLowerCase().endsWith(".pdf")) {
          return null;
        }
        return await this.controller.fileExists(path) ? path : null;
      } catch (error) {
        return null;
      }
    }

    _captureScope() {
      return {
        selectionGeneration: this.selectionGeneration,
        sessionGeneration: this.sessionGeneration,
      };
    }

    _scopeMatches(scope) {
      return Boolean(
        scope
        && !this.disposed
        && scope.selectionGeneration === this.selectionGeneration
        && scope.sessionGeneration === this.sessionGeneration
      );
    }

    _applySelection(selection) {
      this.selectionGeneration += 1;
      this.sessionGeneration += 1;
      this.pendingSelection = null;
      this.hasPendingSelection = false;
      this.selection = selection;
      this.sessionOpen = false;
      this.sessionIdentity = null;
      this.contextInjectionRequired = false;
      this.contextUpdated = false;
      this.streaming = false;
      this.sending = false;
      this.modelLoading = false;
      this.models = [];
      this.currentModelIndex = -1;
      this.thinkingLoading = false;
      this.thinkingLevels = [];
      this.currentThinkingLevel = "";
      this._setModelPlaceholder(this.strings.modelOpenHint);
      this._setThinkingPlaceholder(this.strings.thinkingOpenHint);
      this.cursor = 0;
      this.currentAssistant = null;
      this.activeQuestion = null;
      this.lastFinalAnswer = null;
      this.lastFinalQuestion = null;
      this.lastFinalScope = null;
      this.lastFinalDocument = null;
      this.lastErrorMessage = null;
      this.lastErrorContent = null;
      this.openButton.textContent = this.strings.open;
      this._cancelPoll();
      this._clearTranscript();
      if (!selection) {
        this.paperTitle.textContent = this.strings.noPaper;
        this.paperMeta.textContent = "";
        this._setStatus("idle", this.strings.noPdf);
      } else {
        this.paperTitle.textContent = selection.title;
        this.paperMeta.textContent = selection.attachmentKey;
        this._setStatus("ready", this.strings.ready);
      }
      this._updateControls();
    }

    _clearTranscript() {
      if (this.currentAssistant && this.currentAssistant._zabRenderFrame) {
        this.win.cancelAnimationFrame(this.currentAssistant._zabRenderFrame);
      }
      this.transcript.replaceChildren(this.emptyState);
      this.emptyState.hidden = false;
      this.currentAssistant = null;
      this.currentAssistantText = "";
      this.lastErrorMessage = null;
      this.lastErrorContent = null;
    }

    _renderMessage(role, content, text) {
      const value = String(text || "");
      if (role === "assistant" && this.controller.markdownRenderer) {
        this.controller.markdownRenderer.render(content, value);
      } else {
        content.textContent = value;
      }
    }

    _scheduleAssistantRender(content) {
      if (!content || content._zabRenderFrame) {
        return;
      }
      content._zabRenderFrame = this.win.requestAnimationFrame(() => {
        content._zabRenderFrame = null;
        if (!this.disposed && content.isConnected) {
          this._renderMessage("assistant", content, this.currentAssistantText);
          this.transcript.scrollTop = this.transcript.scrollHeight;
        }
      });
    }

    _addMessage(role, text) {
      if (!text && role !== "assistant") {
        return null;
      }
      this.emptyState.hidden = true;
      const article = createElement(this.doc, "article", `zab-chat__message zab-chat__message--${role}`);
      const label = createElement(
        this.doc,
        "div",
        "zab-chat__message-label",
        role === "user" ? this.strings.user : role === "assistant" ? this.strings.assistant : this.strings.system,
      );
      const content = createElement(this.doc, "div", "zab-chat__message-content");
      this._renderMessage(role, content, text);
      article.append(label, content);
      this.transcript.append(article);
      this.transcript.scrollTop = this.transcript.scrollHeight;
      return content;
    }

    _showError(error) {
      const message = errorMessage(error, this.strings);
      if (this.lastErrorMessage !== message || !this.lastErrorContent || !this.lastErrorContent.isConnected) {
        this.lastErrorContent = this._addMessage("system", message);
        this.lastErrorMessage = message;
      }
      this.openButton.textContent = this.strings.retryStart;
      this._setStatus("error", error && error.message ? error.message : this.strings.bridgeError);
    }

    async openSession() {
      if (!this.selection || this.disposed) {
        return false;
      }
      if (this.sessionOpen) {
        return true;
      }
      const selection = this.selection;
      this.openButton.textContent = this.strings.open;
      this.sessionGeneration += 1;
      const scope = this._captureScope();
      this.sending = true;
      this._setStatus("working", this.strings.opening);
      this._updateControls();
      try {
        const response = await this.controller.bridgeRequest("POST", "/assistant/session/open", {
          item_key: selection.itemKey,
          attachment_key: selection.attachmentKey,
        });
        if (!this._scopeMatches(scope)) {
          return false;
        }
        const context = response.context || {};
        const documentId = String(response.session && response.session.document_id || "").trim();
        const contextFingerprint = String(context.fingerprint || "").trim().toLowerCase();
        if (!documentId || !contextFingerprint) {
          throw new Error(this.strings.bridgeError);
        }
        this.sessionOpen = true;
        this.sessionIdentity = {
          itemKey: selection.itemKey,
          attachmentKey: selection.attachmentKey,
          contextFingerprint,
          documentId: documentId.toLowerCase(),
        };
        this.contextInjectionRequired = Boolean(response.context_injection_required);
        this.contextUpdated = Boolean(response.context_updated);
        this.cursor = Number(response.session && response.session.last_cursor) || 0;
        this.pollIntervalMs = Math.max(100, Number(response.poll_interval_ms) || 300);
        const pageText = context.page_count ? `${context.page_count} ${this.strings.pages}` : "";
        const warningText = context.warnings && context.warnings.length ? this.strings.warning : "";
        this.paperMeta.textContent = [selection.attachmentKey, pageText, warningText].filter(Boolean).join(" · ");
        await this._loadMessages(scope);
        if (!this._scopeMatches(scope)) {
          return false;
        }
        await this._loadModels(scope);
        if (!this._scopeMatches(scope)) {
          return false;
        }
        await this._loadThinkingLevels(scope);
        if (!this._scopeMatches(scope)) {
          return false;
        }
        this._setStatus(
          this.contextUpdated ? "warning" : "ready",
          this.contextUpdated
            ? this.strings.contextUpdated
            : this.contextInjectionRequired
              ? this.strings.contextRequired
              : this.strings.opened,
        );
        return !this.hasPendingSelection;
      } catch (error) {
        if (this._scopeMatches(scope)) {
          this.sessionOpen = false;
          this._showError(error);
        }
        return false;
      } finally {
        if (this._scopeMatches(scope)) {
          this.sending = false;
          this._updateControls();
          if (!this.streaming) {
            await this._applyPendingSelection();
          }
        }
      }
    }

    async _loadModels(scope = this._captureScope()) {
      if (!this.sessionOpen || !this._scopeMatches(scope)) {
        return false;
      }
      this.modelLoading = true;
      this._setModelPlaceholder(this.strings.modelLoading);
      this._updateControls();
      try {
        const response = await this.controller.bridgeRequest("GET", "/assistant/models");
        if (!this._scopeMatches(scope)) {
          return false;
        }
        const models = Array.isArray(response.models) ? response.models.filter((model) => (
          model && typeof model.provider === "string" && typeof model.id === "string"
        )) : [];
        this.models = models;
        this.modelSelect.replaceChildren();
        for (let index = 0; index < models.length; index += 1) {
          const model = models[index];
          const label = model.name && model.name !== model.id
            ? `${model.provider}/${model.id} — ${model.name}`
            : `${model.provider}/${model.id}`;
          const option = createElement(this.doc, "option", "", label);
          option.value = String(index);
          this.modelSelect.append(option);
        }
        const current = response.current_model || null;
        this.currentModelIndex = models.findIndex((model) => (
          current && model.provider === current.provider && model.id === current.id
        ));
        if (!models.length) {
          this.currentModelIndex = -1;
          this._setModelPlaceholder(this.strings.modelUnavailable);
        } else {
          this.currentModelIndex = this.currentModelIndex >= 0 ? this.currentModelIndex : 0;
          this.modelSelect.value = String(this.currentModelIndex);
        }
        return true;
      } catch (error) {
        if (this._scopeMatches(scope)) {
          this.models = [];
          this.currentModelIndex = -1;
          this._setModelPlaceholder(this.strings.modelUnavailable);
          this.controller.log("warning", "pi_chat_models_failed", error);
        }
        return false;
      } finally {
        if (this._scopeMatches(scope)) {
          this.modelLoading = false;
          this._updateControls();
        }
      }
    }

    async _changeModel() {
      const nextIndex = Number(this.modelSelect.value);
      if (!this.sessionOpen || this.sending || this.streaming || !Number.isInteger(nextIndex)) {
        return;
      }
      const model = this.models[nextIndex];
      if (!model || nextIndex === this.currentModelIndex) {
        return;
      }
      const previousIndex = this.currentModelIndex;
      const scope = this._captureScope();
      this.sending = true;
      this._updateControls();
      try {
        const response = await this.controller.bridgeRequest("POST", "/assistant/session/model", {
          provider: model.provider,
          model_id: model.id,
        });
        if (!this._scopeMatches(scope)) {
          return;
        }
        const current = response.current_model || model;
        const selectedIndex = this.models.findIndex((candidate) => (
          candidate.provider === current.provider && candidate.id === current.id
        ));
        this.currentModelIndex = selectedIndex >= 0 ? selectedIndex : nextIndex;
        this.modelSelect.value = String(this.currentModelIndex);
        this._setStatus(
          "ready",
          this.strings.modelChanged.replace("{model}", `${model.provider}/${model.id}`),
        );
        await this._loadThinkingLevels(scope);
      } catch (error) {
        if (this._scopeMatches(scope)) {
          this.currentModelIndex = previousIndex;
          this.modelSelect.value = previousIndex >= 0 ? String(previousIndex) : "";
          this._setStatus("error", `${this.strings.modelFailed}: ${error && error.message ? error.message : error}`);
        }
      } finally {
        if (this._scopeMatches(scope)) {
          this.sending = false;
          this._updateControls();
        }
      }
    }

    async _loadThinkingLevels(scope = this._captureScope()) {
      if (!this.sessionOpen || !this._scopeMatches(scope)) {
        return false;
      }
      this.thinkingLoading = true;
      this._setThinkingPlaceholder(this.strings.thinkingLoading);
      this._updateControls();
      try {
        const response = await this.controller.bridgeRequest("GET", "/assistant/thinking-levels");
        if (!this._scopeMatches(scope)) {
          return false;
        }
        const levels = Array.isArray(response.levels)
          ? response.levels.filter((level) => typeof level === "string" && level.trim())
          : [];
        const usable = levels.filter((level) => level !== "off");
        this.thinkingLevels = levels;
        this.thinkingSelect.replaceChildren();
        for (const level of levels) {
          const option = createElement(this.doc, "option", "", level);
          option.value = level;
          this.thinkingSelect.append(option);
        }
        if (!levels.length || !usable.length) {
          this.thinkingLevels = [];
          this.currentThinkingLevel = "";
          this._setThinkingPlaceholder(this.strings.thinkingUnavailable);
        } else {
          const current = typeof response.current_level === "string" ? response.current_level : "";
          this.currentThinkingLevel = levels.includes(current) ? current : (levels.includes("medium") ? "medium" : levels[0]);
          this.thinkingSelect.value = this.currentThinkingLevel;
        }
        return true;
      } catch (error) {
        if (this._scopeMatches(scope)) {
          this.thinkingLevels = [];
          this.currentThinkingLevel = "";
          this._setThinkingPlaceholder(this.strings.thinkingUnavailable);
          this.controller.log("warning", "pi_chat_thinking_levels_failed", error);
        }
        return false;
      } finally {
        if (this._scopeMatches(scope)) {
          this.thinkingLoading = false;
          this._updateControls();
        }
      }
    }

    async _changeThinkingLevel() {
      const nextLevel = this.thinkingSelect.value;
      if (!this.sessionOpen || this.sending || this.streaming || !nextLevel) {
        return;
      }
      if (!this.thinkingLevels.includes(nextLevel) || nextLevel === this.currentThinkingLevel) {
        return;
      }
      const previousLevel = this.currentThinkingLevel;
      const scope = this._captureScope();
      this.sending = true;
      this._updateControls();
      try {
        const response = await this.controller.bridgeRequest("POST", "/assistant/session/thinking-level", {
          level: nextLevel,
        });
        if (!this._scopeMatches(scope)) {
          return;
        }
        const current = typeof response.current_level === "string" && this.thinkingLevels.includes(response.current_level)
          ? response.current_level
          : nextLevel;
        this.currentThinkingLevel = current;
        this.thinkingSelect.value = current;
        this._setStatus("ready", this.strings.thinkingChanged.replace("{level}", current));
      } catch (error) {
        if (this._scopeMatches(scope)) {
          this.currentThinkingLevel = previousLevel;
          this.thinkingSelect.value = previousLevel || "";
          this._setStatus("error", `${this.strings.thinkingFailed}: ${error && error.message ? error.message : error}`);
        }
      } finally {
        if (this._scopeMatches(scope)) {
          this.sending = false;
          this._updateControls();
        }
      }
    }

    async _loadMessages(scope = this._captureScope()) {
      if (!this.sessionOpen || !this._scopeMatches(scope)) {
        return false;
      }
      const response = await this.controller.bridgeRequest("GET", "/assistant/session/messages");
      if (!this._scopeMatches(scope)) {
        return false;
      }
      const messages = response && response.data && Array.isArray(response.data.messages)
        ? response.data.messages
        : [];
      this._clearTranscript();
      let associatedQuestion = null;
      let finalAnswer = null;
      let finalQuestion = null;
      for (const message of messages) {
        if (message.role !== "user" && message.role !== "assistant") {
          continue;
        }
        const text = contentText(message.content);
        if (text) {
          this._addMessage(message.role, text);
        }
        if (message.role === "user") {
          associatedQuestion = text.trim() || null;
          finalAnswer = null;
          finalQuestion = null;
        } else if (isFinalAssistantMessage(message)) {
          finalAnswer = text.trim();
          finalQuestion = associatedQuestion;
          associatedQuestion = null;
        }
      }
      this.lastFinalAnswer = finalAnswer;
      this.lastFinalQuestion = finalQuestion;
      this.lastFinalScope = finalAnswer ? { ...scope } : null;
      this.lastFinalDocument = finalAnswer && this.sessionIdentity ? { ...this.sessionIdentity } : null;
      this._updateControls();
      return true;
    }

    async send() {
      const message = this.input.value.trim();
      if (!message || !this.selection || this.sending || this.streaming || this.disposed) {
        return;
      }
      this.sending = true;
      this._updateControls();
      let scope = null;
      try {
        if (!(await this.openSession())) {
          return;
        }
        scope = this._captureScope();
        this.sending = true;
        this._updateControls();
        this._addMessage("user", message);
        this.input.value = "";
        this.currentAssistant = null;
        this.activeQuestion = message;
        this.lastFinalAnswer = null;
        this.lastFinalQuestion = null;
        this.lastFinalScope = null;
        this.lastFinalDocument = null;
        const accepted = await this.controller.bridgeRequest("POST", "/assistant/session/message", { message });
        if (!this._scopeMatches(scope)) {
          return;
        }
        if (accepted && accepted.context_injected) {
          this.contextInjectionRequired = false;
          this.contextUpdated = false;
        }
        this.streaming = true;
        this._setStatus("working", this.strings.thinking);
        this._beginPoll(scope);
      } catch (error) {
        if (!this.disposed && (!scope || this._scopeMatches(scope))) {
          this.streaming = false;
          this.activeQuestion = null;
          this._showError(error);
        }
      } finally {
        if (!this.disposed && (!scope || this._scopeMatches(scope))) {
          this.sending = false;
          this._updateControls();
          if (!this.streaming) {
            await this._applyPendingSelection();
          }
        }
      }
    }

    _beginPoll(scope) {
      this._cancelPoll();
      this._schedulePoll(0, scope);
    }

    _schedulePoll(delay, scope) {
      if (!this.streaming || !this._scopeMatches(scope)) {
        return;
      }
      this.pollTimer = this.win.setTimeout(() => void this._poll(scope), delay);
    }

    async _poll(scope) {
      this.pollTimer = null;
      if (!this.streaming || !this._scopeMatches(scope)) {
        return;
      }
      try {
        const response = await this.controller.bridgeRequest(
          "GET",
          `/assistant/session/events?after=${encodeURIComponent(this.cursor)}`,
        );
        if (!this._scopeMatches(scope)) {
          return;
        }
        this.cursor = Number(response.last_cursor) || this.cursor;
        if (response.cursor_expired) {
          await this._loadMessages(scope);
          if (!this._scopeMatches(scope)) {
            return;
          }
          this.currentAssistant = null;
        }
        let settled = false;
        for (const event of response.events || []) {
          if (event.type === "message_update") {
            const update = event.assistantMessageEvent || {};
            if (update.type === "text_delta" && typeof update.delta === "string") {
              if (!this.currentAssistant) {
                this.currentAssistantText = "";
                this.currentAssistant = this._addMessage("assistant", "");
              }
              this.currentAssistantText += update.delta;
              this._scheduleAssistantRender(this.currentAssistant);
            }
          } else if (event.type === "agent_settled") {
            settled = true;
          } else if (event.type === "bridge_pi_error") {
            throw new Error(event.error && event.error.message ? event.error.message : this.strings.bridgeError);
          }
        }
        this.pollCount += 1;
        if (!settled && this.pollCount % 5 === 0) {
          const status = await this.controller.bridgeRequest("GET", "/assistant/session/status");
          if (!this._scopeMatches(scope)) {
            return;
          }
          if (!status.session || !status.session.streaming) {
            settled = true;
          }
        }
        if (settled) {
          this.streaming = false;
          this.currentAssistant = null;
          this.activeQuestion = null;
          await this._loadMessages(scope);
          if (!this._scopeMatches(scope)) {
            return;
          }
          this._setStatus("ready", this.strings.opened);
          this._updateControls();
          await this._applyPendingSelection();
          return;
        }
        this._schedulePoll(Math.max(100, Number(response.poll_interval_ms) || this.pollIntervalMs), scope);
      } catch (error) {
        if (!this._scopeMatches(scope)) {
          return;
        }
        this.streaming = false;
        this.currentAssistant = null;
        this.activeQuestion = null;
        this._cancelPoll();
        this._showError(error);
        this._updateControls();
        await this._applyPendingSelection();
      }
    }

    async stop() {
      if (!this.streaming || this.disposed) {
        return;
      }
      const scope = this._captureScope();
      this.stopButton.disabled = true;
      try {
        await this.controller.bridgeRequest("POST", "/assistant/session/abort");
        if (!this._scopeMatches(scope)) {
          return;
        }
        this.streaming = false;
        this.currentAssistant = null;
        this.activeQuestion = null;
        this._cancelPoll();
        await this._loadMessages(scope);
        if (!this._scopeMatches(scope)) {
          return;
        }
        this._setStatus("ready", this.strings.stopped);
        await this._applyPendingSelection();
      } catch (error) {
        if (this._scopeMatches(scope)) {
          this._showError(error);
        }
      } finally {
        if (this._scopeMatches(scope)) {
          this._updateControls();
        }
      }
    }

    async save() {
      const scope = this._captureScope();
      const answer = this.lastFinalAnswer ? this.lastFinalAnswer.trim() : "";
      const question = this.lastFinalQuestion ? this.lastFinalQuestion.trim() : null;
      const document = this.lastFinalDocument ? { ...this.lastFinalDocument } : null;
      if (
        !canSaveSnapshot({
          sessionOpen: this.sessionOpen,
          streaming: this.streaming,
          sending: this.sending,
          answer,
          finalScope: this.lastFinalScope,
          currentScope: scope,
          finalDocument: document,
          currentDocument: this.sessionIdentity,
        })
        || !this._scopeMatches(scope)
      ) {
        return;
      }
      if (!this.win.confirm(this.strings.saveConfirm)) {
        return;
      }
      if (
        !this._scopeMatches(scope)
        || this.streaming
        || this.sending
        || answer !== this.lastFinalAnswer
        || question !== this.lastFinalQuestion
        || !documentsEqual(document, this.sessionIdentity)
      ) {
        return;
      }
      this.sending = true;
      this._updateControls();
      try {
        const response = await this.controller.bridgeRequest("POST", "/assistant/session/save-note", {
          item_key: document.itemKey,
          attachment_key: document.attachmentKey,
          context_fingerprint: document.contextFingerprint,
          document_id: document.documentId,
          answer,
          question,
        });
        if (!this._scopeMatches(scope)) {
          return;
        }
        const noteKey = response && response.note_key ? String(response.note_key) : "";
        const success = this.strings.saveSuccess.replace("{noteKey}", noteKey || "—");
        this._addMessage("system", success);
        this._setStatus("ready", success);
      } catch (error) {
        if (this._scopeMatches(scope)) {
          const detail = error && error.message ? error.message : String(error);
          this._addMessage("system", `${this.strings.saveFailed}: ${detail}\n${this.strings.retry}`);
          this._setStatus("error", this.strings.saveFailed);
        }
      } finally {
        if (this._scopeMatches(scope)) {
          this.sending = false;
          this._updateControls();
        }
        if (!this.disposed && !this.streaming) {
          await this._applyPendingSelection();
        }
      }
    }

    async reset() {
      if (!this.sessionOpen || this.streaming || this.disposed) {
        return;
      }
      if (!this.win.confirm(this.strings.resetConfirm)) {
        return;
      }
      this.sessionGeneration += 1;
      const scope = this._captureScope();
      this.sending = true;
      this._setStatus("working", this.strings.opening);
      this._updateControls();
      try {
        const response = await this.controller.bridgeRequest("POST", "/assistant/session/reset");
        if (!this._scopeMatches(scope)) {
          return;
        }
        this.cursor = Number(response.session && response.session.last_cursor) || 0;
        this.pollIntervalMs = Math.max(100, Number(response.poll_interval_ms) || this.pollIntervalMs);
        this.sessionOpen = true;
        const resetContext = response.context || {};
        this.sessionIdentity = {
          itemKey: this.selection.itemKey,
          attachmentKey: this.selection.attachmentKey,
          contextFingerprint: String(resetContext.fingerprint || "").toLowerCase(),
          documentId: String(response.session && response.session.document_id || "").toLowerCase(),
        };
        this.contextInjectionRequired = Boolean(response.context_injection_required);
        this.contextUpdated = Boolean(response.context_updated);
        this.activeQuestion = null;
        this.lastFinalAnswer = null;
        this.lastFinalQuestion = null;
        this.lastFinalScope = null;
        this.lastFinalDocument = null;
        this._clearTranscript();
        await this._loadModels(scope);
        if (!this._scopeMatches(scope)) {
          return;
        }
        await this._loadThinkingLevels(scope);
        if (!this._scopeMatches(scope)) {
          return;
        }
        this._setStatus("ready", this.contextInjectionRequired ? this.strings.contextRequired : this.strings.resetDone);
      } catch (error) {
        if (this._scopeMatches(scope)) {
          this._showError(error);
        }
      } finally {
        if (this._scopeMatches(scope)) {
          this.sending = false;
          this._updateControls();
        }
      }
    }

    async _applyPendingSelection() {
      if (!this.hasPendingSelection || this.streaming) {
        return;
      }
      const selection = this.pendingSelection;
      this.pendingSelection = null;
      this.hasPendingSelection = false;
      this._applySelection(selection);
    }

    _cancelPoll() {
      if (this.pollTimer !== null) {
        this.win.clearTimeout(this.pollTimer);
        this.pollTimer = null;
      }
      this.pollCount = 0;
    }

    dispose() {
      if (this.disposed) {
        return;
      }
      this.disposed = true;
      this.selectionVersion += 1;
      this.selectionGeneration += 1;
      this.sessionGeneration += 1;
      this._cancelPoll();
      if (this.currentAssistant && this.currentAssistant._zabRenderFrame) {
        this.win.cancelAnimationFrame(this.currentAssistant._zabRenderFrame);
      }
      this.root.remove();
    }
  }

  class Controller {
    constructor(options) {
      this.Zotero = options.Zotero;
      this.rootURI = options.rootURI;
      this.bridgeRequest = options.bridgeRequest;
      this.appendLog = options.appendLog;
      this.markdownRenderer = options.markdownRenderer || null;
      this.fileExists = typeof options.fileExists === "function" ? options.fileExists : async () => false;
      this.locale = String(options.locale || "en-US");
      this.localeName = this.locale.toLowerCase().startsWith("zh") ? "zh-CN" : "en-US";
      this.strings = STRINGS[this.localeName];
      this.sectionID = null;
      this.panels = new Map();
      this.windowResources = new Map();
      this.windowClickHandlers = new Map();
      this.windowTransitions = new Map();
      this.deckPanels = new Map();
    }

    log(level, message, error) {
      const details = error
        ? { message: error.message || String(error), code: error.code || null }
        : null;
      void this.appendLog(level, message, details);
    }

    installWindow(win) {
      if (!win || !win.document) {
        return;
      }
      const doc = win.document;
      if (!this.windowResources.has(win)) {
        const resources = [];
        if (win.MozXULElement && typeof win.MozXULElement.insertFTLIfNeeded === "function") {
          win.MozXULElement.insertFTLIfNeeded("zotero-agent-bridge.ftl");
        } else {
          const localization = doc.createElementNS(HTML_NS, "link");
          localization.rel = "localization";
          localization.href = `${this.rootURI}locale/${this.localeName}/zotero-agent-bridge.ftl`;
          localization.dataset.zabPiChatResource = "localization";
          doc.documentElement.append(localization);
          resources.push(localization);
        }
        for (const href of [
          `${this.rootURI}chrome/content/vendor/katex/katex.min.css`,
          `${this.rootURI}chrome/content/styles/pi_chat_panel.css`,
        ]) {
          const stylesheet = doc.createElementNS(HTML_NS, "link");
          stylesheet.rel = "stylesheet";
          stylesheet.href = href;
          stylesheet.dataset.zabPiChatResource = "stylesheet";
          doc.documentElement.append(stylesheet);
          resources.push(stylesheet);
        }
        this.windowResources.set(win, resources);
      }
      this._installWindowClickHandler(win);
      this.registerSection();
    }

    _installWindowClickHandler(win) {
      if (this.windowClickHandlers.has(win)) {
        return;
      }
      const handler = (event) => {
        const path = typeof event.composedPath === "function" ? event.composedPath() : [];
        const button = path.find((node) => node && typeof node.getAttribute === "function" && node.getAttribute("data-pane"))
          || (event.target && typeof event.target.closest === "function"
            ? event.target.closest("toolbarbutton[data-pane], [data-pane]")
            : null);
        if (!button) {
          return;
        }
        const contextKey = Object.keys(SIDEBAR_CONTEXTS).find((key) => {
          const selector = SIDEBAR_CONTEXTS[key].sidenavSelector;
          return path.some((node) => node && typeof node.matches === "function" && node.matches(selector))
            || (typeof button.closest === "function" && button.closest(selector));
        });
        if (!contextKey) {
          return;
        }
        const paneID = String(button.getAttribute("data-pane") || (button.dataset && button.dataset.pane) || "");
        if (!paneID) {
          return;
        }
        this._scheduleDeckTransition(win, contextKey, paneID);
      };
      for (const eventName of ["click", "command"]) {
        win.document.addEventListener(eventName, handler, true);
      }
      this.windowClickHandlers.set(win, handler);
    }

    _scheduleDeckTransition(win, contextKey, paneID) {
      let transitions = this.windowTransitions.get(win);
      if (!transitions) {
        transitions = new Map();
        this.windowTransitions.set(win, transitions);
      }
      const existing = transitions.get(contextKey);
      if (existing && existing.paneID === paneID) {
        return;
      }
      if (existing) {
        win.clearTimeout(existing.timer);
      }
      const timer = win.setTimeout(() => {
        transitions.delete(contextKey);
        if (!transitions.size) {
          this.windowTransitions.delete(win);
        }
        if (this._isPiPaneID(paneID)) {
          this.showDeckPanel(win, contextKey);
        } else {
          this.hideDeckPanel(win, contextKey);
        }
      }, 0);
      transitions.set(contextKey, { paneID, timer });
    }

    _clearWindowTransitions(win) {
      const transitions = this.windowTransitions.get(win);
      if (!transitions) {
        return;
      }
      for (const transition of transitions.values()) {
        win.clearTimeout(transition.timer);
      }
      this.windowTransitions.delete(win);
    }

    _isPiPaneID(paneID) {
      const value = String(paneID || "");
      return value === PANE_ID
        || value === this.sectionID
        || value.endsWith(`-${PANE_ID}`);
    }

    _setPiButtonActive(win, contextKey, active) {
      const context = SIDEBAR_CONTEXTS[contextKey];
      if (!context || !win || !win.document) {
        return;
      }
      const sidenav = win.document.querySelector(context.sidenavSelector);
      if (!sidenav) {
        return;
      }
      for (const button of sidenav.querySelectorAll("[data-pane]")) {
        if (!this._isPiPaneID(button.getAttribute("data-pane"))) {
          continue;
        }
        button.setAttribute("aria-selected", active ? "true" : "false");
        button.classList.toggle("zab-pi-sidenav-active", active);
      }
    }

    _entriesForWindow(win, create = false) {
      let entries = this.deckPanels.get(win);
      if (!entries && create) {
        entries = new Map();
        this.deckPanels.set(win, entries);
      }
      return entries || null;
    }

    _ensureDeckPanel(win, contextKey) {
      if (!win || !win.document || !SIDEBAR_CONTEXTS[contextKey]) {
        return null;
      }
      const entries = this._entriesForWindow(win, true);
      const existing = entries.get(contextKey);
      if (existing && existing.container.isConnected) {
        return existing;
      }
      if (existing) {
        existing.panel.dispose();
        entries.delete(contextKey);
      }
      const doc = win.document;
      const context = SIDEBAR_CONTEXTS[contextKey];
      const deck = doc.querySelector(context.deckSelector);
      if (!deck) {
        return null;
      }
      const container = createDeckContainer(doc, "zab-chat-deck-panel");
      container.id = context.panelID;
      container.dataset.zabSidebarContext = contextKey;
      container.setAttribute("flex", "1");
      const panel = new ChatPanel(this, doc, container);
      panel.root.classList.add("zab-chat--deck", `zab-chat--${contextKey}`);
      deck.append(container);
      const entry = {
        contextKey,
        deck,
        container,
        panel,
        previousPanel: deck.selectedPanel,
        bodies: new Set(),
      };
      entries.set(contextKey, entry);
      return entry;
    }

    showDeckPanel(win, contextKey) {
      const entry = this._ensureDeckPanel(win, contextKey);
      if (!entry) {
        return false;
      }
      if (entry.deck.selectedPanel !== entry.container) {
        const currentPanel = entry.deck.selectedPanel;
        if (currentPanel && currentPanel.isConnected !== false) {
          entry.previousPanel = currentPanel;
        }
      }
      entry.deck.selectedPanel = entry.container;
      entry.panel.root.classList.add("zab-chat--deck-active");
      this._setPiButtonActive(win, contextKey, true);
      return entry.deck.selectedPanel === entry.container;
    }

    hideDeckPanel(win, contextKey) {
      const entries = this._entriesForWindow(win);
      const entry = entries && entries.get(contextKey);
      if (!entry) {
        return false;
      }
      if (entry.deck.selectedPanel === entry.container) {
        const fallback = entry.previousPanel && entry.previousPanel.isConnected
          ? entry.previousPanel
          : [...entry.deck.children].find((child) => child !== entry.container);
        if (fallback) {
          entry.deck.selectedPanel = fallback;
        }
      }
      entry.panel.root.classList.remove("zab-chat--deck-active");
      this._setPiButtonActive(win, contextKey, false);
      return entry.deck.selectedPanel !== entry.container;
    }

    _removeDeckPanel(win, contextKey) {
      const entries = this._entriesForWindow(win);
      const entry = entries && entries.get(contextKey);
      if (!entry) {
        return;
      }
      this.hideDeckPanel(win, contextKey);
      for (const [body, panel] of [...this.panels.entries()]) {
        if (panel === entry.panel) {
          this.panels.delete(body);
        }
      }
      entry.panel.dispose();
      entry.container.remove();
      entries.delete(contextKey);
      if (!entries.size) {
        this.deckPanels.delete(win);
      }
    }

    _removeWindowDeckPanels(win) {
      const entries = this._entriesForWindow(win);
      if (!entries) {
        return;
      }
      for (const contextKey of [...entries.keys()]) {
        this._removeDeckPanel(win, contextKey);
      }
    }

    registerSection() {
      if (this.sectionID) {
        return this.sectionID;
      }
      const registered = this.Zotero.ItemPaneManager.registerSection({
        paneID: PANE_ID,
        pluginID: PLUGIN_ID,
        header: {
          l10nID: "zab-pi-chat-section-title",
          icon: `${this.rootURI}chrome/content/icons/pi-16.svg`,
        },
        sidenav: {
          l10nID: "zab-pi-chat-section-sidenav",
          icon: `${this.rootURI}chrome/content/icons/pi-20.svg`,
        },
        onInit: ({ doc, body, tabType }) => {
          this._panel(body, doc, tabType);
        },
        onDestroy: ({ body }) => {
          this.destroyPanel(body);
        },
        onItemChange: ({ body, doc, tabType, item, setEnabled }) => {
          const panel = this._panel(body, doc, tabType);
          if (!panel) {
            if (typeof setEnabled === "function") {
              setEnabled(false);
            }
            return;
          }
          void panel.setItem(item).then(() => {
            if (typeof setEnabled === "function") {
              setEnabled(Boolean(panel.selection));
            }
          });
        },
        onRender: ({ body, doc, tabType, item }) => {
          const panel = this._panel(body, doc, tabType);
          if (panel) {
            void panel.setItem(item);
          }
        },
        onToggle: ({ body, doc, tabType }) => {
          this._panel(body, doc, tabType);
        },
      });
      if (!registered) {
        this.log("error", "pi_chat_section_registration_failed");
        return null;
      }
      this.sectionID = registered;
      return registered;
    }

    _contextKey(body, tabType) {
      const explicit = String(tabType || "").toLowerCase();
      if (SIDEBAR_CONTEXTS[explicit]) {
        return explicit;
      }
      const details = body && typeof body.closest === "function" ? body.closest("item-details") : null;
      const inferred = String(details && (details.tabType || details.getAttribute("tabType")) || "").toLowerCase();
      return SIDEBAR_CONTEXTS[inferred] ? inferred : null;
    }

    _panel(body, doc, tabType) {
      let panel = this.panels.get(body);
      if (panel) {
        return panel;
      }
      const contextKey = this._contextKey(body, tabType);
      if (!contextKey) {
        return null;
      }
      const entry = this._ensureDeckPanel(doc.defaultView, contextKey);
      if (!entry) {
        return null;
      }
      entry.bodies.add(body);
      this.panels.set(body, entry.panel);
      return entry.panel;
    }

    destroyPanel(body) {
      const panel = this.panels.get(body);
      if (!panel) {
        return;
      }
      const entries = this._entriesForWindow(panel.win);
      if (entries) {
        for (const entry of entries.values()) {
          if (entry.panel === panel) {
            entry.bodies.delete(body);
            this.panels.delete(body);
            return;
          }
        }
      }
      panel.dispose();
      this.panels.delete(body);
    }

    cleanupWindow(win) {
      this._removeWindowDeckPanels(win);
      for (const [body, panel] of [...this.panels.entries()]) {
        if (panel.win === win) {
          panel.dispose();
          this.panels.delete(body);
        }
      }
      this._clearWindowTransitions(win);
      const clickHandler = this.windowClickHandlers.get(win);
      if (clickHandler) {
        for (const eventName of ["click", "command"]) {
          win.document.removeEventListener(eventName, clickHandler, true);
        }
        this.windowClickHandlers.delete(win);
      }
      const resources = this.windowResources.get(win) || [];
      for (const resource of resources) {
        resource.remove();
      }
      this.windowResources.delete(win);
    }

    shutdown() {
      for (const win of [...this.deckPanels.keys()]) {
        this._removeWindowDeckPanels(win);
      }
      for (const panel of this.panels.values()) {
        panel.dispose();
      }
      this.panels.clear();
      for (const [win, resources] of this.windowResources.entries()) {
        this._clearWindowTransitions(win);
        const clickHandler = this.windowClickHandlers.get(win);
        if (clickHandler) {
          for (const eventName of ["click", "command"]) {
            win.document.removeEventListener(eventName, clickHandler, true);
          }
          this.windowClickHandlers.delete(win);
        }
        for (const resource of resources) {
          resource.remove();
        }
        this.windowResources.delete(win);
      }
      if (this.sectionID) {
        this.Zotero.ItemPaneManager.unregisterSection(this.sectionID);
        this.sectionID = null;
      }
    }
  }

  return {
    create(options) {
      return new Controller(options);
    },
    __test: {
      canSaveSnapshot,
      contentText,
      documentsEqual,
      isFinalAssistantMessage,
      scopesEqual,
    },
  };
})();

if (typeof module !== "undefined" && module.exports) {
  module.exports = ZoteroAgentBridgePiChatPanel;
}
