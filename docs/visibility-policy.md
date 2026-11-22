# Visibility policy

"The assistant sees what the user sees" is ambiguous, so this page defines it (SRS CAP-7).

The default policy, `visibility="visible"`, reads what is on screen in the current view, and the parts of the page that fold away to save room: other tabs, other carousel slides and collapsed expansions. `visibility="reachable"` also reads the rest of what is one click away. Anything read that is not on screen is marked as not currently visible.

"Tab" here means a NiceGUI element on the page, `ui.tabs` with `ui.tab_panels`, not a browser tab.

| Content | `visible` (default) | `reachable` |
|---|---|---|
| Elements in the current view | Read | Read |
| Content scrolled out of view | Read | Read |
| The active tab, step or carousel slide | Read | Read |
| An inactive tab or carousel slide | Read, marked "not visible", with any filters the user left on it | Read, marked "not visible" |
| A collapsed `ui.expansion` | Read, marked "not visible", with any filters the user left on it | Read, marked "not visible" |
| An inactive step | A stub only, naming it and what it contains | Read, marked "not visible" |
| A closed dialog, menu, popup or drawer | Not read | Read, marked "not visible" |
| `ui.tooltip` text | Not read | Not read |
| `.set_visibility(False)` | Not read | Not read |
| CSS-hidden: `hidden`, `invisible`, `sr-only`, `opacity-0`, `display: none`, `visibility: hidden`, `opacity: 0`, `font-size: 0` | Not read | Not read |
| Hidden nodes and comments inside `ui.html` and `ui.markdown` | Not read | Not read |
| `glimpse.exclude()`, or `describe(available=False)` | Withheld, and the assistant is told something is withheld | The same |
| Password and other sensitive inputs | The value is `[withheld]` | The same |
| Table columns or row keys not displayed | Not read | Not read |

With `read_inactive_sections=False`, inactive tabs, slides and collapsed expansions get a stub only, as steps do.

The rules in the lower half of the table apply inside those sections too. Text hidden with CSS on another tab is not read, and an excluded element in a collapsed expansion stays withheld.

## Why this default

Hidden content is a known injection route: hidden page text hijacked Comet's page summarizer. Reading only what the user can see also keeps answers honest, because the assistant cannot cite something the user cannot check.

The stubs matter. If a form is on a later step, the assistant can say "that is on the Payment step" instead of "not on this page".

## Tabs, slides and collapsed sections

These are the exception, because they usually fold one view to save room rather than filter it. A user on the Overview tab who asks "which customer brings in the most revenue?" expects an answer, even when that table is on the Customers tab. With only a stub, the assistant could say where to look but not give the answer.

So their content is read. Each entry sits under its section's heading, for example `## Tab: Customers`, `## Slide: Team` or `## Expansion: Order details`, and is marked `(not visible: inactive tab)`, `inactive slide` or `collapsed`. The model is told to say where it found an answer when it uses one. This does not break the honesty rule above: the user can check the answer with one click, and clicking the answer's source opens the tab, slide or section and scrolls to the element.

**Filters carry over.** Grids and charts in these sections are probed in the page as they are on screen, so the model sees what the user will see when they open the section:

| Section | In the page while it is not shown | What is read |
|---|---|---|
| A tab the user opened, then left (`ui.tab_panels(keep_alive=True)`, the default) | Still loaded, with its filters and zoom | The filtered view |
| A tab the user has not opened yet | Not loaded | The server's data, which is what it will show |
| A tab with `keep_alive=False`, or a carousel slide not shown | Not loaded. Coming back resets its grids and charts | The server's data, which is what it will show |
| A collapsed `ui.expansion` | Still loaded and only hidden, with its filters and zoom | The filtered view |

This was checked in Chrome on NiceGUI 3.19 and 4.0. Where a section is not loaded, no warning is added, because the server's data is the view.

**What is on screen comes first.** If the page does not fit the token budget, entries in these sections give way first, down to statistics without rows, before what is on screen loses any detail. The tools can still read all of it. On the reference dashboard in `examples/02_sales_dashboard.py`, the page takes about 2,600 estimated tokens per question with every tab read, up from 450 to 2,200 depending on the tab with stubs, and everything stays at full detail within the default budget of 16,000.

**Opting out.** Pass `read_inactive_sections=False` to send a stub for each instead. That suits apps where each tab is a separate view the user should choose on purpose, or pages with large sections where tokens matter more than completeness.

Steps still get stubs by default, because a later step is often a stage the user has not reached yet. `visibility="reachable"` reads them.

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

Grids and charts in other tabs, slides and collapsed sections are probed too, as described under [Tabs, slides and collapsed sections](#tabs-slides-and-collapsed-sections).

If the browser does not answer the probe within a second, the page is still captured from the server, and the model is told that filters may be missing. See [known-limits.md](known-limits.md).

A full chart series is read even when only part of it fits on screen because of chart width. Only zoom reduces what counts as seen.
