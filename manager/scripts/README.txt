CS2 manager operational scripts
===============================

start.sh
  Creates the stopped cs2-game container and starts the panel. It reports ZIP
  files waiting under installs but does not mutate package state.

stop.sh
  Stops the manager services.

migrate.ps1 and rollback.ps1
  Preserve the legacy topology migration and rollback workflow.

smoke-test.sh
  Runs live deployment and isolation checks against a configured server.

Package updates are handled from the repository root by update.ps1.
Framework installation is handled by manager/shared/frameworks/install-linux.sh
through the cs2-modinstaller Compose service.
