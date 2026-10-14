"""WSGI entrypoint that installs panel safeguards before serving."""

import app as panel
from config_guard import install as install_config_guard
from maintenance_guard import install as install_maintenance_guard
from security import install as install_security

install_maintenance_guard(panel)
install_config_guard(panel)
install_security(panel)
app = panel.app
