# Versioning

Glimpse follows [semantic versioning](https://semver.org/). While it is below 1.0, a minor version may include breaking changes, and each one is listed in `CHANGELOG.md`.

## What counts as public

Everything exported from the top-level `glimpse` package and the `glimpse.events` module:

- `attach()`, `describe()`, `exclude()`, `register_extractor()`
- The engine contract: `Engine`, `Message`, `PageContext`, `ElementSnapshot`, `TableData`, `Series`, `Tool`, and the events
- `DirectEngine`, `OfflineEngine`, `Pricing`, `Usage`, and the serializers

The rest is internal and can change without notice, including `glimpse.adapters`, the text format of the page state, and the default system prompt. Pass `system_prompt=` and `serializer=` if you depend on exact text.

## NiceGUI

The minimum version is set in `pyproject.toml` against the advisory list ([security.md](security.md)). The upper bound stays below the next major version, because Glimpse reads a few NiceGUI internals ([nicegui-internals.md](nicegui-internals.md)).

CI runs the tests against the minimum version, the latest release, and the latest pre-release. A failure on the pre-release job is a warning to act on before NiceGUI ships.
