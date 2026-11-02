// The browser side of the assistant panel.
//
// Isolation: everything lives in a Shadow DOM attached to <body>, so host selectors cannot
// reach the panel and panel CSS cannot reach the host. A host rule such as
// `* { color: red !important }` still matches the shadow host itself, and the host's values
// would be inherited. So nothing here inherits from the host: `.root` resets everything and
// is the top of the panel's own inheritance (UI-3).
//
// Safety: the server sends a sanitized tree of blocks, and this file builds DOM nodes from
// it using textContent only. Nothing from a model is ever parsed as HTML, so no image loads
// and no script runs (SEC-2). Do not add innerHTML here.

const STYLE = `
:host { all: initial; }
.root { all: initial; display: block; --bg: #ffffff; --bg-soft: #f5f6f8; --bg-hover: #eceef2; --fg: #1c2024; --fg-soft: #5f6773;
  --line: #dfe2e7; --accent: #3b5bdb; --accent-fg: #ffffff; --danger: #c92a2a; --mark: #e7ecff;
  font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  font-size: 14px; line-height: 1.5; color: var(--fg); }
.root.dark { --bg: #1b1e23; --bg-soft: #24282e; --bg-hover: #2d3238; --fg: #e8eaed; --fg-soft: #a2a9b3;
  --line: #363b43; --accent: #7c93f5; --accent-fg: #10131a; --danger: #ff8787; --mark: #2d3556; }
*, *::before, *::after { box-sizing: border-box; }
button, textarea { font: inherit; color: inherit; }
button { cursor: pointer; border: 0; background: none; padding: 0; }
button:focus-visible, textarea:focus-visible, summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }

.launcher { position: fixed; right: 20px; bottom: 20px; height: 44px; padding: 0 18px; border-radius: 22px;
  background: var(--accent); color: var(--accent-fg); font-weight: 600; box-shadow: 0 4px 14px rgba(0,0,0,.25);
  display: flex; align-items: center; gap: 8px; }
.launcher:hover { filter: brightness(1.08); }

.panel { position: fixed; top: 0; right: 0; bottom: 0; width: var(--width); max-width: 100vw; display: flex;
  flex-direction: column; background: var(--bg); border-left: 1px solid var(--line);
  box-shadow: -4px 0 18px rgba(0,0,0,.08); }
.panel[hidden], .launcher[hidden] { display: none; }

header { display: flex; align-items: center; gap: 8px; padding: 10px 12px 10px 16px; border-bottom: 1px solid var(--line); }
header h2 { margin: 0; flex: 1; font-size: 15px; font-weight: 600; }
.icon { min-width: 30px; height: 30px; padding: 0 8px; border-radius: 6px; color: var(--fg-soft); font-size: 13px; }
.icon:hover { background: var(--bg-hover); color: var(--fg); }

.banner { padding: 8px 16px; background: var(--bg-soft); color: var(--fg-soft); border-bottom: 1px solid var(--line); font-size: 12.5px; }

.log { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 16px; overscroll-behavior: contain; }
.empty { color: var(--fg-soft); margin: auto 0; display: flex; flex-direction: column; gap: 12px; }
.empty p { margin: 0; }
.suggestions { display: flex; flex-direction: column; gap: 6px; align-items: flex-start; }
.suggestion { text-align: left; padding: 7px 12px; border: 1px solid var(--line); border-radius: 8px; color: var(--fg); }
.suggestion:hover { background: var(--bg-hover); }

.question { align-self: flex-end; max-width: 88%; padding: 8px 12px; border-radius: 12px 12px 2px 12px;
  background: var(--mark); white-space: pre-wrap; overflow-wrap: anywhere; }
.answer { display: flex; flex-direction: column; gap: 8px; overflow-wrap: anywhere; }
.turn { display: flex; flex-direction: column; gap: 10px; }

.progress { color: var(--fg-soft); font-size: 13px; display: flex; align-items: center; gap: 8px; }
.progress::before { content: ""; width: 8px; height: 8px; border-radius: 50%; background: var(--accent); animation: pulse 1.1s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { opacity: .25; } 50% { opacity: 1; } }
@media (prefers-reduced-motion: reduce) { .progress::before { animation: none; } }

.error { color: var(--danger); }
.notice { color: var(--fg-soft); font-size: 12.5px; }
.note { color: var(--fg-soft); font-style: italic; }
.body > * { margin: 0 0 8px; }
.body > *:last-child { margin-bottom: 0; }
.body h1, .body h2, .body h3, .body h4 { font-size: 14px; font-weight: 650; margin: 12px 0 4px; }
.body ul, .body ol { padding-left: 20px; }
.body li { margin: 2px 0; }
.body blockquote { border-left: 3px solid var(--line); padding-left: 10px; color: var(--fg-soft); margin-left: 0; margin-right: 0; }
.body hr { border: 0; border-top: 1px solid var(--line); }
.body code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12.5px; background: var(--bg-soft); padding: 1px 4px; border-radius: 4px; }
.body pre { background: var(--bg-soft); padding: 10px; border-radius: 6px; overflow-x: auto; margin: 0 0 8px; }
.body pre code { background: none; padding: 0; }
.body a { color: var(--accent); }
.tablewrap { overflow-x: auto; }
.body table { border-collapse: collapse; font-size: 13px; }
.body th, .body td { border: 1px solid var(--line); padding: 3px 8px; text-align: left; }
.body th { background: var(--bg-soft); font-weight: 600; }
.ref { display: inline; font-size: 11.5px; padding: 0 5px; border-radius: 4px; background: var(--mark); color: var(--accent); white-space: nowrap; vertical-align: 1px; }
.ref:hover { filter: brightness(.95); }

.meta { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; font-size: 12px; color: var(--fg-soft); }
.source { padding: 2px 8px; border: 1px solid var(--line); border-radius: 10px; color: var(--fg-soft); font-size: 12px; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.source:hover { background: var(--bg-hover); color: var(--fg); }

details { font-size: 12.5px; color: var(--fg-soft); }
summary { cursor: pointer; }
.inspection { margin-top: 8px; display: flex; flex-direction: column; gap: 8px; }
.inspection pre { margin: 0; max-height: 320px; overflow: auto; padding: 8px; background: var(--bg-soft); border-radius: 6px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 11.5px; white-space: pre-wrap; overflow-wrap: anywhere; color: var(--fg); }
.meter { display: flex; height: 6px; border-radius: 3px; background: var(--bg-hover); overflow: hidden; }
.meter span { background: var(--accent); }
.parts { display: grid; grid-template-columns: 1fr auto; gap: 1px 12px; }

form { border-top: 1px solid var(--line); padding: 10px 12px; display: flex; gap: 8px; align-items: flex-end; }
textarea { flex: 1; resize: none; border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; background: var(--bg); min-height: 38px; max-height: 140px; }
.send { height: 38px; padding: 0 14px; border-radius: 8px; background: var(--accent); color: var(--accent-fg); font-weight: 600; }
.send:hover { filter: brightness(1.08); }
.send.stop { background: var(--bg-hover); color: var(--fg); }
@media (max-width: 640px) { .panel { width: 100vw; } }
`;

// Only applies while the panel is open with push on. It only moves the page's edge.
const PUSH_STYLE = `
body.glimpse-open { padding-right: var(--glimpse-width) !important; }
body.glimpse-open .q-header, body.glimpse-open .q-footer { right: var(--glimpse-width) !important; }
body.glimpse-open .q-drawer--right { right: var(--glimpse-width) !important; }
@media (max-width: 640px) { body.glimpse-open { padding-right: 0 !important; } }
`;

function make(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export default {
  template: '<span style="display: none"></span>',
  props: { config: Object },
  mounted() {
    this.turnNodes = new Map();
    this.follow = true;
    this.buildPanel();
    this.setOpen(Boolean(this.config.open));
  },
  unmounted() {
    this.setPushed(false);
    this.themeObserver?.disconnect();
    this.host?.remove();
  },
  methods: {
    buildPanel() {
      const config = this.config;
      this.host = make("div");
      this.host.dataset.glimpse = "panel";
      this.host.style.cssText = "position: fixed; z-index: 5900; top: 0; left: 0; width: 0; height: 0;";
      document.body.appendChild(this.host);
      const shadow = this.host.attachShadow({ mode: "open" });
      shadow.appendChild(make("style", "", STYLE));
      this.root = make("div", "root");
      this.root.style.setProperty("--width", `${config.width}px`);
      shadow.appendChild(this.root);

      this.launcher = make("button", "launcher", `Ask`);
      this.launcher.type = "button";
      this.launcher.setAttribute("aria-label", `Open ${config.title}`);
      this.launcher.addEventListener("click", () => this.setOpen(true));
      this.root.appendChild(this.launcher);

      this.panel = make("section", "panel");
      this.panel.setAttribute("aria-label", config.title);
      this.root.appendChild(this.panel);

      const header = make("header");
      header.appendChild(make("h2", "", config.title));
      const clear = make("button", "icon", "New chat");
      clear.type = "button";
      clear.addEventListener("click", () => this.$emit("glimpse_clear", {}));
      header.appendChild(clear);
      const close = make("button", "icon", "Close");
      close.type = "button";
      close.addEventListener("click", () => this.setOpen(false));
      header.appendChild(close);
      this.panel.appendChild(header);

      if (config.banner) this.panel.appendChild(make("div", "banner", config.banner));

      this.log = make("div", "log");
      this.log.setAttribute("aria-live", "polite");
      this.log.addEventListener("scroll", () => {
        this.follow = this.log.scrollHeight - this.log.scrollTop - this.log.clientHeight < 40;
      });
      this.panel.appendChild(this.log);
      this.showEmpty();

      const form = make("form");
      this.input = make("textarea");
      this.input.rows = 1;
      this.input.placeholder = "Ask about this page";
      this.input.setAttribute("aria-label", "Your question");
      this.input.addEventListener("input", () => this.fitInput());
      this.input.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
          event.preventDefault();
          this.submit();
        }
        event.stopPropagation();
      });
      this.input.addEventListener("keyup", (event) => event.stopPropagation());
      form.appendChild(this.input);
      this.sendButton = make("button", "send", "Send");
      this.sendButton.type = "submit";
      form.appendChild(this.sendButton);
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        this.submit();
      });
      this.panel.appendChild(form);

      this.panel.addEventListener("keydown", (event) => {
        if (event.key === "Escape") this.setOpen(false);
      });

      const syncTheme = () => this.root.classList.toggle("dark", document.body.classList.contains("body--dark"));
      syncTheme();
      this.themeObserver = new MutationObserver(syncTheme);
      this.themeObserver.observe(document.body, { attributes: true, attributeFilter: ["class"] });
    },
    fitInput() {
      this.input.style.height = "auto";
      this.input.style.height = `${Math.min(this.input.scrollHeight + 2, 140)}px`;
    },
    submit() {
      if (this.busy) {
        this.$emit("glimpse_cancel", {});
        return;
      }
      const text = this.input.value.trim();
      if (!text) return;
      this.input.value = "";
      this.fitInput();
      this.ask(text);
    },
    ask(text) {
      this.follow = true;
      this.$emit("glimpse_send", { text });
    },
    setOpen(open) {
      this.panel.hidden = !open;
      this.launcher.hidden = open;
      this.setPushed(open && this.config.push);
      if (open) this.input.focus();
    },
    setPushed(pushed) {
      if (pushed && !document.getElementById("glimpse-push-style")) {
        const style = make("style", "", PUSH_STYLE);
        style.id = "glimpse-push-style";
        document.head.appendChild(style);
      }
      document.body.style.setProperty("--glimpse-width", `${this.config.width}px`);
      document.body.classList.toggle("glimpse-open", pushed);
      // Charts and grids re-measure themselves on this.
      window.dispatchEvent(new Event("resize"));
    },
    showEmpty() {
      this.log.replaceChildren();
      const empty = make("div", "empty");
      empty.appendChild(make("p", "", "Ask about anything on this page. The assistant reads the page when you send your question."));
      if (this.config.suggestions.length) {
        const list = make("div", "suggestions");
        for (const suggestion of this.config.suggestions) {
          const button = make("button", "suggestion", suggestion);
          button.type = "button";
          button.addEventListener("click", () => this.ask(suggestion));
          list.appendChild(button);
        }
        empty.appendChild(list);
      }
      this.log.appendChild(empty);
    },
    clear() {
      this.turnNodes.clear();
      this.setBusy(false);
      this.showEmpty();
    },
    setBusy(busy) {
      this.busy = busy;
      this.sendButton.textContent = busy ? "Stop" : "Send";
      this.sendButton.classList.toggle("stop", busy);
    },
    upsert(turn) {
      let nodes = this.turnNodes.get(turn.id);
      if (!nodes) {
        if (this.turnNodes.size === 0) this.log.replaceChildren();
        const root = make("div", "turn");
        root.appendChild(make("div", "question", turn.question));
        const answer = make("div", "answer");
        root.appendChild(answer);
        this.log.appendChild(root);
        nodes = { root, answer, inspection: null, open: false };
        this.turnNodes.set(turn.id, nodes);
      }
      this.renderTurn(turn, nodes);
      const active = ["reading", "thinking", "streaming"].includes(turn.status);
      this.setBusy(active);
      if (this.follow) this.log.scrollTop = this.log.scrollHeight;
    },
    renderTurn(turn, nodes) {
      const answer = nodes.answer;
      const details = nodes.details;
      answer.replaceChildren();
      const sources = new Map(turn.sources.map((source) => [source.id, source]));
      if (turn.blocks.length) {
        const body = make("div", "body");
        for (const block of turn.blocks) body.appendChild(this.renderBlock(block, sources));
        answer.appendChild(body);
      }
      if (turn.progress) answer.appendChild(make("div", "progress", turn.progress));
      if (turn.error) answer.appendChild(make("div", "error", turn.error));
      for (const notice of turn.notices) answer.appendChild(make("div", "notice", notice));
      if (turn.sources.length) {
        const meta = make("div", "meta");
        meta.appendChild(make("span", "", "Sources:"));
        for (const source of turn.sources) {
          const chip = make("button", "source", source.label);
          chip.type = "button";
          chip.title = `Show ${source.label} on the page`;
          chip.addEventListener("click", () => this.reveal(source));
          meta.appendChild(chip);
        }
        answer.appendChild(meta);
      }
      if (this.config.inspector && !["reading", "thinking", "streaming"].includes(turn.status) && turn.tokens !== null) {
        answer.appendChild(details || this.buildDetails(turn, nodes));
      }
    },
    buildDetails(turn, nodes) {
      const details = make("details");
      details.appendChild(make("summary", "", "What the assistant saw"));
      nodes.details = details;
      nodes.inspection = make("div", "inspection");
      details.appendChild(nodes.inspection);
      details.addEventListener("toggle", () => {
        if (details.open && !nodes.inspection.childElementCount) this.$emit("glimpse_inspect", { id: turn.id });
      });
      return details;
    },
    showInspection(data) {
      const nodes = this.turnNodes.get(data.id);
      if (!nodes || !nodes.inspection) return;
      const box = nodes.inspection;
      box.replaceChildren();
      if (!data.available) {
        box.appendChild(make("div", "", "The page was not captured for this answer."));
        return;
      }
      box.appendChild(make("div", "", `${data.tokens.toLocaleString()} of ${data.budget.toLocaleString()} budget tokens, estimated.`));
      const meter = make("div", "meter");
      const bar = make("span");
      bar.style.width = `${Math.min(100, (100 * data.tokens) / data.budget)}%`;
      meter.appendChild(bar);
      box.appendChild(meter);
      const parts = make("div", "parts");
      for (const [name, tokens] of data.parts) {
        parts.appendChild(make("span", "", name));
        parts.appendChild(make("span", "", tokens.toLocaleString()));
      }
      box.appendChild(parts);
      if (data.dropped_messages) box.appendChild(make("div", "", `${data.dropped_messages} older message(s) were left out to fit the budget.`));
      if (data.usage && !data.usage.estimated) {
        const cost = data.usage.cost === null ? "" : `, $${data.usage.cost.toFixed(4)}`;
        box.appendChild(make("div", "", `Model reported ${data.usage.input.toLocaleString()} in, ${data.usage.output.toLocaleString()} out${cost}.`));
      }
      if (data.tool_calls.length) {
        box.appendChild(make("div", "", "Tools used:"));
        box.appendChild(make("pre", "", data.tool_calls.map((call) => `${call.name} ${call.arguments}`).join("\n")));
      }
      if (data.system_prompt) {
        box.appendChild(make("div", "", "System prompt:"));
        box.appendChild(make("pre", "", data.system_prompt));
      }
      if (data.developer_context) {
        box.appendChild(make("div", "", "Developer context:"));
        box.appendChild(make("pre", "", data.developer_context));
      }
      box.appendChild(make("div", "", "Page state sent:"));
      box.appendChild(make("pre", "", data.page));
    },
    reveal(source) {
      const target = source.dom ? document.getElementById(source.dom) : null;
      if (!target) return;
      target.scrollIntoView({ behavior: "smooth", block: "center" });
      target.animate(
        [{ outline: "3px solid #3b5bdb", outlineOffset: "2px" }, { outline: "3px solid transparent", outlineOffset: "2px" }],
        { duration: 1600, easing: "ease-out" },
      );
    },
    renderBlock(block, sources) {
      switch (block.t) {
        case "h":
          return this.withInline(make(`h${Math.min(block.level + 2, 4)}`), block.c, sources);
        case "code": {
          const pre = make("pre");
          pre.appendChild(make("code", "", block.v));
          return pre;
        }
        case "hr":
          return make("hr");
        case "quote":
          return this.withInline(make("blockquote"), block.c, sources);
        case "ul":
        case "ol": {
          const list = make(block.t);
          for (const item of block.items) list.appendChild(this.withInline(make("li"), item, sources));
          return list;
        }
        case "table": {
          const wrap = make("div", "tablewrap");
          const table = make("table");
          const head = make("tr");
          for (const cell of block.head) head.appendChild(this.withInline(make("th"), cell, sources));
          table.appendChild(head);
          for (const row of block.rows) {
            const tr = make("tr");
            for (const cell of row) tr.appendChild(this.withInline(make("td"), cell, sources));
            table.appendChild(tr);
          }
          wrap.appendChild(table);
          return wrap;
        }
        default:
          return this.withInline(make("p"), block.c || [], sources);
      }
    },
    withInline(parent, nodes, sources) {
      for (const node of nodes) parent.appendChild(this.renderInline(node, sources));
      return parent;
    },
    renderInline(node, sources) {
      switch (node.t) {
        case "b":
          return this.withInline(make("strong"), node.c, sources);
        case "i":
          return this.withInline(make("em"), node.c, sources);
        case "code":
          return make("code", "", node.v);
        case "note":
          return make("span", "note", node.v);
        case "a": {
          // The server already checked this. The browser refuses anything else as a second line of defence.
          if (!/^(https?:\/\/|\/(?![\/\\]))/i.test(node.href)) return this.withInline(make("span"), node.c, sources);
          const link = this.withInline(make("a"), node.c, sources);
          link.href = node.href;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          return link;
        }
        case "ref": {
          const source = sources.get(node.id);
          const chip = make("button", "ref", source ? source.label : node.id);
          chip.type = "button";
          if (source) chip.addEventListener("click", () => this.reveal(source));
          return chip;
        }
        default:
          return document.createTextNode(node.v);
      }
    },
  },
};
