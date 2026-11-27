# NiceGUI internals used by Glimpse

Glimpse reads NiceGUI's live element tree, which goes beyond its documented API in a few places. It uses no private NiceGUI attributes in Python, and a test enforces that. The public but undocumented APIs it relies on are in [`_compat.py`](../src/glimpse/adapters/nicegui/_compat.py) (NFR-7). Written against NiceGUI 3.18.0 and tested on 3.19.0, 4.0.0 and 4.1.0.

A NiceGUI maintainer confirmed the status of `props`, `classes`, `style`, `Slot.get_stack()` and `sub_pages_router.current_path` in [discussion 6521](https://github.com/zauberzeug/nicegui/discussions/6521).

| What | Used for | Status |
|---|---|---|
| `client.layout`, `client.elements`, `client.page`, `client.resolve_title()` | The root of the walk, finding the panel, opening the tab of a clicked source, the page title | Public attributes, lightly documented |
| `client.run_javascript()`, `client.on_delete()`, `app.on_connect()` | The probe, cancelling on close, module-level attach | Public |
| `element.slots`, `slot.children`, `element.parent_slot`, `element.descendants()`, `element.visible` | The walk, finding a nearby label | Public attributes, lightly documented |
| `element.html_id` | Scrolling to a cited element | Public |
| `ui.table.rows`, `.columns`, `.selected`, `.pagination`, `.filter`, `ui.aggrid.options`, `ui.echart.options`, `ui.plotly.figure`, `ui.pyplot.fig`, `.value`, `.text`, `.content` | Reading elements | Public |
| `element.props` | Labels and input types. `panel.py` also sets its own props, the usual way to write a component | Public. Returns the same `Props` dict as the private `_props` |
| `element.classes`, `element.style` | Detecting CSS-hidden content | Public. A `Classes` list and a `Style` dict, the same objects as the private attributes |
| `Slot.get_stack()` | Telling a page function from module level, without the side effect of `ui.context` creating a script-mode client | Public but undocumented, in `_compat.py` |
| `client.sub_pages_router.current_path` | The URL of the current sub page | Public but undocumented, in `_compat.py` |
| Class names such as `AgGrid` and `EChart` | Choosing an extractor with no optional imports | Stable in practice. `test_every_nicegui_class_is_dispatched_on_purpose` flags new input-like classes |

## In the browser

| What | Used for | Status |
|---|---|---|
| `getElement(id)` | Finding a component from the probe | Used in NiceGUI's own `get_client_data`, undocumented as an API |
| `.api` on the grid component | AG Grid's public API | The component attribute is internal, and the API is public |
| `.chart` on the echart component | ECharts' public `getOption()` | The component attribute is internal, and the API is public |
| `.$el` on the plotly component, with `.layout` and `.data` | Plotly's documented graph div properties | The Vue attribute is standard |
| `body--dark` class | Following dark mode | Quasar's documented class |
| `.q-header`, `.q-footer`, `.q-drawer--right` | Making room for the panel | Quasar class names, not a stable API |

## Findings from building this

These answer questions from the research plan, verified in Chrome against NiceGUI 3.19.0.

- **N2, N3: browser-only state is readable.** AG Grid's `sourceRowIndex` gives the filtered and sorted order as row indices, so no row data has to come back from the browser. That matters because a Socket.IO message over 1 MB drops the connection.
- **`ui.table` state is not browser-only.** Sort and page changes reach the server through `update:pagination`, so it needs no probe.
- **N4: drawers.** `ui.right_drawer` cannot be shared, so Glimpse does not use one. A component attached to `<body>` avoids layouts entirely.
- **N5: auto-index pages are gone.** The shared auto-index page that worried SEC1 does not exist in NiceGUI 3. Script mode replaced it and re-runs the page for each client. Requiring NiceGUI 3 removes that risk.
- **DOM IDs changed in NiceGUI 4**, from `c12` to `ng-12`. Glimpse never parses one: it uses `element.html_id` for scrolling, numeric IDs in the probe, and the tests pass the DOM element to `getElement()`, which accepts it on both versions.
- **Tab panels stay mounted after the user leaves them.** `ui.tab_panels` wraps its panels in Vue's `keep-alive` by default. A panel the user has left stays mounted, detached from the document, and `getElement()` still returns its grids and charts with their filters and zoom. A panel never opened has no components yet, so `getElement()` returns `undefined`, and the probe reports it as not mounted. With `keep_alive=False`, leaving a panel unmounts it and resets its grids and charts. `ui.carousel` does not keep slides alive, so a slide not shown is unmounted the same way. A collapsed `ui.expansion` stays mounted and is only hidden, so its grids keep their filters. Checked on 3.19.0 and 4.0.0.
- **Cleared text inputs** hold `None` on 3.19 and `''` on 4. The extractor reports `''` on both.
- **`ui.context` has side effects.** Reading it at module level before `ui.run()` creates a client and switches NiceGUI to script mode.
- **Plotly encodes NumPy arrays** as `{dtype, bdata}`, which is decoded with no NumPy import.
