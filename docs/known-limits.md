# Known limits

This is version 0.1, and these are the limits we know of.

## How far it has been tested

**Tested with a real model.** Claude Opus 5.5 answered all 26 reference questions correctly, with a citation on each, for about $0.35. It also picked the right tools on a 20,000-row table, answered from a filter set only in the browser, flagged a prompt injection in a table cell, and declined an exfiltration request. Treat this as an early sign:

- It was one run, on one dashboard, with questions whose answers are mostly in the context.
- The scorer only checks that the expected values appear in the answer.
- The reference questions run with the browser probe off. Browser filters were checked separately, in a few real-browser questions.
- No pass threshold has been set yet, because spike S1 has not run.

**Not tested with a real provider:**

- **OpenAI.** The code runs against the real SDK and a local server that imitates the API, but no request has reached OpenAI. The `gpt-5` default is an assumption.
- **Local models.** `ollama:` was only tested against the same local server, so the quality drop from a cloud model is unknown.
- **Other Claude models.** Only Opus 5.5 was run. The fallback path was never triggered by a real refusal.
- **Vertex AI.** Claude and Gemini on Vertex AI run against the real SDKs and a local server, with stand-in Google credentials. No request has reached Google Cloud, so region availability, quotas and real credential errors are untested.
- **Gemini.** No Gemini model has answered a real question, so its quality on page questions is unknown. The `gemini-flash-latest` default is an assumption, and the token estimate was calibrated on Claude.
- **The council engine.** Its flow is tested with scripted models only. Spike S3 has not run, so whether its extra calls give better answers is unknown. An approved draft appears in one piece rather than streaming.
- **The ADK engine.** Tested with the real ADK runner and a scripted model, and with ADK's Gemini class against a local server. No real agent has run. Only `sub_agents` trees get the page tools, and ADK 2's graph `Workflow` API was not tried.
- **Python 3.10.** google-genai and google-adk need Python 3.11 or later, so on 3.10 only Claude on Vertex AI is available from Google Cloud.

**Not tested in real conditions:**

- **Behind nginx** or any other proxy, so NFR-2 is only partly met. Streams send a progress update during silence, and closing a tab cancels the model call, but proxies may behave differently.
- **Assumption A4 is unchanged.** Direct demand for this product is still unproven.

## Capture

- **Client-side edits in AG Grid are not seen.** The server reads its own copy of the rows and uses the browser only for their order and filtering. Call `grid.load_client_data()` to sync edits first.
- **Computed AG Grid columns** (`valueGetter`) and Quasar columns with a function as `field` cannot be read. The assistant is told which ones.
- **`ui.table` filter and sort** are reproduced on the server using Quasar's default rules, so a custom `sort` or `filter-method` on the client will not match.
- **Above 50,000 displayed grid rows**, the probe reports only the first 50,000, and the context says so.
- **Widgets without readable data:** `ui.leaflet`, `ui.scene`, `ui.image`, `ui.video`, `ui.audio`, `ui.highchart`, `ui.altair`, `ui.anywidget`, `ui.xterm` and unknown custom components appear only as "no readable data". Screenshots (CAP-8) are not implemented. You can add support for a widget with `glimpse.register_extractor()`.
- **`ui.pyplot`** reads line data and titles only, not bars or scatter plots.
- **Unusual ECharts or Plotly data shapes** may read as empty or partial, for example custom series. Check the inspector.
- **Colour-based hiding**, such as white text on white, is not detected.
- **Non-Latin text** is read normally, but the offline demo engine only matches ASCII words.

## Conversations

- A conversation lasts for one page load. Reloading or navigating starts a new one (open question A5 in the research plan).
- With several server workers, each client stays on the worker that served it, as is usual for NiceGUI. Glimpse adds nothing for shared state.
- Earlier answers go back to the model as text only, so reasoning from earlier turns does not carry over.

## Tokens

- `budget=` uses an estimate unless you pass `count_tokens=`. Real requests stayed within budget in every measured case, the closest at 81% of a 6,000-token budget, but this is not a hard guarantee. See [models.md](models.md).
- It limits input per request only. Output is limited separately, by `DirectEngine(max_output_tokens=...)`, and each tool round is its own request.
- The direct engine's prompt and tools take about 2,100 estimated tokens, so `attach()` refuses a budget under about 5,600 for it.
- The estimate was calibrated against Claude. Other models tokenize differently.

## Layout

- Opening the panel with `push=True` changes the page's right edge through a small stylesheet that only applies while the panel is open. Elements positioned with `position: fixed` that are not Quasar headers, footers or drawers may end up under the panel. Pass `push=False` to avoid this.
- The panel uses z-index 5900, under Quasar dialogs (6000) and above drawers. A page using higher values can cover it.

## Python below 3.12

The tests pass on Python 3.10, but stopping the server at the moment an answer finishes can delay shutdown by two seconds and log `Could not cancel ... tasks`. The stuck task is NiceGUI's outbox loop: on these Python versions `asyncio.wait_for` can swallow a cancel that lands in the same tick as its event. It only affects shutdown, not answers. We saw it only in tests that exit right after an answer, and a simple NiceGUI page with no Glimpse did not trigger it, so Glimpse's timing may contribute.

## Not in this version

Actions on the page, a second framework, a second agent framework besides ADK, an AG-UI inbound adapter and `glimpse[mcp]`. See [requirements-status.md](requirements-status.md).
