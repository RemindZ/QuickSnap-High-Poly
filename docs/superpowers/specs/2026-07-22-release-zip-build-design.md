# Versioned Add-on ZIP Build Design

Date: 2026-07-22
Status: Approved

## Goal

Provide one repeatable Windows command that builds the current QuickSnap add-on into a versioned, Blender-installable ZIP without committing generated archives.

## Design

- Add `build_release.ps1` at the repository root.
- Read the add-on version from `bl_info` in `__init__.py`; do not maintain a second version value.
- Stage only runtime files under a top-level `QuickSnap/` directory, then create `releases/QuickSnap-<version>.zip` with PowerShell's built-in archive support.
- Include root Python modules, `LICENSE.md`, `README.md`, `CHANGELOG.md`, and the `icons/` runtime assets.
- Exclude repository metadata, worktrees, tests, docs, build scripts, caches, updater scratch data, and older release archives.
- Replace an existing archive for the same version so rebuilding cannot preserve stale files.
- Validate that the archive contains `QuickSnap/__init__.py` and the principal runtime modules before reporting success.
- Ignore `releases/*.zip` and commit `releases/.gitkeep` so the output location is discoverable.

## Verification

Run `powershell -NoProfile -ExecutionPolicy Bypass -File .\build_release.ps1`, inspect the archive entry list, and confirm no development-only paths are present. Existing Python compilation and Blender regression checks remain the release gate before merge and push.
