# Security and privacy

A read-only assistant can still leak data. In several documented incidents, data left through a rendered image or link with no write tool involved. This page says what Glimpse does about it, and what stays your job.

## What Glimpse does

| Risk | Defence | Requirement |
|---|---|---|
| One user's data reaching another | Each snapshot comes from one client's element tree, and each conversation lives on that client. Nothing is stored at module level, and a test scans the code for it | SEC-1 |
| Data exfiltration through images | Images in model output are never rendered. They become a text note, so no request is made | SEC-2 |
| Script or HTML in model output | Output is parsed into a tree on the server, and the panel builds DOM nodes with `textContent`. `innerHTML` is not used anywhere, and a test enforces it | SEC-2, SEC-9 |
| Data exfiltration through links | External links are not clickable unless the host is in `allowed_link_hosts`. Same-site paths stay clickable | SEC-3 |
| Unsafe output during streaming | Every update is sanitized on the server, so a half-streamed attack is also inert | SEC-3 |
| Prompt injection through page content | Page content goes in a fenced block in the user message, never in the system prompt. Content cannot close its own fence. The system prompt tells the model to treat it as data, and hidden text is not read at all | SEC-4 |
| Passwords and secrets | Password inputs, and inputs and columns with names like `api_key` or `credit_card`, are withheld by default. Add your own with `exclude_fields=` and `glimpse.exclude()` | SEC-5 |
| Compliance | The `redact=` hook runs on every string in the snapshot and on the user's question, before any engine sees them | SEC-7 |
| API key exposure | All model calls run on the server. The browser only ever receives sanitized text | SEC-8 |
| Dependence on a vendor | The core has no cloud dependency | SEC-10 |

## What is sent to the model provider

For each question, the engine receives a snapshot of this user's page, taken when they ask. With the defaults, it holds:

- **What is on screen**, including content scrolled out of view, with the user's filters, sort order, chart zoom and input values.
- **The content of inactive tabs, carousel slides and collapsed expansions**, each marked as not visible. A grid the user filtered keeps its filter after they leave its tab. A tab never opened is read from the server, as it would show when opened. This means Glimpse sends more than what the user is looking at right now: it sees what is on the screen, including the parts folded away.
- **A stub for each inactive step** of a `ui.stepper`, naming it and what it contains.
- **Your developer context** from `context=` and `glimpse.describe()`, the question, and earlier questions and answers as text.

Large tables and series are reduced to statistics and a sample, such as "Showing 50 of 12,000 rows". The model can fetch more rows through read-only tools, which read the same snapshot and nothing else.

**Not sent:** content hidden with CSS or `set_visibility(False)`, closed dialogs, menus and drawers, tooltips, table columns that are not displayed, and anything withheld with the controls below. [visibility-policy.md](visibility-policy.md) has the full table, and [data-flow.md](data-flow.md) says where each engine sends it.

### Controlling what is sent

| Control | Effect |
|---|---|
| `read_inactive_sections=False` | Inactive tabs, slides and collapsed expansions are sent as a stub naming them, not their content. This was the behaviour before 0.3 |
| `glimpse.exclude(element)` or `glimpse.describe(element, available=False)` | The element and everything inside it are withheld, and the assistant is told something is withheld. `available` can be a function, so an element can come and go |
| `exclude_fields=[...]` | Columns and inputs whose names match a string or a compiled regular expression are withheld. Names like `password`, `api_key` or `credit_card` are withheld by default |
| `redact=` | Runs on every string in the snapshot and on the question, before any engine sees them |
| `visibility="reachable"` | Sends more, not less: closed dialogs, menus, drawers and inactive steps too |
| `engine="offline"`, or a local model | Nothing leaves your infrastructure |

Withheld elements are dropped while the page is read, so the tools, the inspector and the conversation history never see them. Use these controls for anything a model provider should not receive, even when the user is allowed to see it.

## Prompt injection is limited, not solved

Language models cannot reliably separate instructions from data. A table cell that says "ignore your instructions" still reaches the model, because it is on the page. Fencing makes the model less likely to obey it, and the panel's sanitizer limits what a hijacked answer can do: it cannot make the browser send data anywhere. But a hijacked model can still give the user a wrong or misleading answer. Treat answers from pages that show untrusted text accordingly.

## Developer context is not secret

Anything in `context=` or `glimpse.describe()` is sent to the model, and **a determined user can get the assistant to repeat it**. Never put secrets, credentials or data a user should not see in it.

The same applies to `system_prompt=`.

## The inspector

"What the assistant saw" shows end users the page state sent for an answer. That is data from their own page: what is on their screen and, by default, the content of its other tabs, slides and collapsed sections, as described [above](#what-is-sent-to-the-model-provider). The system prompt and developer context stay out of it unless you pass `inspector="full"`, which is meant for development. It is still not a security boundary, for the reason above. Pass `inspector=False` to turn it off.

## What stays your job

- Authorization. Glimpse shows the assistant what your page shows the user, so a page that shows too much will leak too much.
- Choosing where data may go. Read the table in [data-flow.md](data-flow.md).
- Sanitizing your own use of `ui.html` and `ui.markdown`.
- Rate limits and app-wide spending limits. Per-session limits are built in, but they reset on reload, so they do not stop a determined user. Use `on_usage` and your own accounting if that matters.
- Custom engines. Sanitizing and fencing still apply to them, but a tool your engine adds is yours to secure.
- ADK agents. Glimpse adds only its read-only page tools. Tools, callbacks and sub-agents you give your agent run with whatever access your code gives them, and a prompt injection in page text can try to call them. Keep tools that change things out of an agent that reads untrusted pages, or put a confirmation step in front of them.
- Google Cloud credentials. Vertex AI calls use the server's Application Default Credentials. Give the service account only the Vertex AI User role, so a leaked credential cannot do more.

## Minimum NiceGUI version

The minimum is **3.19.0**, set against all 24 advisories published in the NiceGUI repository as of 2026-11-22. It is the first release with a fix for all of them. Do not go lower: one of the three fixed in 3.19.0, [GHSA-m47w-xwfc-82pf](https://github.com/zauberzeug/nicegui/security/advisories/GHSA-m47w-xwfc-82pf), is an XSS through `:`-prefixed keys in `ui.aggrid` and `ui.echart` data, such as DataFrame column names. Re-check the list before each Glimpse release, because this list grows quickly:

```bash
gh api '/repos/zauberzeug/nicegui/security-advisories?per_page=100' --jq '.[] | [.ghsa_id, .severity, .vulnerabilities[0].patched_versions] | @tsv'
```

## Reporting a vulnerability

Report privately through [GitHub security advisories](https://github.com/axnsantana/glimpse-ai/security/advisories/new), not in a public issue.
