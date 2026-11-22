# Visibility policy

"The assistant sees what the user sees" is ambiguous, so this page defines it (SRS CAP-7).

The default policy, `visibility="visible"`, reads what is on screen in the current view, and the content of the other tabs. `visibility="reachable"` also reads the rest of what is one click away. Anything read that is not on screen is marked as not currently visible.

| Content | `visible` (default) | `reachable` |
|---|---|---|
| Elements in the current view | Read | Read |
| Content scrolled out of view | Read | Read |
| The active tab, step or carousel slide | Read | Read |
| An inactive tab | Read, marked "not visible", with any filters the user left on it. With `read_inactive_tabs=False`, a stub only | Read, marked "not visible" |
| An inactive step or slide | A stub only, naming it and what it contains | Read, marked "not visible" |
| A collapsed `ui.expansion` | A stub only | Read, marked "not visible" |
| A closed dialog, menu, popup or drawer | Not read | Read, marked "not visible" |
| `ui.tooltip` text | Not read | Not read |
| `.set_visibility(False)` | Not read | Not read |
| CSS-hidden: `hidden`, `invisible`, `sr-only`, `opacity-0`, `display: none`, `visibility: hidden`, `opacity: 0`, `font-size: 0` | Not read | Not read |
| Hidden nodes and comments inside `ui.html` and `ui.markdown` | Not read | Not read |
| `glimpse.exclude()`, or `describe(available=False)` | Withheld, and the assistant is told something is withheld | The same |
| Password and other sensitive inputs | The value is `[withheld]` | The same |
| Table columns or row keys not displayed | Not read | Not read |

The rules in the lower half of the table apply inside other tabs too. Text hidden with CSS on another tab is not read, and an excluded element there stays withheld.

## Why this default

Hidden content is a known injection route: hidden page text hijacked Comet's page summarizer. Reading only what the user can see also keeps answers honest, because the assistant cannot cite something the user cannot check.

The stubs matter. If a chart is in a collapsed section, the assistant can say "that is under Details" instead of "not on this page".

## Other tabs

Tabs are the exception, because they usually split one view to save room rather than filter it. A user on the Overview tab who asks "which customer brings in the most revenue?" expects an answer, even when that table is on the Customers tab. With only a stub, the assistant could say where to look but not give the answer.

So the content of every tab is read. Each entry on another tab sits under its tab's heading, for example `## Tab: Customers`, and is marked `(not visible: inactive tab)`. The model is told to say where it found an answer when it uses one. This does not break the honesty rule above: the user can check the answer with one click, and clicking the answer's source opens the tab and scrolls to the element.

**Filters carry over.** NiceGUI keeps tab panels mounted by default (`ui.tab_panels(keep_alive=True)`), so a grid the user filtered keeps its filter after they leave its tab. The browser probe reads it there as it does on screen, and the model sees the filtered rows. A tab the user has not opened yet is not mounted in the browser. It shows the server's data when opened, so that is what is read, without a warning. With `keep_alive=False`, leaving a tab resets its grids and charts, and the server's data is again what the user will see.

**What is on screen comes first.** If the page does not fit the token budget, entries on other tabs give way first, down to statistics without rows, before what is on screen loses any detail. The tools can still read all of it. On the reference dashboard in `examples/02_sales_dashboard.py`, the page takes about 2,600 estimated tokens per question with every tab read, up from 450 to 2,200 depending on the tab with stubs, and everything stays at full detail within the default budget of 16,000.

**Opting out.** Pass `read_inactive_tabs=False` to send a stub for each inactive tab instead. That suits apps where each tab is a separate view the user should choose on purpose, or pages with large tabs where tokens matter more than completeness.

Steps and carousel slides still get stubs by default. A later step is often a stage the user has not reached yet. `visibility="reachable"` reads them.

## Scrolled-off content counts as seen

The server cannot know the scroll position without asking on every question, and a user reasonably expects "the table below" to work. So anything rendered on the page counts, whatever the scroll position.

## Applied state

For data elements, "what the user sees" means the view after their interactions:

| Element | What is applied | How it is known |
|---|---|---|
| `ui.aggrid` | Filters, quick filter, sort order, displayed columns, selection | Browser probe |
| `ui.echart` | Zoom window, legend toggles | Browser probe |
| `ui.plotly` | Axis range, legend toggles | Browser probe |
| `ui.table` | Filter, sort, page size, selection | Server |
| Inputs, tabs, expansions | Current value | Server |

Grids and charts on other tabs are probed too, as described under [Other tabs](#other-tabs).

If the browser does not answer the probe within a second, the page is still captured from the server, and the model is told that filters may be missing. See [known-limits.md](known-limits.md).

A full chart series is read even when only part of it fits on screen because of chart width. Only zoom reduces what counts as seen.
