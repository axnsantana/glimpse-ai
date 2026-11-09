# Changelog

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
