# NiceGUI internals used by Glimpse

Glimpse reads NiceGUI's live element tree, which goes beyond its documented API in a few places. All private use is in [`_compat.py`](../src/glimpse/adapters/nicegui/_compat.py), and a test enforces that (NFR-7). Written against NiceGUI 3.18.0 and tested on 3.19.0.

| What | Used for | Status |
|---|---|---|
| `client.layout`, `client.elements`, `client.page`, `client.resolve_title()` | The root of the walk, finding the panel, the page title | Public attributes, lightly documented |
| `client.run_javascript()`, `client.on_delete()`, `app.on_connect()` | The probe, cancelling on close, module-level attach | Public |
| `element.slots`, `slot.children`, `element.parent_slot`, `element.descendants()`, `element.visible` | The walk, finding a nearby label | Public attributes, lightly documented |
| `element.html_id` | Scrolling to a cited element | Public |
| `ui.table.rows`, `.columns`, `.selected`, `.pagination`, `.filter`, `ui.aggrid.options`, `ui.echart.options`, `ui.plotly.figure`, `ui.pyplot.fig`, `.value`, `.text`, `.content` | Reading elements | Public |
| `element._props` | Labels and input types | **Private**, in `_compat.py`. `panel.py` also sets its own props, the usual way to write a component |
| `element._classes`, `element._style` | Detecting CSS-hidden content | **Private**, in `_compat.py` |
| `Slot.get_stack()` | Telling a page function from module level, without the side effect of `ui.context` creating a script-mode client | **Private**, in `_compat.py` |
| `client.sub_pages_router.current_path` | The URL of the current sub page | **Private-ish**, in `_compat.py` |
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
- **`ui.context` has side effects.** Reading it at module level before `ui.run()` creates a client and switches NiceGUI to script mode.
- **Plotly encodes NumPy arrays** as `{dtype, bdata}`, which is decoded with no NumPy import.
