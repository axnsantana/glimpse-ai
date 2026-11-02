"""ui.run(root): a single-page app with module-level attach and sub pages."""

from nicegui import ui

import glimpse

glimpse.attach()


def home() -> None:
    ui.label('Root home content')
    ui.link('Details', '/details')


def details() -> None:
    ui.label('Root details content')


def root() -> None:
    ui.label('Shared title')
    ui.sub_pages({'/': home, '/details': details})


ui.run(root)
