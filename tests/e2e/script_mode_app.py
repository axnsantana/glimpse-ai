"""NiceGUI script mode: UI at global scope, re-run for each client. Replaces the old shared auto-index page."""

from nicegui import ui

import glimpse

ui.label('Script mode page')
ui.select(['A', 'B'], value='A', label='Choice')
glimpse.attach()

ui.run()
