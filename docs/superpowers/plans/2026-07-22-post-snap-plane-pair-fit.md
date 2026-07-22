# Post-Snap Plane-Pair Fit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current post-snap ICP heuristic with a deterministic, feature-seeded plane-pair solver that centers rectangular clearance while preserving unconstrained axes.

**Architecture:** The operator preserves the exact source and target snap elements and passes them to a translation-only utility. The utility lazily extracts connected planar patches from Blender mesh topology, matches opposed source and target plane pairs, solves their midplane equations once, and validates the same pairs before returning a correction.

**Tech Stack:** Blender 5.0 headless test runner, Blender Python API compatible with Blender 2.93+, `mathutils`, NumPy, Python standard library.

## Global Constraints

- Add no dependency.
- Run only after confirmation, never during mouse movement.
- Use evaluated meshes unless `ignore_modifiers` is enabled.
- Preserve insertion depth and every other unobserved direction exactly.
- Ambiguous, organic, impossible, or stale geometry returns `None`.
- Do not retain the old ICP implementation as an automatic fallback.
- Do not add replacement tuning preferences.

---

### Task 1: Establish the Blender-headless RED harness

**Files:**
- Create: `tests/precision_fit_regression.py`
- Test: `tests/precision_fit_regression.py`

**Interfaces:**
- Consumes: current `quicksnap_utils.compute_precision_fit` module function.
- Produces: a standalone Blender script with `make_mesh()`, `make_peg()`, `make_socket()`, `assert_vector_close()`, and `main()`.

- [ ] **Step 1: Write the first failing regression**

The script loads `quicksnap_utils.py` directly, creates an eight-vertex peg already corner-snapped into a socket with `0.2` clearance on X and Y, and calls the approved feature-seeded signature:

```python
fit = quicksnap_utils.compute_precision_fit(
    bpy.context,
    SimpleNamespace(ignore_modifiers=True),
    peg.name, 'POINTS', peg_seed,
    socket.name, 'POINTS', socket_seed,
    socket.data.vertices[socket_seed].co,
)
assert_vector_close(fit, Vector((0.1, 0.1, 0.0)))
```

`make_peg()` creates a box from `(-0.6, -0.7, -1.0)` to `(0.4, 0.5, 0.0)` with outward-wound faces. `make_socket()` creates a top rectangular ring at `z=0` plus four inward-facing hole walls down to `z=-1.2`; the hole spans `[-0.6, 0.6] x [-0.7, 0.7]`. Both seed indices identify the shared corner `(-0.6, -0.7, 0.0)`.

- [ ] **Step 2: Run the harness and verify the predicted first RED**

Run:

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.0\blender.exe' --background --factory-startup --python tests\precision_fit_regression.py
```

Expected: nonzero exit with `TypeError: compute_precision_fit() takes from 5 to 7 positional arguments but 10 were given` because the current function does not accept source and target feature descriptors.

- [ ] **Step 3: Commit the RED harness**

```powershell
git add tests/precision_fit_regression.py
git commit -m "test: cover feature-seeded precision fit"
```

---

### Task 2: Preserve snap feature identity and wire the new utility signature

**Files:**
- Modify: `quicksnap.py:56-120`
- Modify: `quicksnap.py:292-320`
- Modify: `quicksnap.py:396-405`
- Modify: `quicksnap.py:526-599`
- Modify: `quicksnap_utils.py:164-387`
- Test: `tests/precision_fit_regression.py`

**Interfaces:**
- Consumes: `SnapData.find_closest()` tuple `(snap_id, distance, object_name, is_origin, element_index)`.
- Produces: `compute_precision_fit(context, settings, source_object_name, source_snap_type, source_element_index, target_object_name, target_snap_type, target_element_index, contact_point) -> Vector | None`.

- [ ] **Step 1: Add operator state for the source datum**

Initialize/reset these fields in `QuickVertexSnapOperator.__init__()` and at tool invocation:

```python
self.source_object = ""
self.source_element_index = -1
self.source_snap_type = ""
```

When a source candidate is accepted, preserve the returned values:

```python
self.source_object = target_name
self.source_element_index = mesh_vertid
self.source_snap_type = self.snapdata_source.snap_type
```

- [ ] **Step 2: Replace the caller arguments**

Call the utility only for mesh element snap types:

```python
if self.source_snap_type not in {'POINTS', 'MIDPOINTS', 'FACES'}:
    return
if self.snapdata_target.snap_type not in {'POINTS', 'MIDPOINTS', 'FACES'}:
    return
fit = quicksnap_utils.compute_precision_fit(
    context, self.settings,
    self.source_object, self.source_snap_type, self.source_element_index,
    self.target_object, self.snapdata_target.snap_type, self.closest_vertexid,
    self.target,
)
```

- [ ] **Step 3: Adapt the utility signature while retaining the old body temporarily**

Change the signature and feed the old sampler from the one source object:

```python
def compute_precision_fit(context, settings,
                          source_object_name, source_snap_type, source_element_index,
                          target_object_name, target_snap_type, target_element_index,
                          contact_point):
    object_names = [source_object_name]
    sample_count = 300
    iterations = 12
```

- [ ] **Step 4: Run the harness and verify the second predicted RED**

Run the Task 1 command.

Expected: assertion failure because the old body returns `None` for the eight-vertex peg at `if len(points) < 16`.

- [ ] **Step 5: Compile the edited modules**

Run:

```powershell
python -m py_compile quicksnap.py quicksnap_utils.py
```

Expected: exit 0.

- [ ] **Step 6: Commit feature identity wiring**

```powershell
git add quicksnap.py quicksnap_utils.py
git commit -m "refactor: pass snap features to precision fit"
```

---

### Task 3: Extract deterministic local planar patches

**Files:**
- Modify: `quicksnap_utils.py:1-387`
- Extend: `tests/precision_fit_regression.py`

**Interfaces:**
- Produces private helpers:
  - `_mesh_fit_data(obj) -> dict`
  - `_seed_polygons(mesh_data, snap_type, element_index) -> list[int]`
  - `_polygon_geometry(mesh_data, polygon_index) -> dict`
  - `_grow_planar_patch(mesh_data, seed_polygon, cos_planar) -> dict | None`
  - `_candidate_patches(mesh_data, seed_polygons) -> list[dict]`

- [ ] **Step 1: Add triangulation-density and polygon-order RED cases**

Extend the harness with these geometrically identical variants: `make_peg(subdivisions=1, reverse_faces=False)` plus `make_socket(subdivisions=1, reverse_faces=False)`; `make_peg(subdivisions=8, reverse_faces=False)` plus `make_socket(subdivisions=8, reverse_faces=False)`; and `make_peg(subdivisions=8, reverse_faces=True)` plus `make_socket(subdivisions=8, reverse_faces=True)`. Assert all three return `(0.1, 0.1, 0.0)` within `1e-9` times the `1.4` target width.

Expected before implementation: all cases fail because the old sampler is density-dependent or returns `None`.

- [ ] **Step 2: Build compact mesh/topology arrays**

`_mesh_fit_data()` bulk-loads local vertices, loop vertex/edge indices, polygon loop ranges, centers, and normals; transforms vertices/centers/normals to world space; and builds edge-to-polygon CSR arrays by stable-sorting loop edge indices:

```python
order = np.argsort(loop_edges, kind='stable')
edge_counts = np.bincount(loop_edges, minlength=len(mesh.edges))
edge_starts = np.concatenate(([0], np.cumsum(edge_counts)))
loop_polygons = np.repeat(np.arange(len(mesh.polygons)), polygon_loop_totals)
edge_polygons = loop_polygons[order]
```

World polygon area is computed lazily from transformed vertices using a triangle fan and cached by polygon index, so non-uniform scale is exact.

- [ ] **Step 3: Map source/target element types to seed polygons**

Implement exact index checks:

```python
if snap_type == 'POINTS':
    return np.unique(loop_polygons[loop_vertices == element_index]).tolist()
if snap_type == 'MIDPOINTS':
    return np.unique(loop_polygons[loop_edges == element_index]).tolist()
if snap_type == 'FACES' and 0 <= element_index < polygon_count:
    return [element_index]
return []
```

- [ ] **Step 4: Grow order-independent planar components**

Connect edge-adjacent polygons only when their outward normals satisfy `dot >= cos(5 degrees)` and each center lies within `max(0.005 * shared_edge_length, 1e-7)` of the other's plane. Grow the full connected component, then reject it when its final maximum residual exceeds `max(0.005 * projected_extent, 1e-7)`.

The patch normal is the normalized world-area-weighted outward-normal sum; the patch point is the world-area-weighted center sum. The extent comes from all unique transformed patch vertices. Cache polygon-to-patch membership so traversal order cannot split or duplicate a component.

- [ ] **Step 5: Gather exactly two patch-boundary hops**

Start with every seed patch, inspect polygons across their boundary edges, grow those neighboring patches, and repeat once. Return patches sorted by their geometric plane key `(rounded canonical normal, rounded plane coordinate, area)`; polygon IDs are retained only for same-run validation.

- [ ] **Step 6: Run focused regressions**

Run the Task 1 command.

Expected: the patch-extraction assertions pass; the top-level correction remains RED until Task 4 supplies pair solving.

- [ ] **Step 7: Commit planar extraction**

```powershell
git add quicksnap_utils.py tests/precision_fit_regression.py
git commit -m "feat: extract snap-seeded planar patches"
```

---

### Task 4: Match plane pairs and solve clearance midplanes

**Files:**
- Modify: `quicksnap_utils.py`
- Extend: `tests/precision_fit_regression.py`

**Interfaces:**
- Produces private helpers:
  - `_plane_pairs(patches, contact) -> list[dict]`
  - `_match_plane_pairs(source_pairs, target_pairs, contact) -> list[dict]`
  - `_solve_pair_translation(matches) -> np.ndarray | None`
  - `_validate_pair_translation(matches, translation) -> bool`

- [ ] **Step 1: Add slot, wedge, organic, neighboring-socket, and impossible-fit RED cases**

Add assertions:

```python
assert_vector_close(run_slot_case(), Vector((0.1, 0.0, 0.0)))
assert run_wedge_case(120) is None
assert run_wedge_case(150) is None
assert run_organic_case() is None
assert_vector_close(run_neighboring_socket_case(), Vector((0.1, 0.1, 0.0)))
assert run_equal_width_case() is None
assert run_oversized_peg_case() is None
assert run_stale_index_case() is None
```

- [ ] **Step 2: Form source and target plane pairs**

For each patch pair:

```python
if float(n1 @ n2) > math.cos(math.radians(170.0)):
    continue
axis = n1 - n2
axis /= np.linalg.norm(axis)
axis *= 1.0 if axis[np.argmax(np.abs(axis))] >= 0 else -1.0
d1, d2 = sorted((float(axis @ p1), float(axis @ p2)))
contact_d = float(axis @ contact)
if not d1 - tolerance <= contact_d <= d2 + tolerance:
    continue
```

Retain pair patches ordered by their plane coordinate, plus midpoint, separation, combined tolerance, and IDs.

- [ ] **Step 3: Match source and target pairs**

Require axis alignment within 5 degrees, spatially corresponding face normals opposed by at least 170 degrees, target width larger than source width beyond tolerance, and both slabs containing the snapped point. Reject requests exceeding `min(0.25 * source_width, 2.0 * clearance)`.

For each source pair and axis, sort qualifying targets by midpoint distance. If the two closest distances differ by no more than their combined tolerance, discard the axis as ambiguous; never use patch IDs as a tie-breaker.

- [ ] **Step 4: Solve only observable directions**

```python
u = np.array([match['axis'] for match in matches])
delta = np.array([match['target_mid'] - match['source_mid'] for match in matches])
translation, _, _, singular = np.linalg.lstsq(u, delta, rcond=0.1)
cutoff = 0.1 * singular[0]
_, _, vh = np.linalg.svd(u, full_matrices=False)
basis = vh[singular > cutoff]
translation = basis.T @ (basis @ translation)
```

Return `None` for no matches, zero rank, non-finite values, or a correction below `1e-12` times the largest matched target width.

- [ ] **Step 5: Validate the same constraints**

For every match, shift only the source plane coordinates by `axis @ translation`, calculate low/high clearances, and require both to be at least negative tolerance, reduced imbalance, and final imbalance no larger than combined tolerance. Reject the entire translation if any match fails.

- [ ] **Step 6: Replace the old ICP body**

Resolve raw/evaluated source and target mesh objects, extract seeds/patches/pairs, solve once, log concise debug reasons for `None`, and return `Vector(translation)` on success. Delete the old sampling, nearest-surface loop, clustering, Cauchy weights, iterations, and sample-radius correction cap.

- [ ] **Step 7: Run the complete current harness**

Run the Task 1 command.

Expected: exit 0 with a printed summary containing every named case and `precision_fit_regression: PASS`.

- [ ] **Step 8: Commit the plane-pair solver**

```powershell
git add quicksnap_utils.py tests/precision_fit_regression.py
git commit -m "feat: center clearance with plane pairs"
```

---

### Task 5: Cover transforms, modifiers, and operator cleanup

**Files:**
- Modify: `quicksnap.py`
- Modify: `quicksnap_utils.py`
- Extend: `tests/precision_fit_regression.py`

**Interfaces:**
- Consumes: completed plane-pair solver.
- Produces: transform/modifier coverage and removal of obsolete sample-count configuration.

- [ ] **Step 1: Add non-uniform-scale and modifier RED cases**

Create one case using object scale `(2.0, 0.5, 1.5)` and an equivalent case with scale applied; assert identical world-space correction. Add a source/target modifier case where evaluated geometry changes the socket width; assert default settings use evaluated width and `ignore_modifiers=True` uses raw width.

- [ ] **Step 2: Make evaluated/raw selection explicit**

Use:

```python
depsgraph = context.evaluated_depsgraph_get()
source_obj = bpy.data.objects.get(source_object_name)
target_obj = bpy.data.objects.get(target_object_name)
source_fit = source_obj if settings.ignore_modifiers else source_obj.evaluated_get(depsgraph)
target_fit = target_obj if settings.ignore_modifiers else target_obj.evaluated_get(depsgraph)
```

Transform normals by inverse-transpose and calculate world area from transformed polygon vertices.

- [ ] **Step 3: Remove the obsolete preference**

Delete `precision_fit_samples`, its preferences UI row, and the old caller argument. Keep `precision_fit` unchanged. Do not migrate the JSON backup: `load_settings()` already ignores removed keys.

- [ ] **Step 4: Run syntax and headless verification**

Run:

```powershell
python -m py_compile quicksnap.py quicksnap_utils.py tests\precision_fit_regression.py
& 'C:\Program Files\Blender Foundation\Blender 5.0\blender.exe' --background --factory-startup --python tests\precision_fit_regression.py
```

Expected: both commands exit 0; harness ends with `precision_fit_regression: PASS`.

- [ ] **Step 5: Commit transform coverage and cleanup**

```powershell
git add quicksnap.py quicksnap_utils.py tests/precision_fit_regression.py
git commit -m "test: harden plane-pair precision fit"
```

---

### Task 6: Release notes and final verification

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `__init__.py`

**Interfaces:**
- Produces: add-on version `1.5.13` and user-facing behavior notes.

- [ ] **Step 1: Document the replacement**

Add a `1.5.13` changelog entry stating that post-snap fit now uses the snapped elements as datum seeds, centers clean opposed plane pairs independent of mesh density, preserves unconstrained axes, and safely skips ambiguous or organic geometry. Note removal of the obsolete sample-count setting.

- [ ] **Step 2: Bump the add-on version**

Change:

```python
'version': (1, 5, 13),
```

- [ ] **Step 3: Run the full verification gate**

Run:

```powershell
python -m py_compile __init__.py quicksnap.py quicksnap_utils.py quicksnap_snapdata.py quicksnap_render.py
& 'C:\Program Files\Blender Foundation\Blender 5.0\blender.exe' --background --factory-startup --python tests\precision_fit_regression.py
git diff --check
git status --short
```

Expected: compilation exit 0, harness exit 0 with `precision_fit_regression: PASS`, no `git diff --check` output, and status containing only the intended changelog/version changes before commit.

- [ ] **Step 4: Commit release metadata**

```powershell
git add CHANGELOG.md __init__.py
git commit -m "chore: release QuickSnap 1.5.13"
```

- [ ] **Step 5: Verify the committed tree**

Run the compilation and Blender harness again, followed by:

```powershell
git status --short
git log -6 --oneline
```

Expected: both verification commands exit 0 and the working tree is clean. Manual validation on a real kit-part `.blend` remains a release gate because no such file exists in this repository.
