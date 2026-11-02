"""Run an example on a chosen port, unchanged apart from the arguments to ui.run."""

import functools
import runpy
import sys

from nicegui import ui

path, port = sys.argv[1], int(sys.argv[2])
ui.run = functools.partial(ui.run, port=port, show=False, reload=False, show_welcome_message=False)
sys.argv = [path]
runpy.run_path(path, run_name='__main__')
