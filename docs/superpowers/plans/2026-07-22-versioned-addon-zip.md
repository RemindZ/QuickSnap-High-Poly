# Versioned Add-on ZIP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the current QuickSnap version into a validated Blender-installable ZIP under an ignored `releases/` directory.

**Architecture:** A single PowerShell script reads `bl_info.version`, copies an explicit runtime allowlist into a temporary `QuickSnap/` directory, archives it, and validates required entries. Generated ZIPs stay out of Git; the script and empty output directory remain discoverable.

**Tech Stack:** Windows PowerShell, `Compress-Archive`, .NET `System.IO.Compression.ZipFile`, Git.

## Global Constraints

- Add no dependency.
- Keep one version source: `bl_info.version` in `__init__.py`.
- Generated `releases/*.zip` files must remain ignored.
- The ZIP must install as a Blender add-on with `QuickSnap/__init__.py` at its root.

---

### Task 1: Add and verify the release builder

**Files:**
- Create: `build_release.ps1`
- Modify: `.gitignore`
- Create: `releases/.gitkeep`

**Interfaces:**
- Consumes: `bl_info.version` from `__init__.py` and the repository's runtime files.
- Produces: `releases/QuickSnap-<major>.<minor>.<patch>.zip`.

- [ ] **Step 1: Record the generated-artifact policy**

Append this rule to `.gitignore` and add `releases/.gitkeep`:

```gitignore
releases/*.zip
```

- [ ] **Step 2: Add the minimal build script**

Create `build_release.ps1` with an explicit file allowlist, a top-level `icons/*.tif` runtime-asset copy, temporary staging under the system temp directory, replacement of an existing same-version ZIP, and a `finally` cleanup. Parse the three numeric version components from `__init__.py`; throw when parsing fails. After `Compress-Archive`, open the ZIP with `System.IO.Compression.ZipFile` and throw unless these entries exist:

```text
QuickSnap/__init__.py
QuickSnap/quicksnap.py
QuickSnap/quicksnap_utils.py
QuickSnap/quicksnap_snapdata.py
QuickSnap/icons/QUICKSNAP_POINTS.tif
```

- [ ] **Step 3: Run the builder and inspect its contract**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_release.ps1
```

Expected: exit `0`, output path ending in `releases\QuickSnap-1.5.13.zip`, and validation success.

Open the archive read-only and assert that every entry starts with `QuickSnap/`, required entries exist, and no entry contains `/tests/`, `/docs/`, `/.git`, `build_release.ps1`, or `/releases/`.

- [ ] **Step 4: Run release gates**

Run:

```powershell
python -m py_compile __init__.py quicksnap.py quicksnap_utils.py quicksnap_snapdata.py quicksnap_render.py tests\precision_fit_regression.py
& 'C:\Program Files\Blender Foundation\Blender 5.0\blender.exe' --background --factory-startup --python-exit-code 1 --python tests\precision_fit_regression.py
git check-ignore releases\QuickSnap-1.5.13.zip
git diff --check
```

Expected: compilation and Blender regression exit `0`, the archive is reported as ignored, and the diff check is empty.

- [ ] **Step 5: Commit the builder**

```powershell
git add .gitignore build_release.ps1 releases/.gitkeep docs/superpowers/plans/2026-07-22-versioned-addon-zip.md
git commit -m "build: add versioned addon package"
```

- [ ] **Step 6: Merge, verify, and push**

From the main worktree, merge `feature/plane-pair-fit`, rerun Steps 3 and 4 on merged `main`, remove the owned linked worktree, delete the merged feature branch, and push `main` to `origin`. Do not push unless the merged-tree build and regression gates pass.
