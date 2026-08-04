"""WSGI entrypoint that installs maintenance safeguards before serving."""

import app as panel
from maintenance_guard import install

install(panel)
app = panel.app
