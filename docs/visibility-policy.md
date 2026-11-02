# Visibility policy

"The assistant sees what the user sees" is ambiguous, so this page defines it (SRS CAP-7).

The default policy, `visibility="visible"`, reads what is on screen in the current view. `visibility="reachable"` also reads content one click away, and marks it as not currently visible.

| Content | `visible` (default) | `reachable` |
|---|---|---|
| Elements in the current view | Read | Read |
| Content scrolled out of view | Read | Read |
| The active tab, step or carousel slide | Read | Read |
| An inactive tab, step or slide | A stub only, naming it and what it contains | Read, marked "not visible" |
| A collapsed `ui.expansion` | A stub only | Read, marked "not visible" |
| A closed dialog, menu, popup or drawer | Not read | Read, marked "not visible" |
| `ui.tooltip` text | Not read | Not read |
| `.set_visibility(False)` | Not read | Not read |
| CSS-hidden: `hidden`, `invisible`, `sr-only`, `opacity-0`, `display: none`, `visibility: hidden`, `opacity: 0`, `font-size: 0` | Not read | Not read |
| Hidden nodes and comments inside `ui.html` and `ui.markdown` | Not read | Not read |
| `glimpse.exclude()`, or `describe(available=False)` | Withheld, and the assistant is told something is withheld | The same |
| Password and other sensitive inputs | The value is `[withheld]` | The same |
| Table columns or row keys not displayed | Not read | Not read |

## Why this default

Hidden content is a known injection route: hidden page text hijacked Comet's page summarizer. Reading only what the user can see also keeps answers honest, because the assistant cannot cite something the user cannot check.

The stubs matter. If a chart is on an inactive tab, the assistant can say "that is on the Orders tab" instead of "not on this page".

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

If the browser does not answer the probe within a second, the page is still captured from the server, and the model is told that filters may be missing. See [known-limits.md](known-limits.md).

A full chart series is read even when only part of it fits on screen because of chart width. Only zoom reduces what counts as seen.
