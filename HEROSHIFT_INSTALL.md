# HeroShift package installation

Place one or more release archives named `HeroShift-vX.Y.Z.zip` in the repository root.
The installer selects the highest semantic version when no package path is supplied.

## Windows

```powershell
.\install-heroshift.ps1
```

To verify and stage the package without changing Docker containers:

```powershell
.\install-heroshift.ps1 -StageOnly
```

## Linux

```bash
bash ./install-heroshift.sh
```

To verify and stage the package without changing Docker containers:

```bash
bash ./install-heroshift.sh --stage-only
```

The installer performs the following operations.

1. It validates the package name and semantic version.
2. It rejects unsafe archive paths.
3. It verifies every file against `package-manifest.json`.
4. It verifies the required HeroShift and RayTrace package paths.
5. It stages a clean overlay under `manager/releases/heroshift/current`.
6. It backs up the previous overlay under `manager/backups`.
7. It updates `HEROSHIFT_RELEASE_PATH` in `.env`.
8. It recreates the panel and game containers without rebuilding their images.

When the game container was running, it is recreated and started so the mode applier deploys the new files into the persistent CS2 installation. When it was stopped, it remains stopped and can be started from the panel.

A full image rebuild is not required for a HeroShift package update. The package is supplied through bind mounts. Container recreation is required so Docker binds the verified replacement overlay.
