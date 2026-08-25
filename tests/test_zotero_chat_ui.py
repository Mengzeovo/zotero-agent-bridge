from __future__ import annotations

import hashlib
import json
import re
import subprocess
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "zotero_companion_addon"
BOOTSTRAP_SCRIPT = ADDON / "bootstrap.js"
PANEL_SCRIPT = ADDON / "chrome" / "content" / "scripts" / "pi_chat_panel.js"
MARKDOWN_SCRIPT = ADDON / "chrome" / "content" / "scripts" / "markdown_renderer.js"
MARKED_SCRIPT = ADDON / "chrome" / "content" / "vendor" / "marked" / "marked.umd.js"
PANEL_STYLE = ADDON / "chrome" / "content" / "styles" / "pi_chat_panel.css"
XPI = ROOT / "dist" / "zotero-agent-bridge-addon.xpi"


class ZoteroChatUiStaticTest(unittest.TestCase):
    def test_panel_registers_zotero9_section_and_cleans_up(self) -> None:
        bootstrap = (ADDON / "bootstrap.js").read_text(encoding="utf-8-sig")
        panel = PANEL_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("Zotero.ItemPaneManager.registerSection", panel)
        self.assertIn("Zotero.ItemPaneManager.unregisterSection", panel)
        self.assertIn("onDestroy", panel)
        self.assertIn("cleanupWindow", panel)
        self.assertIn("state.chatPanel?.cleanupWindow(window)", bootstrap)
        self.assertIn("state.chatPanel?.shutdown()", bootstrap)
        self.assertIn("menuItems: new Map()", bootstrap)
        self.assertIn("state.menuItems.set(win, menuItem)", bootstrap)
        self.assertIn("uninstallMenus(window)", bootstrap)
        self.assertIn("pi_chat_panel.js", bootstrap)
        self.assertIn('insertFTLIfNeeded("zotero-agent-bridge.ftl")', panel)
        self.assertIn("chrome/content/icons/pi-16.svg", panel)
        self.assertIn("chrome/content/icons/pi-20.svg", panel)
        self.assertNotIn("chrome://zotero/skin/20/universal/book.svg", panel)
        self.assertIn('ChromeUtils.importESModule("resource://gre/modules/Subprocess.sys.mjs")', bootstrap)
        self.assertIn("Zotero.HTTP.request", bootstrap)
        self.assertNotIn("fetch(", bootstrap)
        self.assertIn('responseType: "text"', bootstrap)
        self.assertIn("bridge_bundle_manager.js", bootstrap)
        self.assertIn("bridge_config_manager.js", bootstrap)
        self.assertIn("ZOTERO_AGENT_BRIDGE_CONFIG", bootstrap)
        self.assertIn("xpi-bundled", bootstrap)
        self.assertIn('"/lifecycle/shutdown"', bootstrap)
        self.assertIn('"X-Bridge-Owner-Token"', bootstrap)
        self.assertIn('"quit-application-granted"', bootstrap)
        self.assertIn('state.bridgeOwnership === "owned"', bootstrap)

    def test_panel_uses_assistant_endpoints_and_safe_text_rendering(self) -> None:
        panel = PANEL_SCRIPT.read_text(encoding="utf-8")
        for endpoint in (
            "/assistant/session/open",
            "/assistant/session/message",
            "/assistant/session/events?after=",
            "/assistant/session/messages",
            "/assistant/session/status",
            "/assistant/session/abort",
            "/assistant/session/reset",
            "/assistant/session/model",
            "/assistant/models",
            "/assistant/thinking-levels",
            "/assistant/session/thinking-level",
            "/assistant/session/save-note",
            "/assistant/session/history",
            "/assistant/session/resume",
        ):
            self.assertIn(endpoint, panel)
        self.assertIn("textContent", panel)
        self.assertIn("replaceChildren", panel)
        self.assertNotIn("innerHTML", panel)
        self.assertIn('update.type === "text_delta"', panel)
        self.assertIn('event.type === "agent_settled" && this.promptStarted', panel)
        self.assertIn('event.type === "agent_start"', panel)
        self.assertIn("accepted && accepted.event_cursor", panel)
        self.assertIn("this.cursor = eventCursor", panel)
        self.assertIn("shouldSendOnKeydown(event)", panel)
        self.assertNotIn("event.ctrlKey || event.metaKey", panel)
        self.assertIn('this.input.addEventListener("paste"', panel)
        self.assertIn("clipboard.items", panel)
        self.assertIn("reader.readAsDataURL(file)", panel)
        self.assertIn("{ message, images }", panel)
        self.assertIn("this.images.length", panel)
        self.assertIn("currentIdentity === nextIdentity", panel)
        self.assertIn("this.hasPendingSelection", panel)
        self.assertIn("this.selectionGeneration", panel)
        self.assertIn("this.sessionGeneration", panel)
        self.assertIn("this._scopeMatches(scope)", panel)
        self.assertIn("await this._applyPendingSelection()", panel)
        self.assertIn("await this.controller.fileExists(path)", panel)
        self.assertNotIn("attachment = attachment || attachments[0]", panel)
        self.assertIn("this.strings.system", panel)
        self.assertIn("context_injection_required", panel)
        self.assertIn("context_updated", panel)
        self.assertIn("this.strings.contextRequired", panel)
        self.assertIn("this.strings.contextUpdated", panel)
        self.assertIn("accepted.context_injected", panel)
        self.assertIn("this.saveButton.disabled = true", panel)
        self.assertIn("this.win.confirm(this.strings.saveConfirm)", panel)
        self.assertIn("canSaveSnapshot", panel)
        self.assertIn("this.lastFinalScope", panel)
        self.assertIn("this.lastFinalAnswer = null", panel)
        self.assertIn("finalAnswer = null", panel)
        self.assertIn("answer,", panel)
        self.assertIn("question,", panel)
        self.assertNotIn("Save will be enabled in the next implementation step", panel)
        self.assertIn("this.lastErrorMessage !== message", panel)
        self.assertIn("this.strings.retryStart", panel)
        self.assertIn("markdownRenderer.render", panel)
        self.assertIn('this.doc.addEventListener("copy", this._copyHandler, true)', panel)
        self.assertIn('this.doc.removeEventListener("copy", this._copyHandler, true)', panel)
        self.assertIn("markdownRenderer.handleCopy", panel)
        self.assertIn("this.historyButton", panel)
        self.assertIn("this.historyPopover", panel)
        self.assertIn("toggleHistory", panel)
        self.assertIn("_resumeSession", panel)
        self.assertIn("session_id", panel)
        self.assertIn('this.doc.addEventListener("click", this._historyDismissHandler, true)', panel)
        self.assertIn('this.doc.removeEventListener("click", this._historyDismissHandler, true)', panel)
        self.assertIn("this._hideHistory()", panel)
        self.assertIn("zab-chat__history-popover", panel)
        self.assertIn("selectsRow.append(modelRow, thinkingRow)", panel)
        self.assertIn("actionRow.append(primaryActions, secondaryActions, this.historyPopover)", panel)
        self.assertIn("this.modelSelect", panel)
        self.assertIn("this._loadModels(scope)", panel)
        self.assertIn("this.thinkingSelect", panel)
        self.assertIn("this._loadThinkingLevels(scope)", panel)
        self.assertIn("this._changeThinkingLevel()", panel)
        self.assertIn("this.strings.thinkingUnavailable", panel)
        self.assertIn("thinkingChanged", panel)
        self.assertIn("model_id: model.id", panel)
        self.assertIn("showDeckPanel", panel)
        self.assertIn("hideDeckPanel", panel)
        self.assertIn('sidenavSelector: "#zotero-view-item-sidenav"', panel)
        self.assertIn('deckSelector: "#zotero-item-pane-content"', panel)
        self.assertIn('sidenavSelector: "#zotero-context-pane-sidenav"', panel)
        self.assertIn('deckSelector: "#zotero-context-pane-inner deck"', panel)
        self.assertIn('toolbarbutton[data-pane], [data-pane]', panel)
        self.assertIn('["click", "command"]', panel)
        self.assertIn("_scheduleDeckTransition", panel)
        self.assertIn('setAttribute("aria-selected"', panel)
        self.assertIn("entry.deck.selectedPanel = entry.container", panel)
        self.assertNotIn("showLibraryDeckPanel", panel)
        self.assertNotIn("libraryDeckPanels", panel)
        self.assertNotIn("请确认 Bridge 和 Pi 已启动", panel)

    def test_clipboard_image_payload_helpers_run_in_node(self) -> None:
        script = f"""
const assert = require('assert');
const test = require({json.dumps(str(PANEL_SCRIPT))}).__test;
const payload = test.imagePayloadFromDataURL('data:image/png;base64,aGVsbG8=');
assert.deepStrictEqual(payload, {{ type: 'image', data: 'aGVsbG8=', mimeType: 'image/png' }});
assert.strictEqual(test.contentImageCount([{{ type: 'text', text: 'look' }}, payload]), 1);
assert.strictEqual(
  test.displayContentText([{{ type: 'text', text: 'look' }}, payload], {{ imageCount: '{{count}} image(s) attached' }}),
  'look\\n1 image(s) attached',
);
assert.throws(() => test.imagePayloadFromDataURL('data:image/svg+xml;base64,aGVsbG8='), /Unsupported image type/);
assert.strictEqual(test.shouldSendOnKeydown({{ key: 'Enter', shiftKey: false, isComposing: false }}), true);
assert.strictEqual(test.shouldSendOnKeydown({{ key: 'Enter', shiftKey: true, isComposing: false }}), false);
assert.strictEqual(test.shouldSendOnKeydown({{ key: 'Enter', shiftKey: false, isComposing: true }}), false);
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_better_notes_markdown_conversion_uses_safe_fallback_in_node(self) -> None:
        script = f"""
const assert = require('assert');
const bootstrap = require({json.dumps(str(BOOTSTRAP_SCRIPT))});
const convert = bootstrap.__test.convertMarkdownNoteHTML;
(async () => {{
  const payload = {{ markdown: 'Inline $x$', note_html: '<p>fallback</p>' }};
  const betterNotes = {{ api: {{ convert: {{ md2html: async (markdown) => {{
    assert.strictEqual(markdown, payload.markdown);
    return '<p><span class="math">$x$</span></p>';
  }} }} }} }};
  const converted = await convert(payload, betterNotes);
  assert.strictEqual(converted.renderer, 'better-notes');
  assert.strictEqual(converted.html, '<p><span class="math">$x$</span></p>');
  assert.strictEqual(converted.error, null);

  const unavailable = await convert(payload, null);
  assert.strictEqual(unavailable.renderer, 'bridge');
  assert.strictEqual(unavailable.html, payload.note_html);
  assert.strictEqual(unavailable.error, null);

  const failure = await convert(payload, {{ api: {{ convert: {{ md2html: async () => {{ throw new Error('boom'); }} }} }} }});
  assert.strictEqual(failure.renderer, 'bridge');
  assert.strictEqual(failure.html, payload.note_html);
  assert.strictEqual(failure.error.message, 'boom');

  const empty = await convert(payload, {{ api: {{ convert: {{ md2html: async () => '   ' }} }} }});
  assert.strictEqual(empty.renderer, 'bridge');
  assert.strictEqual(empty.html, payload.note_html);
  assert.match(empty.error.message, /empty note HTML/);
}})().catch((error) => {{
  console.error(error);
  process.exitCode = 1;
}});
"""
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_markdown_renderer_guards_and_math_detection_run_in_node(self) -> None:
        renderer = MARKDOWN_SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("innerHTML", renderer)
        self.assertIn('gfm: true', renderer)
        self.assertIn('trust: false', renderer)
        self.assertIn('throwOnError: false', renderer)
        problematic = r"""意思是：

\[
\text{接收功率}
=
\text{发射功率}\times\text{湍流衰落}
\]

因为 \(L_{\mathrm{fog}}\) 会减小。"""
        protected_code = "Code `\\(raw\\)`\n\n```tex\n\\[raw\\]\n```"
        script = f"""
const assert = require('assert');
const renderer = require({json.dumps(str(MARKDOWN_SCRIPT))});
const markedModule = require({json.dumps(str(MARKED_SCRIPT))});
const marked = markedModule.marked || markedModule;
const test = renderer.__test;
assert.strictEqual(test.safeHref('javascript:alert(1)'), null);
assert.strictEqual(test.safeHref('data:text/html,x'), null);
assert.strictEqual(test.safeHref('https://example.com/a'), 'https://example.com/a');
assert.strictEqual(test.blockMathSource('$$\\nx^2\\n$$'), 'x^2');
assert.strictEqual(test.blockMathSource('\\\\[a+b\\\\]'), 'a+b');
assert.deepStrictEqual(test.splitInlineMath('A $x+y$ B'), [
  {{ type: 'text', value: 'A ' }},
  {{ type: 'math', value: 'x+y', raw: '$x+y$' }},
  {{ type: 'text', value: ' B' }},
]);
assert.deepStrictEqual(test.splitInlineMath('A \\\\(x+y\\\\) B'), [
  {{ type: 'text', value: 'A ' }},
  {{ type: 'math', value: 'x+y', raw: '\\\\(x+y\\\\)' }},
  {{ type: 'text', value: ' B' }},
]);
const prepared = test.prepareMarkdown(marked, {json.dumps(problematic, ensure_ascii=False)});
assert.strictEqual(prepared.math.length, 2);
assert.strictEqual(prepared.math[0].displayMode, true);
assert.match(prepared.math[0].source, /接收功率[\\s\\S]*\\n=\\n[\\s\\S]*湍流衰落/);
assert.strictEqual(prepared.math[0].raw.startsWith(String.fromCharCode(92) + '['), true);
assert.strictEqual(prepared.math[0].raw.endsWith(String.fromCharCode(92) + ']'), true);
assert.strictEqual(prepared.math[1].displayMode, false);
assert.strictEqual(prepared.math[1].source, {json.dumps(r'L_{\mathrm{fog}}')});
assert.strictEqual(prepared.math[1].raw, {json.dumps(r'\(L_{\mathrm{fog}}\)')});
assert.strictEqual(prepared.tokens.some((token) => token.type === 'heading'), false);
const calls = [];
const makeNode = (tag) => ({{
  tag,
  children: [],
  className: '',
  dataset: {{}},
  style: {{}},
  append(...nodes) {{ this.children.push(...nodes); }},
  replaceChildren(...nodes) {{ this.children = nodes; }},
  setAttribute() {{}},
}});
const doc = {{
  createElementNS: (_namespace, tag) => makeNode(tag),
  createDocumentFragment: () => makeNode('#fragment'),
  createTextNode: (value) => ({{ tag: '#text', value }}),
}};
const target = makeNode('div');
target.ownerDocument = doc;
renderer.create({{
  marked,
  katex: {{ render: (source, container, options) => calls.push({{
    source,
    displayMode: options.displayMode,
    raw: container.dataset.zabMathSource,
  }}) }},
}}).render(target, {json.dumps(problematic, ensure_ascii=False)});
assert.deepStrictEqual(calls, [
  {{ source: prepared.math[0].source, displayMode: true, raw: prepared.math[0].raw }},
  {{
    source: {json.dumps(r'L_{\mathrm{fog}}')},
    displayMode: false,
    raw: {json.dumps(r'\(L_{\mathrm{fog}}\)')},
  }},
]);
const code = test.protectMath({json.dumps(protected_code)});
assert.strictEqual(code.math.length, 0);
assert.strictEqual(code.source, {json.dumps(protected_code)});
const dollarPrepared = test.prepareMarkdown(marked, '$$\\na=b\\n$$ and $x+y$');
assert.strictEqual(dollarPrepared.math.length, 2);
assert.strictEqual(dollarPrepared.math[0].displayMode, true);
assert.strictEqual(dollarPrepared.math[0].raw, '$$\\na=b\\n$$');
assert.strictEqual(dollarPrepared.math[1].displayMode, false);
assert.strictEqual(dollarPrepared.math[1].raw, '$x+y$');
"""
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_formula_copy_restores_original_latex_in_node(self) -> None:
        inline_source = r"\(x+y\)"
        script = f"""
const assert = require('assert');
const rendererModule = require({json.dumps(str(MARKDOWN_SCRIPT))});
const test = rendererModule.__test;
const raw = {json.dumps(inline_source)};
const formula = {{ dataset: {{ zabMathSource: raw }} }};
const formulaParent = {{ closest: () => formula }};
const formulaText = {{ parentElement: formulaParent }};
const formulaSelection = {{
  isCollapsed: false,
  rangeCount: 1,
  getRangeAt: () => ({{
    startContainer: formulaText,
    endContainer: formulaText,
    intersectsNode: (node) => node === formulaRoot,
  }}),
}};
const formulaDoc = {{ defaultView: {{ getSelection: () => formulaSelection }} }};
const formulaRoot = {{ ownerDocument: formulaDoc, contains: (node) => node === formula }};
const writes = [];
const event = {{
  clipboardData: {{ setData: (type, value) => writes.push([type, value]) }},
  preventDefault() {{ this.prevented = true; }},
}};
assert.strictEqual(rendererModule.create({{}}).handleCopy(event, formulaRoot), true);
assert.deepStrictEqual(writes, [['text/plain', raw]]);
assert.strictEqual(event.prevented, true);

const clonedMath = {{
  dataset: {{ zabMathSource: '$x+y$' }},
  textContent: 'rendered math',
  replaceChildren(node) {{ this.textContent = node.textContent; }},
}};
const fragment = {{
  querySelectorAll: () => [clonedMath],
  get textContent() {{ return `Before ${{clonedMath.textContent}} after`; }},
}};
const host = {{
  style: {{}},
  setAttribute() {{}},
  append(node) {{ this.child = node; }},
  get innerText() {{ return this.child.textContent; }},
  remove() {{ this.removed = true; }},
}};
const mixedDoc = {{
  body: {{ append(node) {{ this.child = node; }} }},
  createElementNS: () => host,
  createTextNode: (value) => ({{ textContent: value }}),
}};
const outside = {{ parentElement: {{ closest: () => null }} }};
const mixedSelection = {{
  isCollapsed: false,
  rangeCount: 1,
  getRangeAt: () => ({{
    startContainer: outside,
    endContainer: outside,
    intersectsNode: () => true,
    cloneContents: () => fragment,
  }}),
}};
assert.strictEqual(
  test.selectionTextWithMath(mixedDoc, {{ contains: () => false }}, mixedSelection),
  'Before $x+y$ after',
);
assert.strictEqual(host.removed, true);
"""
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_dual_context_deck_panels_switch_and_restore_in_node(self) -> None:
        script = f"""
const assert = require('assert');
const panel = require({json.dumps(str(PANEL_SCRIPT))});
const classes = () => {{
  const values = new Set();
  return {{
    add: (...items) => items.forEach((value) => values.add(value)),
    remove: (value) => values.delete(value),
    contains: (value) => values.has(value),
  }};
}};
const makeEntry = () => {{
  const defaultPanel = {{ isConnected: true }};
  const otherPanel = {{ isConnected: true }};
  const chatPanel = {{ isConnected: true }};
  const deck = {{ selectedPanel: defaultPanel, children: [defaultPanel, otherPanel, chatPanel] }};
  const rootClasses = classes();
  return {{
    defaultPanel,
    otherPanel,
    chatPanel,
    rootClasses,
    entry: {{
      deck,
      container: chatPanel,
      panel: {{ root: {{ classList: rootClasses }} }},
      previousPanel: defaultPanel,
      bodies: new Set(),
    }},
  }};
}};
const controller = panel.create({{ Zotero: {{}}, rootURI: '', locale: 'zh-CN', bridgeRequest() {{}}, appendLog() {{}}, fileExists: async () => true }});
controller.sectionID = 'zotero-agent-bridge\\@local-zotero-agent-bridge-pi-chat';
assert.strictEqual(controller._isPiPaneID('zotero-agent-bridge-pi-chat'), true);
assert.strictEqual(controller._isPiPaneID(controller.sectionID), true);
assert.strictEqual(controller._isPiPaneID('other-pane'), false);
const win = {{ document: {{ querySelector: () => null }} }};
const library = makeEntry();
const reader = makeEntry();
library.entry.panel.win = win;
reader.entry.panel.win = win;
controller.deckPanels.set(win, new Map([['library', library.entry], ['reader', reader.entry]]));
controller.showDeckPanel(win, 'library');
assert.strictEqual(library.entry.deck.selectedPanel, library.chatPanel);
assert.strictEqual(reader.entry.deck.selectedPanel, reader.defaultPanel);
assert.strictEqual(library.rootClasses.contains('zab-chat--deck-active'), true);
controller.showDeckPanel(win, 'library');
assert.strictEqual(library.entry.previousPanel, library.defaultPanel);
controller.showDeckPanel(win, 'reader');
assert.strictEqual(reader.entry.deck.selectedPanel, reader.chatPanel);
controller.hideDeckPanel(win, 'library');
assert.strictEqual(library.entry.deck.selectedPanel, library.defaultPanel);
assert.strictEqual(reader.entry.deck.selectedPanel, reader.chatPanel);
assert.strictEqual(library.rootClasses.contains('zab-chat--deck-active'), false);
reader.entry.deck.selectedPanel = reader.otherPanel;
controller.hideDeckPanel(win, 'reader');
assert.strictEqual(reader.entry.deck.selectedPanel, reader.otherPanel);
assert.strictEqual(reader.rootClasses.contains('zab-chat--deck-active'), false);
const transientBody = {{}};
reader.entry.bodies.add(transientBody);
controller.panels.set(transientBody, reader.entry.panel);
controller.destroyPanel(transientBody);
assert.strictEqual(controller.deckPanels.get(win).get('reader'), reader.entry);
assert.strictEqual(reader.entry.bodies.has(transientBody), false);
"""
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_assistant_note_uses_dedicated_validated_queue_command(self) -> None:
        sources = [
            (ROOT / "zotero_companion_addon" / "bootstrap.js").read_text(encoding="utf-8-sig"),
            (ADDON / "chrome" / "content" / "scripts" / "zotero_agent_bridge.js").read_text(encoding="utf-8-sig"),
        ]
        for source in sources:
            command_switch = source.split("async function processCommand(request)", 1)[1].split(
                "function validateRequest(request)", 1
            )[0]
            self.assertEqual(re.findall(r'case "([^"]+)"', command_switch), ["create_assistant_note"])
            self.assertIn("handleCreateAssistantNote(request)", source)
            self.assertIn("Assistant document_id must be a SHA-256 hex digest", source)
            self.assertIn("Assistant context_fingerprint must be a SHA-256 hex digest", source)
            self.assertIn("Assistant attachment_key is required", source)
            for retired in (
                "handleCreateItem",
                "handleUpdateItem",
                "handleAttachLinkedPdf",
                "handleCreateNote",
                "handleCreateCollection",
                "handleUpdateCollection",
            ):
                self.assertNotIn(retired, source)

    def test_save_note_state_guards_run_in_node(self) -> None:
        script = f"""
const assert = require('assert');
const panel = require({json.dumps(str(PANEL_SCRIPT))});
const test = panel.__test;
const scope = {{ selectionGeneration: 3, sessionGeneration: 7 }};
const document = {{ itemKey: 'ABCD1234', attachmentKey: 'PDFD1234', contextFingerprint: 'f'.repeat(64), documentId: 'd'.repeat(64) }};
assert.strictEqual(test.isFinalAssistantMessage({{ role: 'assistant', content: 'done', stopReason: 'stop' }}), true);
assert.strictEqual(test.isFinalAssistantMessage({{ role: 'assistant', content: 'partial', stopReason: 'aborted' }}), false);
assert.strictEqual(test.isFinalAssistantMessage({{ role: 'assistant', content: '   ', stopReason: 'stop' }}), false);
assert.strictEqual(test.canSaveSnapshot({{ sessionOpen: true, streaming: false, sending: false, answer: 'done', finalScope: scope, currentScope: scope, finalDocument: document, currentDocument: document }}), true);
assert.strictEqual(test.canSaveSnapshot({{ sessionOpen: true, streaming: true, sending: false, answer: 'partial', finalScope: scope, currentScope: scope, finalDocument: document, currentDocument: document }}), false);
assert.strictEqual(test.canSaveSnapshot({{ sessionOpen: true, streaming: false, sending: false, answer: 'done', finalScope: scope, currentScope: {{ selectionGeneration: 4, sessionGeneration: 7 }}, finalDocument: document, currentDocument: document }}), false);
assert.strictEqual(test.canSaveSnapshot({{ sessionOpen: true, streaming: false, sending: false, answer: '', finalScope: scope, currentScope: scope, finalDocument: document, currentDocument: document }}), false);
"""
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_bridge_autostart_defaults_are_safe(self) -> None:
        config = json.loads((ADDON / "config" / "default-config.json").read_text(encoding="utf-8"))
        self.assertTrue(config["autoStartBridge"])
        self.assertTrue(config["stopOwnedBridgeOnShutdown"])
        self.assertEqual(config["bridgeLauncherFile"], "bridge-launcher.json")
        self.assertGreaterEqual(config["bridgeStartupTimeoutMs"], 10000)
        self.assertEqual(config["bridgeHost"], "127.0.0.1")

    def test_bundle_install_and_rollback_guards_are_regression_covered(self) -> None:
        bootstrap = (ADDON / "bootstrap.js").read_text(encoding="utf-8-sig")
        manager = (ADDON / "chrome" / "content" / "scripts" / "bridge_bundle_manager.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("return hashBytes(await IOUtils.read(path));", manager)
        self.assertIn("const previousState = await readInstallState(root);", manager)
        self.assertIn("...previousState", manager)
        self.assertIn("protocol_floor", manager)
        self.assertIn("pi_only_established_at", manager)
        self.assertIn("legacy_fallback_consumed", manager)
        self.assertIn("rollbackDecision", manager)
        self.assertIn("bridge_bundle_existing_quarantined", manager)
        self.assertIn(".invalid-${Services.uuid.generateUUID()", manager)
        self.assertIn('throw new BundleError(\n              "bundle_existing_invalid"', manager)
        self.assertIn('["ready", "rollback"].includes(state.bridgeBundleState)', bootstrap)
        self.assertIn('typeof error.code === "string"', bootstrap)
        self.assertIn('const bundleInstallError = state.bridgeBundleState === "error"', bootstrap)
        self.assertIn("state.bridgeLastError = bundleInstallError", bootstrap)
        self.assertIn("rollbackCandidate(primaryBundle)", bootstrap)
        self.assertIn("markLaunchSucceeded(bundleInfo, { emergencyLegacyFallback })", bootstrap)
        self.assertIn("recordLaunchFailure(rollback, rollbackError)", bootstrap)
        self.assertIn('"bridge_bundle_rollback_failed"', bootstrap)
        self.assertLess(
            bootstrap.index('lifecycle.protocol_version === undefined'),
            bootstrap.index('Number.isInteger(Number(lifecycle.pid))'),
        )
        self.assertIn("pid: process.pid", bootstrap)

    def test_lifecycle_v2_classification_preserves_v1_transition_in_node(self) -> None:
        script = f"""
const assert = require('assert');
const test = require({json.dumps(str(BOOTSTRAP_SCRIPT))}).__test;
assert.strictEqual(test.PI_ONLY_LIFECYCLE_PROTOCOL_VERSION, 2);
assert.strictEqual(test.TRANSITIONAL_LIFECYCLE_PROTOCOL_VERSION, 1);
assert.strictEqual(test.PI_ONLY_PRODUCT_SCOPE, 'zotero-pi-only');
const current = test.classifyBridgeLifecycle({{
  pid: 42,
  bridge_version: '0.3.5',
  protocol_version: 2,
  product_scope: 'zotero-pi-only',
  distribution: 'xpi-bundled',
}}, {{
  bundled: true,
  expectedBundleVersion: '0.3.5',
  expectedBundleProtocolVersion: 2,
}});
assert.strictEqual(current.compatible, true);
assert.strictEqual(current.piOnly, true);
assert.strictEqual(current.transitional, false);
assert.strictEqual(current.productScope, 'zotero-pi-only');
const v1 = test.classifyBridgeLifecycle({{
  pid: 43,
  bridge_version: '0.3.5',
  protocol_version: 1,
  distribution: 'xpi-bundled',
}});
assert.strictEqual(v1.compatible, true);
assert.strictEqual(v1.legacy, true);
assert.strictEqual(v1.transitional, true);
assert.strictEqual(v1.piOnly, false);
assert.strictEqual(v1.productScope, 'legacy-agent-bridge');
const legacy = test.classifyBridgeLifecycle({{status: 'ok'}});
assert.strictEqual(legacy.protocolVersion, 0);
assert.strictEqual(legacy.transitional, true);
assert.throws(
  () => test.classifyBridgeLifecycle({{
    pid: 44,
    bridge_version: '0.3.5',
    protocol_version: 2,
    product_scope: 'general-agent-bridge',
    distribution: 'xpi-bundled',
  }}),
  (error) => error.code === 'bridge_protocol_incompatible',
);
assert.throws(
  () => test.classifyBridgeLifecycle({{
    pid: 45,
    bridge_version: '0.3.5',
    protocol_version: 1,
    distribution: 'xpi-bundled',
  }}, {{bundled: true, expectedBundleVersion: '0.3.5', expectedBundleProtocolVersion: 2}}),
  (error) => error.code === 'bridge_bundle_runtime_mismatch',
);
"""
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_panel_styles_accessibility_and_localization_resources(self) -> None:
        styles = PANEL_STYLE.read_text(encoding="utf-8")
        self.assertIn(":focus-visible", styles)
        self.assertIn("prefers-reduced-motion", styles)
        self.assertIn('item-pane-section[data-pane="zotero-agent-bridge-pi-chat"]', styles)
        self.assertIn('item-pane-section[data-pane$="-zotero-agent-bridge-pi-chat"]', styles)
        self.assertIn('item-pane-custom-section[data-pane$="-zotero-agent-bridge-pi-chat"]', styles)
        self.assertIn('collapsible-section[data-pane$="-zotero-agent-bridge-pi-chat"]', styles)
        self.assertNotIn('item-details[tabtype="library"] item-pane-section', styles)
        self.assertIn("-moz-box-orient: vertical", styles)
        self.assertIn(".zab-chat--deck {\n  width: 100%;\n  height: 100%;\n  flex: 1 1 0;", styles)
        self.assertIn(".zab-chat--deck .zab-chat__transcript {\n  min-height: 0;\n  max-height: calc(100vh - 279px);\n}", styles)
        self.assertIn(".zab-chat__selects-row", styles)
        self.assertIn(".zab-chat__actions {\n  display: flex;\n  flex-wrap: wrap;\n  justify-content: space-between;\n  gap: 6px;\n  position: relative;\n}", styles)
        self.assertIn("bottom: calc(100% + 6px);", styles)
        self.assertIn("max-height: 260px;", styles)
        self.assertNotIn("max-height: 45%;", styles)
        self.assertIn(".zab-chat__model-select", styles)
        self.assertIn(".zab-chat__model-select:focus-visible", styles)
        self.assertIn(".zab-chat__image-tray", styles)
        self.assertIn(".zab-chat__image-preview", styles)
        self.assertIn(".zab-chat__image-remove", styles)
        self.assertNotIn("linear-gradient", styles)
        zh = (ADDON / "locale" / "zh-CN" / "zotero-agent-bridge.ftl").read_text(encoding="utf-8")
        en = (ADDON / "locale" / "en-US" / "zotero-agent-bridge.ftl").read_text(encoding="utf-8")
        self.assertIn("zab-pi-chat-message-system = 状态", zh)
        self.assertIn("zab-pi-chat-message-system = Status", en)
        self.assertIn(".label = Pi 文献助手", zh)
        self.assertIn(".tooltiptext = Pi 文献助手", zh)
        self.assertIn(".label = Pi Literature Assistant", en)
        self.assertIn(".tooltiptext = Pi Literature Assistant", en)
        self.assertIn("zab-pi-chat-save-note-confirm", zh)
        self.assertIn("zab-pi-chat-save-note-success", zh)
        self.assertIn("zab-pi-chat-save-note-confirm", en)
        self.assertIn("zab-pi-chat-save-note-success", en)
        for filename, size in (("pi-16.svg", "16"), ("pi-20.svg", "20")):
            icon_path = ADDON / "chrome" / "content" / "icons" / filename
            icon = icon_path.read_text(encoding="utf-8")
            root = ET.parse(icon_path).getroot()
            self.assertEqual(root.attrib["width"], size)
            self.assertEqual(root.attrib["height"], size)
            self.assertIn("context-fill", icon)

    def test_addon_version_and_zotero9_range_are_consistent(self) -> None:
        manifest = json.loads((ADDON / "manifest.json").read_text(encoding="utf-8-sig"))
        rdf_root = ET.parse(ADDON / "install.rdf").getroot()
        bootstrap = (ADDON / "bootstrap.js").read_text(encoding="utf-8-sig")
        legacy = (ADDON / "chrome" / "content" / "scripts" / "zotero_agent_bridge.js").read_text(
            encoding="utf-8-sig"
        )
        version = manifest["version"]
        self.assertEqual(version, "0.3.5")
        zotero_manifest = manifest["applications"]["zotero"]
        self.assertEqual(zotero_manifest["strict_max_version"], "9.0.*")
        self.assertEqual(
            zotero_manifest["update_url"],
            "https://raw.githubusercontent.com/Mengzeovo/zotero-agent-bridge/main/updates.json",
        )
        version_nodes = [node.text for node in rdf_root.iter() if node.tag.endswith("version")]
        max_nodes = [node.text for node in rdf_root.iter() if node.tag.endswith("maxVersion")]
        update_nodes = [node.text for node in rdf_root.iter() if node.tag.endswith("updateURL")]
        self.assertIn(version, version_nodes)
        self.assertIn("9.0.*", max_nodes)
        self.assertIn(zotero_manifest["update_url"], update_nodes)
        self.assertIn(f'ADDON_VERSION = "{version}"', bootstrap)
        self.assertIn(f'ADDON_VERSION = "{version}"', legacy)

    def test_built_xpi_contains_chat_resources(self) -> None:
        self.assertTrue(XPI.is_file(), "Build the add-on XPI before running the complete validation suite")
        with zipfile.ZipFile(XPI) as archive:
            names = set(archive.namelist())
            expected = {
                "bootstrap.js",
                "manifest.json",
                "chrome/content/scripts/pi_chat_panel.js",
                "chrome/content/scripts/markdown_renderer.js",
                "chrome/content/scripts/bridge_bundle_manager.js",
                "chrome/content/scripts/bridge_config_manager.js",
                "chrome/content/styles/pi_chat_panel.css",
                "chrome/content/vendor/marked/marked.umd.js",
                "chrome/content/vendor/marked/LICENSE.md",
                "chrome/content/vendor/katex/katex.min.js",
                "chrome/content/vendor/katex/katex.min.css",
                "chrome/content/vendor/katex/LICENSE",
                "chrome/content/vendor/katex/fonts/KaTeX_Main-Regular.woff2",
                "chrome/content/icons/pi-16.svg",
                "chrome/content/icons/pi-20.svg",
                "locale/zh-CN/zotero-agent-bridge.ftl",
                "locale/en-US/zotero-agent-bridge.ftl",
                "bridge/windows-x64/bridge-manifest.json",
                "bridge/windows-x64/zab-bridge/zab-bridge.exe",
                "bridge/windows-x64/SBOM.cdx.json",
                "bridge/windows-x64/THIRD_PARTY_NOTICES.md",
            }
            self.assertTrue(expected.issubset(names), sorted(expected - names))
            manifest = json.loads(archive.read("manifest.json").decode("utf-8-sig"))
            self.assertEqual(manifest["version"], "0.3.5")
            bundle_manifest = json.loads(archive.read("bridge/windows-x64/bridge-manifest.json").decode("utf-8"))
            self.assertEqual(bundle_manifest["bridge_version"], "0.3.5")
            self.assertEqual(bundle_manifest["protocol_version"], 1)
            self.assertEqual(bundle_manifest["distribution"], "xpi-bundled")
            self.assertEqual(manifest["applications"]["zotero"]["strict_max_version"], "9.0.*")

        updates = json.loads((ROOT / "updates.json").read_text(encoding="utf-8"))
        update = updates["addons"]["zotero-agent-bridge@local"]["updates"][0]
        self.assertEqual(update["version"], manifest["version"])
        self.assertEqual(
            update["update_link"],
            "https://github.com/Mengzeovo/zotero-agent-bridge/releases/download/v0.3.5-beta/zotero-agent-bridge-addon-0.3.5.xpi",
        )
        self.assertEqual(
            update["update_hash"],
            "sha512:" + hashlib.sha512(XPI.read_bytes()).hexdigest(),
        )

    def test_bundle_manager_quarantines_invalid_install_and_reinstalls_in_node(self) -> None:
        script = r"""
const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { pathToFileURL } = require('url');

const managerFactory = require(process.argv[1]);
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'zab-bundle-test-'));
const localAppData = path.join(work, 'LocalAppData');
const addonRoot = path.join(work, 'addon');
const bundleSourceDir = path.join(addonRoot, 'bridge', 'windows-x64');
fs.mkdirSync(path.join(bundleSourceDir, 'zab-bridge'), { recursive: true });

const exeBytes = Buffer.from('fake bridge exe v2');
fs.writeFileSync(path.join(bundleSourceDir, 'zab-bridge', 'zab-bridge.exe'), exeBytes);
const manifest = {
  bundle_schema_version: 1,
  protocol_version: 2,
  product_scope: 'zotero-pi-only',
  distribution: 'xpi-bundled',
  platform: 'windows',
  architecture: 'x64',
  bridge_version: '0.4.0-beta',
  entrypoint: 'zab-bridge/zab-bridge.exe',
  sentinel: '.zab-bundle-installed.json',
  files: [
    {
      path: 'zab-bridge/zab-bridge.exe',
      size: exeBytes.length,
      sha256: crypto.createHash('sha256').update(exeBytes).digest('hex'),
    },
  ],
};
const manifestRaw = JSON.stringify(manifest, null, 2);
fs.writeFileSync(path.join(bundleSourceDir, 'bridge-manifest.json'), manifestRaw);
const manifestSha256 = crypto.createHash('sha256').update(manifestRaw, 'utf8').digest('hex');

const installRoot = path.join(localAppData, 'ZoteroAgentBridge', 'bridge');
const legacyRoot = path.join(installRoot, '0.3.5');
const legacyExeBytes = Buffer.from('legacy bridge exe v1');
fs.mkdirSync(path.join(legacyRoot, 'zab-bridge'), { recursive: true });
fs.writeFileSync(path.join(legacyRoot, 'zab-bridge', 'zab-bridge.exe'), legacyExeBytes);
const legacyManifest = {
  bundle_schema_version: 1,
  protocol_version: 1,
  distribution: 'xpi-bundled',
  platform: 'windows',
  architecture: 'x64',
  bridge_version: '0.3.5',
  entrypoint: 'zab-bridge/zab-bridge.exe',
  sentinel: '.zab-bundle-installed.json',
  files: [
    {
      path: 'zab-bridge/zab-bridge.exe',
      size: legacyExeBytes.length,
      sha256: crypto.createHash('sha256').update(legacyExeBytes).digest('hex'),
    },
  ],
};
const legacyManifestRaw = JSON.stringify(legacyManifest, null, 2);
const legacyManifestSha256 = crypto.createHash('sha256').update(legacyManifestRaw, 'utf8').digest('hex');
fs.writeFileSync(path.join(legacyRoot, '.zab-bundle-manifest.json'), legacyManifestRaw);
fs.writeFileSync(path.join(legacyRoot, '.zab-bundle-installed.json'), JSON.stringify({
  sentinel_schema_version: 1,
  bridge_version: '0.3.5',
  protocol_version: 1,
  manifest_sha256: legacyManifestSha256,
  installed_at: '2026-01-01T00:00:00.000Z',
  entrypoint: 'zab-bridge/zab-bridge.exe',
}));
fs.writeFileSync(path.join(installRoot, 'install-state.json'), JSON.stringify({
  state_schema_version: 1,
  current_version: '0.3.5',
  last_known_good: '0.3.5',
  pending_version: null,
  updated_at: '2026-01-01T00:00:00.000Z',
}));
const staleRoot = path.join(installRoot, '0.4.0-beta');
fs.mkdirSync(staleRoot, { recursive: true });
fs.writeFileSync(path.join(staleRoot, '.zab-bundle-installed.json'), JSON.stringify({
  sentinel_schema_version: 1,
  bridge_version: '0.4.0-beta',
  protocol_version: 2,
  product_scope: 'zotero-pi-only',
  manifest_sha256: 'stale-manifest-hash',
  installed_at: '2026-01-01T00:00:00.000Z',
  entrypoint: 'zab-bridge/zab-bridge.exe',
}));
fs.writeFileSync(path.join(staleRoot, 'zab-bridge-placeholder.txt'), 'old install');

const logs = [];
const localFile = () => ({
  path: '',
  initWithPath(value) { this.path = value; },
  create() { fs.writeFileSync(this.path, '', { flag: 'wx' }); },
});
const cryptoHash = () => ({
  chunks: [],
  init() {},
  update(bytes) { this.chunks.push(Buffer.from(bytes.buffer || bytes)); },
  finish() {
    return crypto.createHash('sha256').update(Buffer.concat(this.chunks)).digest('latin1');
  },
});
const Services = {
  dirsvc: { get: () => ({ path: localAppData }) },
  uuid: { generateUUID: () => ({ toString: () => '{' + crypto.randomUUID() + '}' }) },
  appinfo: { processID: process.pid },
  io: { newURI: (uri) => ({
    scheme: 'file',
    QueryInterface() { return { file: { path: decodeURIComponent(new URL(uri).pathname).replace(/^\//, '') } }; },
  }) },
};
const IOUtils = {
  makeDirectory: async (dir) => { fs.mkdirSync(dir, { recursive: true }); },
  exists: async (target) => fs.existsSync(target),
  stat: async (target) => {
    const stat = fs.statSync(target);
    return { type: stat.isDirectory() ? 'directory' : 'regular', size: stat.size, lastModified: stat.mtimeMs };
  },
  read: async (target) => new Uint8Array(fs.readFileSync(target)),
  readUTF8: async (target) => fs.readFileSync(target, 'utf8'),
  writeUTF8: async (target, value) => { fs.mkdirSync(path.dirname(target), { recursive: true }); fs.writeFileSync(target, value, 'utf8'); },
  copy: async (from, to, options = {}) => {
    if (options.noOverwrite && fs.existsSync(to)) { throw new Error('exists'); }
    fs.copyFileSync(from, to);
  },
  move: async (from, to, options = {}) => {
    if (options.noOverwrite && fs.existsSync(to)) { throw new Error('exists'); }
    fs.mkdirSync(path.dirname(to), { recursive: true });
    fs.renameSync(from, to);
  },
  remove: async (target) => { fs.rmSync(target, { force: true, recursive: true }); },
};
const PathUtils = {
  join: (...parts) => path.join(...parts),
  normalize: (value) => path.normalize(value),
  parent: (value) => path.dirname(value),
  profileDir: work,
};
const Zotero = { File: { getContentsFromURL: (url) => fs.readFileSync(decodeURIComponent(new URL(url).pathname).replace(/^\//, ''), 'utf8') } };
const Components = {
  interfaces: { nsIFile: { NORMAL_FILE_TYPE: 1 } },
  classes: {
    '@mozilla.org/file/local;1': { createInstance: localFile },
    '@mozilla.org/security/hash;1': { createInstance: cryptoHash },
  },
};
globalThis.Components = Components;

(async () => {
  const manager = managerFactory.create({
    rootURI: pathToFileURL(addonRoot + '/').href,
    addonVersion: '0.4.0-beta',
    Services, IOUtils, PathUtils, Zotero,
    appendLog: (level, message, details) => logs.push({ level, message, details }),
  });
  const installed = await manager.ensureInstalled();
  assert.strictEqual(installed.reused, false);
  assert.deepStrictEqual(fs.readFileSync(installed.executable), exeBytes);
  assert.strictEqual(fs.existsSync(path.join(staleRoot, 'zab-bridge-placeholder.txt')), false, 'stale contents are quarantined away');
  const quarantined = fs.readdirSync(installRoot).filter((name) => name.startsWith('0.4.0-beta.invalid-'));
  assert.strictEqual(quarantined.length, 1);
  assert.strictEqual(fs.readFileSync(path.join(installRoot, quarantined[0], 'zab-bridge-placeholder.txt'), 'utf8'), 'old install');
  const sentinel = JSON.parse(fs.readFileSync(path.join(installed.versionRoot, '.zab-bundle-installed.json'), 'utf8'));
  assert.strictEqual(sentinel.protocol_version, 2);
  assert.strictEqual(sentinel.product_scope, 'zotero-pi-only');
  assert.strictEqual(sentinel.manifest_sha256, manifestSha256);
  const rollback = await manager.rollbackCandidate(installed);
  assert.strictEqual(rollback.manifest.bridge_version, '0.3.5');
  assert.strictEqual(rollback.manifest.protocol_version, 1);
  assert.strictEqual(rollback.emergencyLegacyFallback, true);
  const reservedState = JSON.parse(fs.readFileSync(path.join(installRoot, 'install-state.json'), 'utf8'));
  assert.strictEqual(reservedState.legacy_fallback_consumed, true);
  assert.strictEqual(reservedState.legacy_fallback_version, '0.3.5');
  assert.strictEqual(reservedState.legacy_fallback_from, '0.4.0-beta');
  assert.strictEqual(reservedState.legacy_fallback_completed_at, null);
  assert.strictEqual(await manager.rollbackCandidate(installed), null);
  await manager.markLaunchSucceeded(rollback, { emergencyLegacyFallback: true });
  const consumedState = JSON.parse(fs.readFileSync(path.join(installRoot, 'install-state.json'), 'utf8'));
  assert.strictEqual(consumedState.legacy_fallback_consumed, true);
  assert.ok(consumedState.legacy_fallback_completed_at);
  assert.strictEqual(consumedState.protocol_floor, 0);
  await manager.markLaunchSucceeded(installed);
  const establishedState = JSON.parse(fs.readFileSync(path.join(installRoot, 'install-state.json'), 'utf8'));
  assert.strictEqual(establishedState.protocol_floor, 2);
  assert.strictEqual(establishedState.last_known_good, '0.4.0-beta');
  assert.strictEqual(establishedState.last_known_good_protocol_version, 2);
  assert.strictEqual(establishedState.last_known_good_product_scope, 'zotero-pi-only');
  assert.ok(establishedState.pi_only_established_at);
  assert.ok(logs.some((entry) => entry.message === 'bridge_bundle_existing_quarantined'));
  assert.ok(logs.some((entry) => entry.message === 'bridge_bundle_installed'));

  const reused = await manager.ensureInstalled();
  assert.strictEqual(reused.reused, true);
  assert.strictEqual(reused.executable, installed.executable);
  console.log('bundle quarantine + reinstall behavior OK');
})().catch((error) => { console.error(error); process.exitCode = 1; });
"""
        result = subprocess.run(
            ["node", "-e", script, str(ADDON / "chrome" / "content" / "scripts" / "bridge_bundle_manager.js")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertIn("bundle quarantine + reinstall behavior OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
