from __future__ import annotations

import hashlib
import json
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
  {{ type: 'math', value: 'x+y' }},
  {{ type: 'text', value: ' B' }},
]);
assert.deepStrictEqual(test.splitInlineMath('A \\\\(x+y\\\\) B'), [
  {{ type: 'text', value: 'A ' }},
  {{ type: 'math', value: 'x+y' }},
  {{ type: 'text', value: ' B' }},
]);
const prepared = test.prepareMarkdown(marked, {json.dumps(problematic, ensure_ascii=False)});
assert.strictEqual(prepared.math.length, 2);
assert.strictEqual(prepared.math[0].displayMode, true);
assert.match(prepared.math[0].source, /接收功率[\\s\\S]*\\n=\\n[\\s\\S]*湍流衰落/);
assert.strictEqual(prepared.math[1].displayMode, false);
assert.strictEqual(prepared.math[1].source, {json.dumps(r'L_{\mathrm{fog}}')});
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
  katex: {{ render: (source, _container, options) => calls.push({{ source, displayMode: options.displayMode }}) }},
}}).render(target, {json.dumps(problematic, ensure_ascii=False)});
assert.deepStrictEqual(calls, [
  {{ source: prepared.math[0].source, displayMode: true }},
  {{ source: {json.dumps(r'L_{\mathrm{fog}}')}, displayMode: false }},
]);
const code = test.protectMath({json.dumps(protected_code)});
assert.strictEqual(code.math.length, 0);
assert.strictEqual(code.source, {json.dumps(protected_code)});
const dollarPrepared = test.prepareMarkdown(marked, '$$\\na=b\\n$$ and $x+y$');
assert.strictEqual(dollarPrepared.math.length, 2);
assert.strictEqual(dollarPrepared.math[0].displayMode, true);
assert.strictEqual(dollarPrepared.math[1].displayMode, false);
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
        self.assertIn('["ready", "rollback"].includes(state.bridgeBundleState)', bootstrap)
        self.assertIn('typeof error.code === "string"', bootstrap)
        self.assertIn('const bundleInstallError = state.bridgeBundleState === "error"', bootstrap)
        self.assertIn("state.bridgeLastError = bundleInstallError", bootstrap)
        self.assertLess(
            bootstrap.index('lifecycle.protocol_version === undefined'),
            bootstrap.index('Number.isInteger(Number(lifecycle.pid))'),
        )
        self.assertIn("pid: process.pid", bootstrap)

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
        self.assertIn(".zab-chat--deck .zab-chat__transcript {\n  min-height: 0;\n  max-height: calc(100vh - 315px);\n}", styles)
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


if __name__ == "__main__":
    unittest.main()
