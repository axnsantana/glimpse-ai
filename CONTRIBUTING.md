# Contributing to Glimpse

Thanks for your interest in Glimpse. It is an early project with one maintainer, so help of any size makes a difference.

## Ways to help

- **Try it on your own NiceGUI app and tell us what it got wrong.** This is the most useful help of all. Open an issue with the element, what the assistant said, and what was on the screen. The "What the assistant saw" section under each answer shows what reached the model.
- **Pick an issue** labelled [good first issue](https://github.com/axnsantana/glimpse-ai/labels/good%20first%20issue) or [help wanted](https://github.com/axnsantana/glimpse-ai/labels/help%20wanted). Comment on it first, so two people do not do the same work.
- **Test a setup we have not tried for real,** such as running behind a reverse proxy. [Known limits](docs/known-limits.md) lists what has been tested.
- **Ask questions and share ideas** in [Discussions](https://github.com/axnsantana/glimpse-ai/discussions).

For anything larger than a small fix, open an issue or a discussion before writing code, so we can agree on the approach.

## Set up

With conda:

```bash
git clone https://github.com/axnsantana/glimpse-ai && cd glimpse-ai
conda env create -f environment.yml && conda activate glimpse
```

Or with a virtual environment, on Python 3.10 or later:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

No API key is needed for development. Without one, the examples run in offline demo mode.

## Run the checks

```bash
ruff check src tests examples
pytest                # Fast tests, including every example
pytest -m e2e         # Real Chrome against the real examples
```

The browser tests use your installed Chrome. Without it, run `playwright install chromium` once. CI runs all three on Python 3.10, 3.12 and 3.14, on the minimum NiceGUI version and on its pre-release.

`pytest -m live` calls a real model and costs money. Changes to the prompt, the tools or how the page is serialized need it, and the maintainer can run it for your pull request. See [tests/test_fidelity.py](tests/test_fidelity.py).

## Rules for the code

`tests/test_architecture.py` enforces the first three.

1. **Only `src/glimpse/adapters/nicegui/` imports NiceGUI.** The core stays independent of the framework, so a second framework can be added later.
2. **Private NiceGUI APIs stay in [`_compat.py`](src/glimpse/adapters/nicegui/_compat.py),** and [docs/nicegui-internals.md](docs/nicegui-internals.md) lists each one.
3. **Nothing about a session or a page lives at module level.** Two users must never see each other's data.
4. **Provider SDKs stay optional.** NiceGUI is the only required dependency, and engines import their SDK lazily.
5. **Model output never reaches HTML.** `panel.js` uses `textContent` only. Treat any change to `sanitize.py` or `panel.js` as a security change, and say so in the pull request.

## How we work

- **Example first.** A new feature starts as a runnable example in `examples/` or a change to one, and `tests/test_examples.py` runs it.
- **Trust the browser, not only the simulation.** NiceGUI's simulated user cannot see the shadow DOM, the browser probe or layout, so changes to the panel or to capture need `pytest -m e2e`.
- **Keep the record honest.** If a change fixes or adds a limit, update [docs/known-limits.md](docs/known-limits.md) and [docs/requirements-status.md](docs/requirements-status.md) in the same pull request, and say what you did not test.

## Teaching Glimpse to read a widget

This is a good first contribution. Each NiceGUI element is read by an extractor in [`extractors.py`](src/glimpse/adapters/nicegui/extractors.py), chosen by class name in `REGISTRY`. Widgets with no extractor yet, such as `ui.leaflet`, are registered with `unreadable(...)`, so the assistant says it cannot read them.

1. Write a function that takes the element and returns an `ElementSnapshot`. The `pyplot` and `echart` extractors are short examples to copy.
2. Replace the `unreadable(...)` entry in `REGISTRY` with your extractor.
3. Add a test to [tests/test_capture.py](tests/test_capture.py), modelled on `test_pyplot_is_read_when_matplotlib_is_used`.
4. Remove the widget from the list in [docs/known-limits.md](docs/known-limits.md).

If the widget keeps state only in the browser, such as a map the user has panned, the server cannot see it. Read what the server holds first, and mention the rest in the pull request.

## Pull requests

- Branch from `main`, and keep each pull request to one change.
- Make sure `ruff check` and `pytest` pass.
- Describe what changed, why, and how you tested it, including what you could not test.
- AI-assisted contributions are welcome. Say so in the description, and check the code as carefully as you would your own.

## Security

Do not report vulnerabilities in public issues. Use [private vulnerability reporting](https://github.com/axnsantana/glimpse-ai/security/advisories/new) instead. [docs/security.md](docs/security.md) describes the threat model.

## License

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).
