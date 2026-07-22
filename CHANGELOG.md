# Changelog

## 1.5.13

### Changed
- Post-snap precision fit now uses the exact snapped source and target elements
  as datum seeds, then centers clean opposed plane pairs. Rectangular pegs and
  slots fit deterministically regardless of mesh density or polygon order,
  while insertion depth and every other unconstrained direction stay fixed.
- Ambiguous, organic, stale, equal-width, or impossible geometry is safely
  skipped instead of falling back to surface-distance fitting. The obsolete
  fit sample-count setting has been removed.

## 1.5.12

### Fixed
- Precision fit rebuilt for sculpted kit parts (organic surfaces, fur, shells
  that overlap by design, with clean rectangular pegs for assembly). The fit
  now only acts on clean mating faces: large, flat, direction-coherent contact
  clusters whose normals oppose almost exactly. Rough organic contact and
  designed shell overlaps are ignored entirely, and the correction is
  restricted to the axes that opposing faces actually constrain, so insertion
  depth always stays exactly where the snap put it. When no clean bilateral
  feature is found near the snap, the part is not moved at all.

### Added
- QuickSnap panel in the 3D view sidebar (N panel) with the per-session
  toggles: post-snap precision fit, prefer corners, hide dragged over target.
- Holding middle mouse (orbit) now also pauses snapping and hides the dragged
  objects, like Shift, so navigating around the target stays light and clear.

## 1.5.11

### Added
- Hold Shift after picking the source point to pause snapping: nothing under
  the cursor is loaded, searched or highlighted while held, so the mouse stays
  light around dense targets, and the dragged objects stay hidden (with the
  hide option on) so the target's interior is visible. Release Shift to resume
  snapping; the header shows when snapping is paused.

## 1.5.10

### Fixed
- Precision fit no longer moves a part too far, e.g. carrying a key across the
  slot until its left wall touches the lock's right wall. The fit now solves on
  one robust value per mating face instead of per sample, so the balance
  depends on the geometry rather than on how many samples happen to land on
  each wall (uneven sampling used to drag the part towards the better-sampled
  side). Faces close to where the user placed the part anchor the fit while
  far matches (such as a neighboring identical slot) lose influence, and the
  maximum correction is much tighter: the fit refines placement, it never
  relocates the part.

## 1.5.9

### Fixed
- Settings now survive version upgrades. Blender wipes addon preferences when
  an addon is removed, and keys them to the install folder name, so upgrading
  via remove+install (or installing a differently named zip) lost all settings.
  The addon now backs its preferences up to quicksnap_settings.json in
  Blender's config folder (on every tool session end and on disable) and
  restores them when enabled, so settings persist across reinstalls, renamed
  installs and Blender upgrades.

## 1.5.8

### Fixed
- Precision fit now handles parts with built-in tolerances (a designed air gap
  between key and lock) correctly: the part is centered so the gap is even on
  all sides, instead of sometimes being pushed against a wall. A gap now only
  constrains the fit when another surface opposes its direction: opposed gaps
  are balanced, unopposed gaps are treated as designed standoffs and left
  alone, and penetration always resolves. The final check is a safety check
  (reject corrections that leave the parts sitting worse) rather than an
  improvement demand, since balancing a clearance barely changes the total
  error while clearly improving the fit.

## 1.5.7

### Fixed
- Stop "ReferenceError: StructRNA ... has been removed" spam from the viewport
  draw callbacks. If the tool operator is ever freed without a clean shutdown
  (a mid-session error, a script reload), its draw handlers no longer keep
  firing against the dead operator: the handlers are tracked centrally, the
  draw callbacks detect a freed operator and unregister themselves, and any
  leftover handlers are purged when the addon is disabled or reloaded.
- Corner-preferring vertex snapping can no longer raise during a snap; on any
  unexpected error it is skipped for that query instead of ending the tool.

## 1.5.6

### Fixed
- Fix a crash on tool start (NameError: numpy was not imported in the operator
  module) introduced with corner-preferring vertex snapping in 1.5.5.

## 1.5.5

### Added
- **Prefer corners (vertex snapping)** (toggleable, on by default): when picking
  vertices, corner vertices (peg/socket corners, crease ends, borders) get a
  scoring bonus over vertices on flat or gently curved areas near the cursor,
  making the corners of mating features much easier to grab. Cornerness comes
  from the mesh topology (how strongly a vertex's edge directions point into
  the surface), is computed only for the few candidates under the cursor and
  cached, and applies to both the source and the destination pick. Vertex/curve
  point mode only; curve points are unaffected.

## 1.5.4

### Added
- **Wireframe style** preference: choose how the target/hover wireframe is
  drawn. "Automatic" keeps the vertex-threshold behavior, "Cursor-local always"
  never shows a full object wireframe regardless of mesh size, "Native always"
  restores the original overlay everywhere.
- **Hide dragged objects over the target** (object mode, on by default): while
  picking the snap destination, the objects being moved are hidden whenever the
  mouse is over another object so the target geometry is unobstructed. They
  reappear as soon as the mouse leaves the target, and on confirm/cancel.

## 1.5.3

Performance and accuracy pass over the 1.5.x additions, driven by a full audit.

### Performance
- While a heavy object's points are still loading, the closest-point query now
  scans only the newly loaded points on each tick instead of everything so far
  (a per-tick cost that grew with mesh size is now near constant).
- The wireframe's edge-adjacency and grid builds use the default sort instead of
  a stable one (order within a bucket never mattered): roughly halves the
  one-time build per heavy object and the per-orbit rebuild.
- Vertex coordinates are read in float32 (matching Blender's storage, enabling
  the bulk copy path) for the wireframe build and the precision-fit sampling.
- The near-cursor wireframe batch is cached: redraws with an unchanged mouse and
  view reuse the built GPU batch instead of recomputing everything each frame,
  and the batch uploads from numpy directly where supported.
- The wire cache keeps only the objects being displayed (was up to four) and
  never evicts one that is on screen, avoiding repeated multi-second rebuilds
  when sweeping across many heavy objects.

### Fixed
- Precision fit: a part hovering at a uniform standoff over a single flat
  surface is no longer pulled down to touch (indistinguishable from a designed
  offset, so the snap stays exact). Multi-wall seating is unchanged.
- Precision fit: normals are now transformed by the inverse transpose, so
  non-uniformly scaled objects filter and fit correctly.
- The cursor wireframe hides during orbit/zoom instead of drawing a patch
  frozen to the pre-navigation view (it reappears on the next mouse move).
- The grid cell size and the snap search radius are tied to one constant so
  they cannot drift apart.

## 1.5.2

### Fixed
- Precision fit no longer moves a snap that is already aligned. Matches now
  require genuinely opposing surfaces, gap errors are trimmed hard so designed
  clearances and shoulder gaps cannot pull the part (penetrations are kept and
  weighted higher, since those are never by design), and the correction is only
  applied when re-measuring shows the parts actually seat better than before.

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
