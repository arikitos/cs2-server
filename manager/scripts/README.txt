HeroShift v1.0.1 server deployment
==================================

Prerequisite
------------
Pull the latest main branch of arikitos/cs2-server first. The current main branch
contains the versioned HeroShift release overlay mounts and installer scripts.

Windows PowerShell
------------------
Open PowerShell in the repository root and run:

  .\manager\scripts\install-heroshift-release.ps1 .\HeroShift-v1.0.1.zip

Linux
-----
Open a shell in the repository root and run:

  chmod +x ./manager/scripts/install-heroshift-release.sh
  ./manager/scripts/install-heroshift-release.sh ./HeroShift-v1.0.1.zip

What the installer does
-----------------------
1. Verifies the exact archive SHA256.
2. Rejects unsafe ZIP paths.
3. Verifies all 99 package files against package-manifest.json.
4. Installs a versioned overlay under manager/releases/heroshift/v1.0.1.
5. Updates HEROSHIFT_RELEASE_PATH in .env.
6. Recreates the panel and game container while preserving whether the game was running.
7. Keeps the previous overlay under manager/backups when replacing one.

Expected archive SHA256
-----------------------
5e4e2901757a234c43b0c844a99e118985a1f2474244c0d3dcedabc6f4770b0e

Configuration compatibility
---------------------------
HeroShift v1.0.1 ships configs/heroshift.json. The current panel roster editor
still targets the legacy config.json and skillsInfo.json files. Those legacy
files are retained for rollback, but edits made through that editor are not
expected to configure v1.0.1.
