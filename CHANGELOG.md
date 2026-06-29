# Changelog

## 1.5.0

High-poly performance pass. The tool stays usable on objects in the
millions-of-vertices range, without changing which elements are snappable or
altering behavior on light meshes. Every heavy-mesh path is gated behind a
configurable vertex threshold, so meshes below it keep the previous behavior
exactly.

### Added
- Cursor-local wireframe: for objects above the vertex threshold, the native
  full-object wireframe overlay (which redraws every edge each frame) is
  replaced by a wireframe limited to the edges near the cursor. This keeps the
  viewport interactive when hovering very dense meshes.
- New preferences under "High-poly performance":
  - **Optimize high-poly meshes**: master toggle for the optimized paths.
  - **High-poly vertex threshold**: objects with at least this many vertices
    use the optimized paths (default 500,000).
  - **Cursor wireframe radius (px)**: pixel radius of the cursor-local
    wireframe (default 60).

### Changed
- Closest-point lookup on heavy scenes now uses a vectorized screen-space range
  query instead of building a spatial tree over millions of points, removing the
  upfront stall and the associated memory spike when a heavy object enters snap
  range. Snap results are identical to the previous method.

### Notes
- Snap targets are always the real mesh elements; no decimated proxy is used.
- Light meshes use the original code paths unchanged.
