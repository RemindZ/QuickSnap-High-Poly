# Post-Snap Plane-Pair Fit Design

Date: 2026-07-22
Status: Approved direction; implementation not started

## Purpose

Replace QuickSnap's sample-density-dependent post-snap ICP heuristic with a deterministic, translation-only mate solver for rectangular pegs, sockets, and slots.

The user-selected source and target snap elements are the coarse alignment and implicit datum seeds. The solver must center designed lateral clearance only where both meshes expose a clean opposed plane pair. It must preserve every unconstrained degree of freedom, especially insertion depth, and do nothing when the evidence is ambiguous.

## Current behavior being replaced

`QuickVertexSnapOperator.run_precision_fit()` calls `compute_precision_fit()` once after the user's final snap translation. The current implementation:

- samples nearby moving-object vertices;
- finds nearest points on the target;
- clusters target normals;
- infers opposed directions;
- iteratively solves a weighted point-to-plane translation;
- projects the result onto inferred bilateral axes.

The integration point and translation-only scope remain. The nearest-point ICP objective and sample-count preference do not.

## Requirements

### Functional

1. Center a rectangular peg inside a larger rectangular socket along each laterally constrained axis.
2. Center a key inside a slot along the slot's one constrained axis only.
3. Preserve insertion depth exactly unless a clean opposed plane pair explicitly constrains that axis.
4. Produce the same correction for equivalent geometry with different triangulation density or polygon order.
5. Use evaluated meshes unless `ignore_modifiers` is enabled, matching the existing snap-data behavior.
6. Apply the correction to the complete moving selection inside the existing undo operation.
7. Fail closed: ambiguous, organic, incomplete, impossible, or stale feature data produces no correction.

### Non-functional

1. Add no dependency; use Blender's mesh API, `mathutils`, and NumPy already shipped with the add-on.
2. Run once on confirmation, never during mouse movement.
3. Avoid whole-scene searches. Inspect only the snapped source object and target object.
4. Keep geometric thresholds internal. Do not replace the sample-count preference with a new tuning panel.
5. Leave a Blender-headless regression check covering every solver branch.

## Non-goals

- Rotation or scale correction.
- Global registration or recovery from a wrong user snap.
- General organic-surface seating.
- Cylindrical, spherical, or conical analytic mates.
- Collision detection for the complete selected assembly.
- Inferring deliberately off-center clearances.

## Interaction and data flow

### Capture the implicit datum seeds

`SnapData.find_closest()` already returns the object name and element index for point, edge-midpoint, and face-center snaps. Preserve these values when the source is chosen instead of discarding the source element index.

The operator records:

- source object name;
- source snap type: `POINTS`, `MIDPOINTS`, or `FACES`;
- source evaluated-mesh element index;
- target object name;
- target snap type;
- target evaluated-mesh element index.

Origin, cursor, curve, free-space, edit-mode, and explicitly axis-constrained snaps retain their existing skip behavior.

At confirmation:

1. Apply the user's exact snap translation.
2. Resolve the recorded elements against fresh raw or evaluated meshes.
3. Skip if either object, topology, or element index is no longer valid.
4. Extract local planar patches and plane pairs.
5. Solve and validate one translation.
6. Apply it through the existing `bpy.ops.transform.translate()` call.

The replacement utility entry point is:

```python
compute_precision_fit(context, settings,
                      source_object_name, source_snap_type, source_element_index,
                      target_object_name, target_snap_type, target_element_index,
                      contact_point)
```

The source object defines the mating feature; the returned translation is still applied to the complete operator selection by the caller.

## Geometry model

### Seed polygons

Map the selected element to seed polygons:

- `POINTS`: every polygon incident to the selected vertex;
- `MIDPOINTS`: every polygon incident to the selected edge;
- `FACES`: the selected polygon.

Element indices refer to the same evaluated mesh used to build the corresponding `SnapData`. If an index cannot be resolved, skip rather than falling back to proximity inference.

### Planar patches

Build a local edge-adjacency view for the evaluated mesh and grow maximal connected patches from the seed polygons. Adjacent polygons join a patch when:

- their world-space normals differ by at most 5 degrees; and
- every added polygon center lies within `0.5%` of the current patch extent from the current patch plane, with an absolute floor of `1e-7` Blender units.

Define the patch point as the world-area-weighted mean of polygon centers and its normal as the normalized world-area-weighted mean of the polygons' outward normals. This also defines a plane for a patch containing one n-gon. Refit after each accepted growth batch. Store:

- deterministic patch ID: lowest polygon index;
- outward unit normal;
- area-weighted point on plane;
- total world-space area;
- maximum point-to-plane residual;
- projected extent;
- polygon indices and boundary edges.

Candidate patches are:

1. every patch containing a seed polygon; and
2. every planar patch reached within two patch-boundary hops of those seed patches.

Two hops let a face-center snap traverse `side -> end/rim -> opposite side`; point and edge snaps usually need only one. The later slab and pair-matching checks reject unrelated boundaries reached through a large coplanar patch.

### Opposed plane pairs

Within each mesh, form a pair only when:

- the patch normals are at least 170 degrees apart (`dot <= cos(170 degrees)`);
- both patches pass their flatness test;
- their plane separation is positive and greater than both flatness tolerances;
- the snapped point's projection lies inside the closed slab between the planes, plus flatness tolerance;
- neither patch has zero area or extent.

Canonicalize the pair axis so its largest-magnitude component is positive. Store the two plane coordinates on that axis, their midpoint, separation, combined area, and patch IDs.

### Source-to-target pair matching

Match a source pair to a target pair only when:

- their canonical axes differ by at most 5 degrees;
- each source face normal opposes its spatially corresponding target face normal by at least 170 degrees;
- target separation is strictly larger than source separation after flatness tolerance;
- both pair slabs contain the snapped point;
- the target pair midpoint is the closest qualifying midpoint to the snapped point.

Sort matches by midpoint distance. If the two closest pairs are tied within their flatness tolerances, the axis is ambiguous and is skipped. Patch IDs identify constraints during same-run validation; they never break a geometric tie, so polygon enumeration cannot choose the result.

## Translation solve

For every unambiguous matched pair, define:

```text
axis dot translation = target_midpoint - source_midpoint
clearance = target_separation - source_separation
```

Reject an axis when the requested correction exceeds:

```text
min(0.25 * source_separation, 2.0 * clearance)
```

This permits corner-to-corner placement to move by half the designed clearance, tolerates a small initial overlap, and prevents relocation to a neighboring feature.

Solve all accepted equations with `numpy.linalg.lstsq`. Use a relative singular-value cutoff of `0.1`; components below the cutoff are unobservable and remain exactly zero. Project the result back onto the retained row space so numerical damping cannot introduce motion along an unconstrained axis.

No nearest-neighbor iteration or robust kernel remains in the clean planar path.

## Validation and failure behavior

Validate against the same patch-pair IDs used to solve; do not rebuild correspondences for acceptance.

For each matched axis after the proposed translation:

1. Both signed clearances must be at least negative flatness tolerance.
2. The absolute difference between the two clearances must decrease.
3. The final difference must be no greater than the combined source and target flatness tolerances.
4. The correction component along every discarded singular direction must be zero within `1e-10` times the largest accepted feature separation.

Reject the complete correction if any accepted axis fails. A zero correction, no plane pair, ambiguous pair, impossible fit, rank-zero system, invalid topology, or numerical failure returns `None`.

Early exits log a concise debug reason but do not add user-facing warnings. A successfully applied correction retains the existing info report.

## Code shape

Keep the change local:

- `quicksnap.py`
  - preserve the source element identity;
  - pass source and target feature descriptors to the solver;
  - remove the `precision_fit_samples` preference and UI row.
- `quicksnap_utils.py`
  - replace the current `compute_precision_fit()` body;
  - add only private, single-purpose geometry helpers needed by that function.
- `tests/precision_fit_regression.py`
  - create synthetic Blender meshes, run the solver, and assert corrections.
- `CHANGELOG.md` and `__init__.py`
  - document and version the behavior after the regression harness and implementation pass.

The stale `precision_fit_samples` key in `quicksnap_settings.json` is safe: the existing loader already ignores properties removed from the current version.

## Regression harness

Run with:

```powershell
blender --background --factory-startup --python tests/precision_fit_regression.py
```

The script exits nonzero on the first failed assertion and covers:

1. Eight-vertex rectangular peg/socket centers X and Y; Z is bit-for-bit unchanged.
2. The same geometry with uneven dense triangulation produces the same correction within `1e-9` times feature width.
3. Reversed polygon creation order produces the same correction.
4. A one-axis slot centers one axis and leaves the other two unchanged.
5. A valid single axis remains usable when another axis is ambiguous.
6. Organic/fur-like irregular surfaces produce `None`.
7. A 120-to-150-degree wedge is not an opposed pair and produces `None`.
8. A neighboring identical socket is ignored in favor of the slab containing the snapped point.
9. Non-uniform object scale produces the same world-space result as applied geometry.
10. Evaluated modifiers are honored; `ignore_modifiers` uses the raw mesh.
11. A peg equal to or larger than the socket produces `None`.
12. A stale or out-of-range source/target element index produces `None` without an exception.

The harness is written and observed failing for the current solver before implementation begins. The predicted first RED is a `TypeError` because the current utility does not accept source/target feature descriptors. After the new signature is minimally wired, the eight-vertex case must remain RED under the old body because it requires at least 16 sampled vertices.

## Delivery order

1. Add the headless regression harness and confirm the predicted RED failure.
2. Preserve source and target feature identities through the operator.
3. Implement planar patch extraction and its focused regression cases.
4. Implement pair matching, midplane solve, and same-feature validation.
5. Remove the obsolete sample-count preference.
6. Run the complete headless harness.
7. Perform a manual Blender smoke test on one real kit-part file before release.

## Deferred extensions

- Add a modifier-assisted explicit datum mode only if valid rectangular features remain ambiguous in real scenes.
- Add robust plane fitting for noisy scan meshes only when the planar residual tests reject real intended pegs.
- Add analytic cylinder mates only after a concrete cylindrical assembly case exists.

Do not retain the old ICP solver as an automatic fallback: an ambiguous plane result must remain a safe no-op rather than silently re-entering the behavior this design replaces.
