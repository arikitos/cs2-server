HeroShift v1.0.0 server deployment
==================================

The repository contains the official HeroShift v1.0.0 release archive and
installers for Windows PowerShell and Linux.

Windows PowerShell
------------------

Run from the repository root.

  ./manager/scripts/install-heroshift-release.ps1 ./manager/scripts/HeroShift-v1.0.0.zip

Linux
-----

Run from the repository root.

  chmod +x ./manager/scripts/install-heroshift-release.sh
  ./manager/scripts/install-heroshift-release.sh ./manager/scripts/HeroShift-v1.0.0.zip

What the installer does
-----------------------

1. Verifies the archive SHA256.
2. Rejects unsafe ZIP paths.
3. Verifies all 99 runtime files against package-manifest.json.
4. Backs up older release overlays.
5. Installs manager/releases/heroshift/v1.0.0.
6. Updates HEROSHIFT_RELEASE_PATH in .env.
7. Recreates the panel and game container while preserving whether the game was running.

Expected archive SHA256
-----------------------

42e4672e48e8b8b460180648a2f2508787b6f77896323cfe594661c692507c7b

Configuration
-------------

HeroShift v1.0.0 reads only heroshift.json. The manager-owned file is
manager/modes/heroshift/config/heroshift.json. config.json and skillsInfo.json
are legacy formats and are intentionally absent.

The previous tracked legacy files matched HeroShift v1.0.0 canonical defaults,
so the minimal schemaVersion-only override preserves the effective behavior.

Bootstrap
---------

setup.ps1 and manager/scripts/start.sh use the stage-only installer mode when
the verified release overlay is missing. Stage-only verifies, extracts, backs
up, and updates .env without starting or recreating containers.
