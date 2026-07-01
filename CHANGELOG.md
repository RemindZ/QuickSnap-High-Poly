# Changelog

## 1.5.1

### Added
- Post-snap precision fit (object mode, toggleable, on by default): after a snap
  confirms, the selection is nudged (translation only, no rotation) so the
  geometry around the snapped point seats onto the target surface. Intended for
  assembling kit parts where peg and hole vertices do not correspond exactly.
  - Sampling is anchored to the snapped point, matches are only accepted near
    the contact area and between surfaces facing each other, so complex
    geometry around the mating features does not affect the fit.
  - The correction is capped relative to the sampled area, applied within the
    same undo step, and skipped when an axis constraint is active or the target
    is an origin/cursor/free-space point.
  - New preferences under "Precision fit": enable toggle and sample count.

## 1.5.0

High-poly performance pass. The tool stays usable on objects in the
millions-of-vertices range, without changing which elements are snappable or
altering behavior on light meshes. Every heavy-mesh path is gated behind a
configurable vertex threshold, so meshes below it keep the previous behavior
exactly. The gate counts evaluated vertices, so sculpts whose density comes
from a subsurf/multires modifier are detected too.

### Added
- Cursor-local wireframe: for objects above the vertex threshold, the native
  full-object wireframe overlay (which redraws every edge each frame) is
  replaced by a wireframe limited to the edges near the cursor. Edges with one
  endpoint near the cursor are drawn in full, it works for all snap types, and
  it is occluded by the mesh by default (optional x-ray). The mesh data is
  fetched once per object and lookups go through a screen-space grid plus a
  vertex-to-edge adjacency, so per-frame cost only depends on what is drawn.
- New preferences under "High-poly performance":
  - **Optimize high-poly meshes**: master toggle for the optimized paths.
  - **High-poly vertex threshold (x1000)**: objects with at least this many
    thousand vertices use the optimized paths (default 500, i.e. 500,000).
  - **Cursor wireframe radius (px)**: pixel radius of the cursor-local
    wireframe (default 60).
  - **Cursor wireframe color / opacity**: look of the cursor-local wireframe
    (default white at 0.9).
  - **Wireframe through geometry (x-ray)**: draw the cursor wireframe through
    the mesh instead of occluding it (default off).
- Debug HUD (shown when the log level is set to Debug): point count, query
  mode, query/wireframe frame timings and total ingestion time. Useful for
  before/after performance comparisons.

### Changed
- Closest-point lookup on heavy scenes now uses a screen-space grid query
  instead of building a spatial tree over millions of points, removing the
  upfront stall and the associated memory spike when a heavy object enters snap
  range, and keeping per-move lookups cheap afterwards. Snap results are
  identical to the previous method.
- The near-point display (edge midpoints / face centers / vertices around the
  hovered face) now uses a binary search instead of a linear scan through the
  object's point indices, which removes a per-frame cost that grew with vertex
  count.

### Notes
- Snap targets are always the real mesh elements; no decimated proxy is used.
- Light meshes use the original code paths unchanged.
