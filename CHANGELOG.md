# Changelog

## Unreleased

- **Other tabs are read.** The assistant now reads the content of every tab, not only the selected one, because tabs usually split one view to save room. Entries on other tabs are marked as not on screen, and the model is told to say where it found an answer. Pass `read_inactive_tabs=False` to `attach()` to send only a summary of each tab, as before. Steps, carousel slides and collapsed sections are unchanged.
- **Filters on other tabs carry over.** Grids and charts on other tabs are probed too. A grid the user filtered keeps its filter after they leave its tab, and the assistant sees the filtered rows. A tab the user has not opened yet is read from the server, which is what it will show.
- **What is on screen keeps its detail.** When the page does not fit the budget, entries on other tabs give way first. `ContextReport.off_screen_detail_level` reports how far they fell, and `Detail.off_screen` lets a custom serializer do the same.
- **Sources open their tab.** Clicking a source on another tab, or in a collapsed section, opens it and scrolls to the element. Before, the click did nothing.

## 0.2.0 (2026-11-10)

- **NiceGUI 4.** Glimpse now supports NiceGUI 3.19 and 4. NiceGUI 4 needs Python 3.11, so on Python 3.10 pip keeps installing 3.19.
- A text input cleared with its clear button now reads as empty (`''`) on every NiceGUI version. On 3.19 the assistant used to see `null`.

## 0.1.0 (2026-11-09)

The first MVP: NiceGUI only, read-only, with direct, council, ADK, offline and custom engines. See `docs/requirements-status.md`.

- **Vertex AI.** `vertex:claude-...` and `vertex:gemini-...` models, configured with `project=` and `location=` or `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION`, using Google credentials instead of an API key. Gemini also works with an API key, as `gemini:...`. New extras: `vertex`, `gemini` and `adk`.
- **Council engine.** `engine="council"` or `CouncilEngine`: an actor drafts, a critic checks the draft against the page with the same tools, and a mediator settles any disagreement. Not yet measured against the direct engine.
- **ADK engine.** Pass a Google ADK agent as `engine=`, or use `engine="adk"`. Glimpse adds the page tools and its rules for page data to a copy of the agent for each question.
- **Releases.** Publishing a GitHub release publishes to PyPI through trusted publishing. See `docs/releasing.md`.
- The sdist now includes only an explicit list of folders.

The PyPI package is `glimpse-ai`, because the name `glimpse` is taken. It is imported as `glimpse`. The earlier `0.0.1` on PyPI was an empty placeholder that reserved the name.
