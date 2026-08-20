"use strict";

var ZoteroAgentBridgeMarkdownRenderer = (() => {
  const HTML_NS = "http://www.w3.org/1999/xhtml";
  const SAFE_PROTOCOLS = new Set(["http:", "https:", "mailto:", "zotero:"]);

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
      if (text[index] === "$" && text[index + 1] !== "$") {
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
          parts.push({ type: "math", value: text.slice(index + 2, end) });
          index = end + 2;
          plainStart = index;
          continue;
        }
      }
      if (text[index] === "$" && text[index + 1] !== "$" && (index === 0 || text[index - 1] !== "\\")) {
        const end = findClosingDollar(text, index + 1);
        if (end !== -1 && end > index + 1) {
          pushPlain(index);
          parts.push({ type: "math", value: text.slice(index + 1, end) });
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

  class Renderer {
    constructor(options = {}) {
      this.marked = options.marked || null;
      this.katex = options.katex || null;
    }

    render(target, source) {
      const text = String(source || "");
      const doc = target.ownerDocument;
      const tokens = markedLexer(this.marked, text);
      if (!tokens) {
        target.textContent = text;
        return;
      }
      const fragment = doc.createDocumentFragment();
      this._renderBlocks(doc, fragment, tokens);
      target.replaceChildren(fragment);
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
          const math = blockMathSource(token.text);
          if (math !== null) {
            parent.append(this._math(doc, math, true));
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
          for (const part of splitInlineMath(token.text || token.raw || "")) {
            parent.append(part.type === "math"
              ? this._math(doc, part.value, false)
              : doc.createTextNode(part.value));
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

    _math(doc, source, displayMode) {
      const container = createElement(
        doc,
        displayMode ? "div" : "span",
        displayMode ? "zab-markdown__math zab-markdown__math--block" : "zab-markdown__math zab-markdown__math--inline",
      );
      const tex = String(source || "").trim();
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
      safeHref,
      splitInlineMath,
    },
  };
})();

if (typeof module !== "undefined" && module.exports) {
  module.exports = ZoteroAgentBridgeMarkdownRenderer;
}
