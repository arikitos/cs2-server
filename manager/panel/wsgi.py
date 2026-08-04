"""WSGI entrypoint that installs panel safeguards before serving."""

import app as panel
from config_guard import install as install_config_guard
from maintenance_guard import install as install_maintenance_guard

install_maintenance_guard(panel)
install_config_guard(panel)
app = panel.app
