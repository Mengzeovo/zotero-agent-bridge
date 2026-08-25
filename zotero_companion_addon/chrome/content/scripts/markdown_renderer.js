"use strict";

var ZoteroAgentBridgeMarkdownRenderer = (() => {
  const HTML_NS = "http://www.w3.org/1999/xhtml";
  const SAFE_PROTOCOLS = new Set(["http:", "https:", "mailto:", "zotero:"]);
  const MATH_MARKER_PREFIX = "\uE000ZABMATH";
  const MATH_MARKER_SUFFIX = "\uE001";

  function createElement(doc, tag, className = "") {
    const element = doc.createElementNS(HTML_NS, tag);
    if (className) {
      element.className = className;
    }
    return element;
  }

  function markedLexer(markedLibrary, source) {
    const api = markedLibrary && markedLibrary.marked ? markedLibrary.marked : markedLibrary;
    const lexer = api && typeof api.lexer === "function"
      ? api.lexer.bind(api)
      : markedLibrary && typeof markedLibrary.lexer === "function"
        ? markedLibrary.lexer.bind(markedLibrary)
        : null;
    if (!lexer) {
      return null;
    }
    return lexer(String(source || ""), {
      async: false,
      breaks: false,
      gfm: true,
      pedantic: false,
    });
  }

  function safeHref(value) {
    const href = String(value || "").trim();
    if (!href || href.startsWith("#")) {
      return href || null;
    }
    const protocol = /^([a-z][a-z0-9+.-]*):/i.exec(href);
    return protocol && SAFE_PROTOCOLS.has(`${protocol[1].toLowerCase()}:`) ? href : null;
  }

  function findClosingDollar(text, start) {
    for (let index = start; index < text.length; index += 1) {
      if (text[index] === "\\") {
        index += 1;
        continue;
      }
      if (text[index] === "$" && text[index - 1] !== "$" && text[index + 1] !== "$") {
        return index;
      }
    }
    return -1;
  }

  function splitInlineMath(value) {
    const text = String(value || "");
    const parts = [];
    let plainStart = 0;
    let index = 0;
    const pushPlain = (end) => {
      if (end > plainStart) {
        parts.push({ type: "text", value: text.slice(plainStart, end) });
      }
    };
    while (index < text.length) {
      if (text[index] === "\\" && text[index + 1] === "(") {
        const end = text.indexOf("\\)", index + 2);
        if (end !== -1) {
          pushPlain(index);
          parts.push({
            type: "math",
            value: text.slice(index + 2, end),
            raw: text.slice(index, end + 2),
          });
          index = end + 2;
          plainStart = index;
          continue;
        }
      }
      if (text[index] === "$" && text[index + 1] !== "$" && (index === 0 || text[index - 1] !== "\\")) {
        const end = findClosingDollar(text, index + 1);
        if (end !== -1 && end > index + 1) {
          pushPlain(index);
          parts.push({
            type: "math",
            value: text.slice(index + 1, end),
            raw: text.slice(index, end + 1),
          });
          index = end + 1;
          plainStart = index;
          continue;
        }
      }
      index += 1;
    }
    pushPlain(text.length);
    return parts.length ? parts : [{ type: "text", value: text }];
  }

  function blockMathSource(value) {
    const text = String(value || "").trim();
    if (text.length >= 4 && text.startsWith("$$") && text.endsWith("$$")) {
      return text.slice(2, -2).trim();
    }
    if (text.length >= 4 && text.startsWith("\\[") && text.endsWith("\\]")) {
      return text.slice(2, -2).trim();
    }
    return null;
  }

  function isEscaped(text, index) {
    let backslashes = 0;
    for (let cursor = index - 1; cursor >= 0 && text[cursor] === "\\"; cursor -= 1) {
      backslashes += 1;
    }
    return backslashes % 2 === 1;
  }

  function findClosingDelimiter(text, delimiter, start) {
    let cursor = start;
    while (cursor < text.length) {
      const end = text.indexOf(delimiter, cursor);
      if (end === -1) {
        return -1;
      }
      if (!isEscaped(text, end)) {
        return end;
      }
      cursor = end + delimiter.length;
    }
    return -1;
  }

  function fencedCodeEnd(text, start) {
    const opening = /^ {0,3}(`{3,}|~{3,})[^\n]*(?:\n|$)/.exec(text.slice(start));
    if (!opening) {
      return -1;
    }
    const marker = opening[1];
    const markerCharacter = marker[0];
    const minimumLength = marker.length;
    let cursor = start + opening[0].length;
    while (cursor < text.length) {
      const lineEnd = text.indexOf("\n", cursor);
      const end = lineEnd === -1 ? text.length : lineEnd + 1;
      const line = text.slice(cursor, end);
      const closing = /^ {0,3}(`{3,}|~{3,})[ \t]*(?:\n|$)/.exec(line);
      if (closing && closing[1][0] === markerCharacter && closing[1].length >= minimumLength) {
        return end;
      }
      cursor = end;
    }
    return text.length;
  }

  function mathMarker(index) {
    return `${MATH_MARKER_PREFIX}${index}${MATH_MARKER_SUFFIX}`;
  }

  function protectMath(value) {
    const text = String(value || "");
    const math = [];
    const output = [];
    let cursor = 0;
    let lineStart = true;
    const stash = (source, displayMode, raw) => {
      const index = math.length;
      math.push({
        source: String(source || "").trim(),
        displayMode: Boolean(displayMode),
        raw: String(raw || ""),
      });
      output.push(mathMarker(index));
    };
    while (cursor < text.length) {
      if (lineStart) {
        const fenceEnd = fencedCodeEnd(text, cursor);
        if (fenceEnd !== -1) {
          output.push(text.slice(cursor, fenceEnd));
          cursor = fenceEnd;
          lineStart = true;
          continue;
        }
        if (text.startsWith("    ", cursor) || text[cursor] === "\t") {
          const lineEnd = text.indexOf("\n", cursor);
          const end = lineEnd === -1 ? text.length : lineEnd + 1;
          output.push(text.slice(cursor, end));
          cursor = end;
          lineStart = true;
          continue;
        }
      }
      if (text[cursor] === "`") {
        let markerEnd = cursor + 1;
        while (markerEnd < text.length && text[markerEnd] === "`") {
          markerEnd += 1;
        }
        const marker = text.slice(cursor, markerEnd);
        const closing = text.indexOf(marker, markerEnd);
        if (closing !== -1) {
          const end = closing + marker.length;
          const code = text.slice(cursor, end);
          output.push(code);
          lineStart = code.endsWith("\n");
          cursor = end;
          continue;
        }
      }
      let opening = null;
      let closing = null;
      let displayMode = false;
      if (text.startsWith("\\[", cursor) && !isEscaped(text, cursor)) {
        opening = "\\[";
        closing = "\\]";
        displayMode = true;
      } else if (text.startsWith("\\(", cursor) && !isEscaped(text, cursor)) {
        opening = "\\(";
        closing = "\\)";
      } else if (text.startsWith("$$", cursor) && !isEscaped(text, cursor)) {
        opening = "$$";
        closing = "$$";
        displayMode = true;
      } else if (text[cursor] === "$" && text[cursor + 1] !== "$" && !isEscaped(text, cursor)) {
        opening = "$";
        closing = "$";
      }
      if (opening) {
        const end = closing === "$"
          ? findClosingDollar(text, cursor + opening.length)
          : findClosingDelimiter(text, closing, cursor + opening.length);
        if (end !== -1 && end > cursor + opening.length) {
          stash(
            text.slice(cursor + opening.length, end),
            displayMode,
            text.slice(cursor, end + closing.length),
          );
          cursor = end + closing.length;
          lineStart = false;
          continue;
        }
      }
      const character = text[cursor];
      output.push(character);
      lineStart = character === "\n";
      cursor += 1;
    }
    return { source: output.join(""), math };
  }

  function markerIndex(value) {
    const text = String(value || "").trim();
    const match = new RegExp(`^${MATH_MARKER_PREFIX}(\\d+)${MATH_MARKER_SUFFIX}$`).exec(text);
    return match ? Number(match[1]) : -1;
  }

  function splitProtectedMath(value, entries) {
    const text = String(value || "");
    const parts = [];
    const pattern = new RegExp(`${MATH_MARKER_PREFIX}(\\d+)${MATH_MARKER_SUFFIX}`, "g");
    let start = 0;
    let match;
    while ((match = pattern.exec(text)) !== null) {
      if (match.index > start) {
        parts.push({ type: "text", value: text.slice(start, match.index) });
      }
      const entry = entries[Number(match[1])];
      if (entry) {
        parts.push({
          type: "math",
          value: entry.source,
          displayMode: entry.displayMode,
          raw: entry.raw,
        });
      } else {
        parts.push({ type: "text", value: match[0] });
      }
      start = match.index + match[0].length;
    }
    if (start < text.length) {
      parts.push({ type: "text", value: text.slice(start) });
    }
    return parts.length ? parts : [{ type: "text", value: text }];
  }

  function prepareMarkdown(markedLibrary, source) {
    const protectedMath = protectMath(source);
    return {
      tokens: markedLexer(markedLibrary, protectedMath.source),
      math: protectedMath.math,
    };
  }

  function mathElementForNode(node, root) {
    const element = node && typeof node.closest === "function"
      ? node
      : node && node.parentElement;
    const math = element && typeof element.closest === "function"
      ? element.closest("[data-zab-math-source]")
      : null;
    if (!math || !root || typeof root.contains !== "function" || !root.contains(math)) {
      return null;
    }
    return math;
  }

  function mathSource(element) {
    const source = element && element.dataset && element.dataset.zabMathSource;
    return typeof source === "string" ? source : null;
  }

  function replaceMathWithSource(doc, fragment) {
    const elements = fragment && typeof fragment.querySelectorAll === "function"
      ? [...fragment.querySelectorAll("[data-zab-math-source]")]
      : [];
    let replaced = 0;
    for (const element of elements) {
      const source = mathSource(element);
      if (source === null || typeof element.replaceChildren !== "function") {
        continue;
      }
      element.replaceChildren(doc.createTextNode(source));
      replaced += 1;
    }
    return replaced;
  }

  function fragmentPlainText(doc, fragment) {
    const parent = doc && (doc.body || doc.documentElement);
    if (!parent || typeof parent.append !== "function") {
      return String(fragment && fragment.textContent || "");
    }
    const host = createElement(doc, "div");
    host.setAttribute("aria-hidden", "true");
    host.style.position = "fixed";
    host.style.left = "-100000px";
    host.style.top = "0";
    host.style.width = "max-content";
    host.style.maxWidth = "none";
    host.style.opacity = "0";
    host.style.pointerEvents = "none";
    host.style.whiteSpace = "pre-wrap";
    host.append(fragment);
    parent.append(host);
    try {
      return typeof host.innerText === "string" ? host.innerText : String(host.textContent || "");
    } finally {
      host.remove();
    }
  }

  function rangeIntersectsRoot(range, root) {
    if (!range || !root) {
      return false;
    }
    if (typeof range.intersectsNode === "function") {
      try {
        return range.intersectsNode(root);
      } catch (error) {}
    }
    return root === range.startContainer
      || root === range.endContainer
      || (typeof root.contains === "function"
        && (root.contains(range.startContainer) || root.contains(range.endContainer)));
  }

  function selectionTextWithMath(doc, root, selection) {
    if (!doc || !root || !selection || selection.isCollapsed || !selection.rangeCount) {
      return null;
    }
    const parts = [];
    let containsMath = false;
    for (let index = 0; index < selection.rangeCount; index += 1) {
      const range = selection.getRangeAt(index);
      if (!rangeIntersectsRoot(range, root)) {
        continue;
      }
      const startMath = mathElementForNode(range.startContainer, root);
      const endMath = mathElementForNode(range.endContainer, root);
      if (startMath && startMath === endMath) {
        const source = mathSource(startMath);
        if (source !== null) {
          parts.push(source);
          containsMath = true;
          continue;
        }
      }
      const fragment = range.cloneContents();
      if (replaceMathWithSource(doc, fragment)) {
        containsMath = true;
      }
      parts.push(fragmentPlainText(doc, fragment));
    }
    return containsMath ? parts.join("\n") : null;
  }

  class Renderer {
    constructor(options = {}) {
      this.marked = options.marked || null;
      this.katex = options.katex || null;
    }

    render(target, source) {
      const text = String(source || "");
      const doc = target.ownerDocument;
      const prepared = prepareMarkdown(this.marked, text);
      if (!prepared.tokens) {
        target.textContent = text;
        return;
      }
      this.mathEntries = prepared.math;
      const fragment = doc.createDocumentFragment();
      this._renderBlocks(doc, fragment, prepared.tokens);
      target.replaceChildren(fragment);
      this.mathEntries = [];
    }

    handleCopy(event, root) {
      const clipboard = event && event.clipboardData;
      const doc = root && root.ownerDocument;
      const win = doc && doc.defaultView;
      if (!clipboard || typeof clipboard.setData !== "function" || !win || typeof win.getSelection !== "function") {
        return false;
      }
      const text = selectionTextWithMath(doc, root, win.getSelection());
      if (text === null) {
        return false;
      }
      clipboard.setData("text/plain", text);
      event.preventDefault();
      return true;
    }

    _renderBlocks(doc, parent, tokens) {
      for (const token of tokens || []) {
        if (!token || token.type === "space" || token.type === "def") {
          continue;
        }
        if (token.type === "heading") {
          const depth = Math.max(1, Math.min(6, Number(token.depth) || 1));
          const heading = createElement(doc, `h${depth}`);
          this._renderInline(doc, heading, token.tokens || []);
          parent.append(heading);
          continue;
        }
        if (token.type === "paragraph" || token.type === "text") {
          const protectedIndex = markerIndex(token.text);
          const protectedMath = this.mathEntries && this.mathEntries[protectedIndex];
          const math = protectedMath && protectedMath.displayMode
            ? protectedMath.source
            : blockMathSource(token.text);
          if (math !== null && math !== undefined) {
            const rawMath = protectedMath && protectedMath.displayMode
              ? protectedMath.raw
              : String(token.text || "").trim();
            parent.append(this._math(doc, math, true, rawMath));
          } else {
            const paragraph = createElement(doc, "p");
            this._renderInline(doc, paragraph, token.tokens || [{ type: "text", text: token.text || "" }]);
            parent.append(paragraph);
          }
          continue;
        }
        if (token.type === "code") {
          const pre = createElement(doc, "pre", "zab-markdown__code-block");
          const code = createElement(doc, "code");
          const language = String(token.lang || "").trim().split(/\s+/)[0];
          if (language) {
            code.dataset.language = language;
          }
          code.textContent = String(token.text || "");
          pre.append(code);
          parent.append(pre);
          continue;
        }
        if (token.type === "blockquote") {
          const quote = createElement(doc, "blockquote");
          this._renderBlocks(doc, quote, token.tokens || []);
          parent.append(quote);
          continue;
        }
        if (token.type === "list") {
          parent.append(this._list(doc, token));
          continue;
        }
        if (token.type === "table") {
          parent.append(this._table(doc, token));
          continue;
        }
        if (token.type === "hr") {
          parent.append(createElement(doc, "hr"));
          continue;
        }
        if (token.type === "html") {
          const raw = createElement(doc, "pre", "zab-markdown__raw-html");
          raw.textContent = String(token.raw || token.text || "");
          parent.append(raw);
          continue;
        }
        const fallback = String(token.text || token.raw || "");
        if (fallback) {
          const paragraph = createElement(doc, "p");
          paragraph.textContent = fallback;
          parent.append(paragraph);
        }
      }
    }

    _renderInline(doc, parent, tokens) {
      for (const token of tokens || []) {
        if (!token) {
          continue;
        }
        if (token.type === "text" || token.type === "escape") {
          const protectedParts = splitProtectedMath(token.text || token.raw || "", this.mathEntries || []);
          for (const protectedPart of protectedParts) {
            if (protectedPart.type === "math") {
              parent.append(this._math(doc, protectedPart.value, false, protectedPart.raw));
              continue;
            }
            for (const part of splitInlineMath(protectedPart.value)) {
              parent.append(part.type === "math"
                ? this._math(doc, part.value, false, part.raw)
                : doc.createTextNode(part.value));
            }
          }
          continue;
        }
        if (token.type === "strong" || token.type === "em" || token.type === "del") {
          const element = createElement(doc, token.type === "strong" ? "strong" : token.type === "em" ? "em" : "del");
          this._renderInline(doc, element, token.tokens || []);
          parent.append(element);
          continue;
        }
        if (token.type === "codespan") {
          const code = createElement(doc, "code", "zab-markdown__inline-code");
          code.textContent = String(token.text || "");
          parent.append(code);
          continue;
        }
        if (token.type === "br") {
          parent.append(createElement(doc, "br"));
          continue;
        }
        if (token.type === "link") {
          const href = safeHref(token.href);
          if (!href) {
            this._renderInline(doc, parent, token.tokens || [{ type: "text", text: token.text || "" }]);
            continue;
          }
          const link = createElement(doc, "a");
          link.href = href;
          if (href.startsWith("http://") || href.startsWith("https://")) {
            link.target = "_blank";
            link.rel = "noopener noreferrer";
          }
          if (token.title) {
            link.title = String(token.title);
          }
          this._renderInline(doc, link, token.tokens || [{ type: "text", text: token.text || href }]);
          parent.append(link);
          continue;
        }
        if (token.type === "image") {
          const image = createElement(doc, "span", "zab-markdown__image-placeholder");
          image.textContent = token.text ? `[图片：${token.text}]` : "[图片]";
          const href = safeHref(token.href);
          if (href) {
            image.title = href;
          }
          parent.append(image);
          continue;
        }
        if (token.type === "html") {
          parent.append(doc.createTextNode(String(token.raw || token.text || "")));
          continue;
        }
        if (Array.isArray(token.tokens)) {
          this._renderInline(doc, parent, token.tokens);
        } else if (token.text || token.raw) {
          parent.append(doc.createTextNode(String(token.text || token.raw)));
        }
      }
    }

    _list(doc, token) {
      const list = createElement(doc, token.ordered ? "ol" : "ul");
      if (token.ordered && Number(token.start) > 1) {
        list.start = Number(token.start);
      }
      for (const item of token.items || []) {
        const row = createElement(doc, "li");
        if (item.task) {
          row.classList.add("zab-markdown__task");
          const checkbox = createElement(doc, "input");
          checkbox.type = "checkbox";
          checkbox.checked = Boolean(item.checked);
          checkbox.disabled = true;
          checkbox.setAttribute("aria-hidden", "true");
          row.append(checkbox);
        }
        this._renderBlocks(doc, row, item.tokens || []);
        list.append(row);
      }
      return list;
    }

    _table(doc, token) {
      const wrapper = createElement(doc, "div", "zab-markdown__table-wrap");
      const table = createElement(doc, "table");
      const head = createElement(doc, "thead");
      const headRow = createElement(doc, "tr");
      (token.header || []).forEach((cell, index) => {
        const th = createElement(doc, "th");
        if (token.align && token.align[index]) {
          th.style.textAlign = token.align[index];
        }
        this._renderInline(doc, th, cell.tokens || []);
        headRow.append(th);
      });
      head.append(headRow);
      table.append(head);
      const body = createElement(doc, "tbody");
      for (const row of token.rows || []) {
        const tr = createElement(doc, "tr");
        row.forEach((cell, index) => {
          const td = createElement(doc, "td");
          if (token.align && token.align[index]) {
            td.style.textAlign = token.align[index];
          }
          this._renderInline(doc, td, cell.tokens || []);
          tr.append(td);
        });
        body.append(tr);
      }
      table.append(body);
      wrapper.append(table);
      return wrapper;
    }

    _math(doc, source, displayMode, rawSource = null) {
      const container = createElement(
        doc,
        displayMode ? "div" : "span",
        displayMode ? "zab-markdown__math zab-markdown__math--block" : "zab-markdown__math zab-markdown__math--inline",
      );
      const tex = String(source || "").trim();
      container.dataset.zabMathSource = rawSource === null || rawSource === undefined
        ? displayMode ? `$$${tex}$$` : `$${tex}$`
        : String(rawSource);
      if (!tex) {
        return container;
      }
      if (this.katex && typeof this.katex.render === "function") {
        try {
          this.katex.render(tex, container, {
            displayMode,
            output: "htmlAndMathml",
            strict: "ignore",
            throwOnError: false,
            trust: false,
          });
          return container;
        } catch (error) {}
      }
      const fallback = createElement(doc, "code", "zab-markdown__math-fallback");
      fallback.textContent = displayMode ? `$$${tex}$$` : `$${tex}$`;
      container.append(fallback);
      return container;
    }
  }

  return {
    create(options) {
      return new Renderer(options);
    },
    __test: {
      blockMathSource,
      prepareMarkdown,
      protectMath,
      rangeIntersectsRoot,
      safeHref,
      selectionTextWithMath,
      splitInlineMath,
      splitProtectedMath,
    },
  };
})();

if (typeof module !== "undefined" && module.exports) {
  module.exports = ZoteroAgentBridgeMarkdownRenderer;
}
