from pathlib import Path

import bpy
import bpy_extras
import blf
import gpu
import logging
import numpy as np
import os
import time
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from .quicksnap_utils import State
from .quicksnap_utils import dump
if bpy.app.version >= (3, 4, 0):
    from .quicksnap_shader_gpu_module import shader_2d_image_color, shader_2d_uniform_color, shader_3d_uniform_color, shader_3d_smooth_color, shader_3d_polyline_smooth_color, draw_line_3d_smooth_blend_versionized, draw_polygon_smooth_blend_versionized
else:
    from .quicksnap_shader_legacy import shader_2d_image_color, shader_2d_uniform_color, shader_3d_uniform_color, shader_3d_smooth_color, shader_3d_polyline_smooth_color, draw_line_3d_smooth_blend_versionized, draw_polygon_smooth_blend_versionized

__name_addon__ = '.'.join(__name__.split('.')[:-1])
logger = logging.getLogger(__name_addon__)
square_indices = ((0, 1), (1, 2), (2, 3), (3, 0))
icons = {}


def draw_square_2d(position_x, position_y, size, color=(1, 1, 0, 1), line_width=1, point_width=4):
    """
    Draw a 2D square of size {size}, color {color}, line_width, and draw 2D point of width {point_width}
    if line_width==0: Only draw point.
    if point_width==0: Only draw square.
    """
    if line_width != 1:
        gpu.state.line_width_set(line_width)
    gpu.state.blend_set("ALPHA")
    if line_width > 0:
        vertices = (
            (position_x - size, position_y - size),
            (position_x + size, position_y - size),
            (position_x + size, position_y + size),
            (position_x - size, position_y + size))

        batch = batch_for_shader(shader_2d_uniform_color, 'LINES', {"pos": vertices}, indices=square_indices)
        shader_2d_uniform_color.bind()
        shader_2d_uniform_color.uniform_float("color", color)
        batch.draw(shader_2d_uniform_color)
    if point_width > 0:
        gpu.state.point_size_set(point_width)
        batch = batch_for_shader(shader_2d_uniform_color, 'POINTS', {"pos": [(position_x, position_y)]})
        shader_2d_uniform_color.bind()
        shader_2d_uniform_color.uniform_float("color", color)
        batch.draw(shader_2d_uniform_color)
        gpu.state.point_size_set(5)

    if line_width != 1:
        gpu.state.line_width_set(1)
    gpu.state.blend_set("NONE")


def draw_image(self, position_x=100, position_y=100, size=20, image='MISSING', color=(1, 1, 1, 1),
               color_bg=(0, 0, 0, 1), fade=1):
    """
        Draw an icon in the viewport.
    """
    halfsize = size * .5
    vertices = (
        (position_x - halfsize, position_y - halfsize),
        (position_x + halfsize, position_y - halfsize),
        (position_x + halfsize, position_y + halfsize),
        (position_x - halfsize, position_y + halfsize))
    previous_blend_state = gpu.state.blend_get()
    gpu.state.blend_set("ALPHA")
    if image not in icons:
        texture_name = f'QUICKSNAP_{image}.tif'
        texture_path = get_icons_dir() / texture_name
        if not texture_path.exists():
            texture_path = get_icons_dir() / f'QUICKSNAP_MISSING.tif'
            if not texture_path.exists():
                return
        if texture_name in bpy.data.images:
            bpy.data.images.remove(bpy.data.images[f'QUICKSNAP_{image}.tif'])
        img = bpy.data.images.load(str(texture_path), check_existing=True)
        icons[image] = gpu.texture.from_image(img)
    batch = batch_for_shader(
        shader_2d_image_color, 'TRI_FAN',
        {
            "pos": vertices,
            "texCoord": ((0, 0), (1, 0), (1, 1), (0, 1)),
        },
    )
    shader_2d_image_color.bind()
    shader_2d_image_color.uniform_float("Color", color)
    shader_2d_image_color.uniform_float("Color_bg", color_bg)
    shader_2d_image_color.uniform_float("Fade", fade)
    shader_2d_image_color.uniform_sampler("Image", icons[image])
    batch.draw(shader_2d_image_color)

    gpu.state.blend_set(previous_blend_state)


def draw_line_2d(source_x, source_y, target_x, target_y, color=(1, 1, 0, 1), line_width=1):
    """
        Draw a 2d line in the viewport.
    """
    if line_width != 1:
        gpu.state.line_width_set(line_width)
    gpu.state.blend_set("ALPHA")
    vertices = (
        (source_x, source_y),
        (target_x, target_y))

    batch = batch_for_shader(shader_2d_uniform_color, 'LINES', {"pos": vertices})
    shader_2d_uniform_color.bind()
    shader_2d_uniform_color.uniform_float("color", color)
    batch.draw(shader_2d_uniform_color)

    if line_width != 1:
        gpu.state.line_width_set(1)
    gpu.state.blend_set("NONE")


def draw_line_3d(source, target, color=(1, 1, 0, 1), line_width=1, depth_test=False):
    """
        Draw a 3d line in the viewport.
    """
    if line_width != 1:
        gpu.state.line_width_set(line_width)
    gpu.state.blend_set("ALPHA")

    if depth_test:
        gpu.state.depth_test_set("LESS")
    vertices = (
        (source[0], source[1], source[2]),
        (target[0], target[1], target[2]))

    batch = batch_for_shader(shader_3d_uniform_color, 'LINES', {"pos": vertices})
    shader_3d_uniform_color.bind()
    shader_3d_uniform_color.uniform_float("color", color)
    batch.draw(shader_3d_uniform_color)
    if line_width != 1:
        gpu.state.line_width_set(1)
    gpu.state.blend_set("NONE")
    if depth_test:
        gpu.state.depth_test_set("NONE")


def draw_lines_3d(coords, color=(1, 1, 0, 1), line_width=1, depth_test=False):
    """
        Draw many 3d line segments in a single LINES batch. coords is a flat list of point pairs.
    """
    if coords is None or len(coords) == 0:
        return
    if line_width != 1:
        gpu.state.line_width_set(line_width)
    gpu.state.blend_set("ALPHA")
    if depth_test:
        gpu.state.depth_test_set("LESS")

    batch = batch_for_shader(shader_3d_uniform_color, 'LINES', {"pos": coords})
    shader_3d_uniform_color.bind()
    shader_3d_uniform_color.uniform_float("color", color)
    batch.draw(shader_3d_uniform_color)

    if line_width != 1:
        gpu.state.line_width_set(1)
    gpu.state.blend_set("NONE")
    if depth_test:
        gpu.state.depth_test_set("NONE")


def _gather_ranges(starts, ends, values):
    """Concatenate values[starts[i]:ends[i]] for all i, vectorized. Returns None when empty."""
    lens = ends - starts
    total = int(lens.sum())
    if total == 0:
        return None
    cum = np.zeros(len(lens), dtype=np.int64)
    np.cumsum(lens[:-1], out=cum[1:])
    idx = np.arange(total, dtype=np.int64) - np.repeat(cum, lens) + np.repeat(starts, lens)
    return values[idx]


def _build_wire_static(self, context, object_name):
    """
        Fetch the per-object data for the cursor-local wireframe once: world-space vertex coords,
        the edge list, and a vertex->edge adjacency (CSR) so per-frame lookups only touch edges
        around the cursor. Kept until the operator ends or 'ignore modifiers' changes.
    """
    obj = bpy.data.objects.get(object_name)
    if obj is None or obj.type != 'MESH':
        return None

    # Same evaluated/raw data choice as add_object_data, so the wire matches the snappable mesh.
    is_selected = object_name in self.selection_objects
    if is_selected:
        use_evaluated = self.object_mode and not self.settings.ignore_modifiers
    else:
        use_evaluated = not self.settings.ignore_modifiers
    if use_evaluated:
        data = obj.evaluated_get(context.evaluated_depsgraph_get()).data
    else:
        data = obj.data

    n_verts = len(data.vertices)
    n_edges = len(data.edges)
    if n_verts == 0 or n_edges == 0:
        return None

    co = np.empty(n_verts * 3, dtype=np.float64)
    data.vertices.foreach_get('co', co)
    co.shape = (n_verts, 3)
    matrix = np.array(obj.matrix_world, dtype=np.float64)
    vert_world = (co @ matrix[:3, :3].T + matrix[:3, 3]).astype(np.float32)

    edge_verts = np.zeros(n_edges * 2, dtype=np.int32)
    data.edges.foreach_get('vertices', edge_verts)
    flat = edge_verts
    edge_verts = edge_verts.reshape(n_edges, 2)

    # CSR adjacency: adj_edge[adj_off[v]:adj_off[v+1]] = edges touching vert v.
    order = np.argsort(flat, kind='stable')
    adj_edge = (order // 2).astype(np.int32)
    counts = np.bincount(flat, minlength=n_verts)
    adj_off = np.zeros(n_verts + 1, dtype=np.int64)
    np.cumsum(counts, out=adj_off[1:])

    return {
        "vert_world": vert_world,
        "edge_verts": edge_verts,
        "adj_off": adj_off,
        "adj_edge": adj_edge,
        "matrix": None,  # per-view part below
    }


def _build_wire_view(cache, snapdata, radius):
    """
        Per-view part of the wire cache: project the verts to screen space and bin the visible ones
        into a pixel grid (cell = wire radius). Redone when the view matrix or the radius changes.
    """
    matrix = np.array(snapdata.perspective_matrix, dtype=np.float32)
    world = cache["vert_world"]
    # Only rows x, y, w of the projection are needed for the screen-distance test.
    proj = world @ matrix[[0, 1, 3], :3].T + matrix[[0, 1, 3], 3]
    w = proj[:, 2]
    with np.errstate(divide='ignore', invalid='ignore'):
        sx = snapdata.width_half + (proj[:, 0] / w) * snapdata.width_half
        sy = snapdata.height_half + (proj[:, 1] / w) * snapdata.height_half
    screen = np.column_stack((sx, sy))

    # Grid only holds verts with a meaningful screen position; edges to the others are still drawn
    # through the adjacency of their near endpoint. The magnitude clamp keeps the int cast safe.
    cell = max(int(radius), 10)
    usable = (w > 0) & np.isfinite(sx) & np.isfinite(sy) & (np.abs(sx) < 1e6) & (np.abs(sy) < 1e6)
    grid_ids = np.nonzero(usable)[0]
    if len(grid_ids) > 0:
        cx = np.floor(screen[grid_ids, 0] / cell).astype(np.int64)
        cy = np.floor(screen[grid_ids, 1] / cell).astype(np.int64)
        min_x = int(cx.min())
        min_y = int(cy.min())
        cx -= min_x
        cy -= min_y
        ncols = int(cx.max()) + 1
        cell_id = cy * ncols + cx
        order = np.argsort(cell_id, kind='stable')
        grid = {
            "cell_id_sorted": cell_id[order],
            "vert_ids": grid_ids[order].astype(np.int64),
            "ncols": ncols, "min_x": min_x, "min_y": min_y,
        }
    else:
        grid = {"cell_id_sorted": np.empty(0, dtype=np.int64), "vert_ids": np.empty(0, dtype=np.int64),
                "ncols": 1, "min_x": 0, "min_y": 0}

    cache["screen"] = screen
    cache["grid"] = grid
    cache["cell"] = cell
    cache["matrix"] = snapdata.perspective_matrix.copy()


def _wire_verts_near_mouse(cache, mouse_x, mouse_y, radius):
    """Vert indices within radius px of the mouse, via the 3x3 grid cells around it."""
    grid = cache["grid"]
    vert_ids = grid["vert_ids"]
    if len(vert_ids) == 0:
        return None
    cell = cache["cell"]
    cell_sorted = grid["cell_id_sorted"]
    ncols = grid["ncols"]
    mcx = int(np.floor(mouse_x / cell)) - grid["min_x"]
    mcy = int(np.floor(mouse_y / cell)) - grid["min_y"]
    chunks = []
    for dy in (-1, 0, 1):
        cyy = mcy + dy
        if cyy < 0:
            continue
        for dx in (-1, 0, 1):
            cxx = mcx + dx
            if cxx < 0 or cxx >= ncols:
                continue
            cid = cyy * ncols + cxx
            lo = np.searchsorted(cell_sorted, cid, side='left')
            hi = np.searchsorted(cell_sorted, cid, side='right')
            if hi > lo:
                chunks.append(vert_ids[lo:hi])
    if not chunks:
        return None
    candidates = np.concatenate(chunks)
    screen = cache["screen"]
    dx = screen[candidates, 0] - mouse_x
    dy = screen[candidates, 1] - mouse_y
    near = candidates[(dx * dx + dy * dy) < (radius * radius)]
    return near if len(near) > 0 else None


def ensure_wire_static(self, context, object_name):
    """
        Get or build the static wire data for an object. Called from the modal side when an object
        is first flagged heavy, so the one-time build does not happen inside the draw handler.
    """
    cache = self.local_wire_data.get(object_name)
    if cache is not None:
        return cache
    cache = _build_wire_static(self, context, object_name)
    if cache is None:
        return None
    # Static data for a very dense mesh is large; keep only a few objects around.
    if len(self.local_wire_data) >= 4:
        self.local_wire_data.pop(next(iter(self.local_wire_data)))
    self.local_wire_data[object_name] = cache
    return cache


def build_local_wire_cache(self, context, snapdata, object_name):
    """
        Return the wire cache for the object, building the static part once and the view part
        whenever the view matrix or the radius setting changed. Returns None if no wire.
    """
    cache = ensure_wire_static(self, context, object_name)
    if cache is None:
        return None
    radius = self.settings.local_wireframe_radius
    if cache.get("matrix") != snapdata.perspective_matrix or cache.get("cell") != max(int(radius), 10):
        _build_wire_view(cache, snapdata, radius)
    return cache


def draw_local_wireframe(self, context, snapdata, object_name):
    """
        Draw the mesh edges near the cursor for heavy objects (cheaper than the native show_wire).
        An edge is drawn if either endpoint is within the radius, so long edges are drawn in full.
    """
    cache = build_local_wire_cache(self, context, snapdata, object_name)
    if cache is None:
        return

    radius = self.settings.local_wireframe_radius
    near_verts = _wire_verts_near_mouse(cache, self.mouse_position[0], self.mouse_position[1], radius)
    if near_verts is None:
        return

    # Edges incident to the near verts, via the adjacency. Dedup so alpha does not double up.
    adj_off = cache["adj_off"]
    edge_ids = _gather_ranges(adj_off[near_verts], adj_off[near_verts + 1], cache["adj_edge"])
    if edge_ids is None:
        return
    selected = cache["edge_verts"][np.unique(edge_ids)]

    vert_world = cache["vert_world"]
    coords = np.empty((len(selected) * 2, 3), dtype=np.float32)
    coords[0::2] = vert_world[selected[:, 0]]
    coords[1::2] = vert_world[selected[:, 1]]

    # Depth test (default) hides the far side so only the surface you see is wireframed; x-ray draws
    # through. When depth testing, nudge the verts towards the camera to avoid z-fighting the surface.
    depth_test = not self.settings.local_wireframe_xray
    if depth_test:
        region3d = context.space_data.region_3d
        camera_position = np.array(region3d.view_matrix.inverted().translation, dtype=np.float32)
        cam_to = camera_position[None, :] - coords
        if not region3d.is_perspective:
            camera_vector = np.array(region3d.view_rotation @ Vector((0.0, 0.0, -1.0)), dtype=np.float32)
            dist = np.sqrt(np.einsum('ij,ij->i', cam_to, cam_to))
            coords = coords - camera_vector[None, :] * dist[:, None] * 0.01
        else:
            coords = coords + cam_to * 0.01

    color = (*self.settings.local_wireframe_color, self.settings.local_wireframe_opacity)
    draw_lines_3d(coords.tolist(), color=color, line_width=1, depth_test=depth_test)


def index_allowed(allowed_indices, value):
    """
        Membership test on a per-object allowed-index array. None allows everything. The arrays
        come from ObjectPointData (arange + filters) so they are ascending: binary search instead
        of a linear scan, which matters on multi-million point objects.
    """
    if allowed_indices is None:
        return True
    pos = np.searchsorted(allowed_indices, value)
    return pos < len(allowed_indices) and allowed_indices[pos] == value


def _blf_size(font_id, size):
    """blf.size dropped its dpi argument in Blender 4.0."""
    if bpy.app.version >= (4, 0, 0):
        blf.size(font_id, size)
    else:
        blf.size(font_id, size, 72)


def draw_perf_hud(self, context):
    """
        Debug-only HUD (shown when log level is Debug): point count, query mode and frame timings.
        Handy for recording before/after performance captures.
    """
    snapdata = self.snapdata_source if self.current_state == State.IDLE else self.snapdata_target
    if snapdata is None:
        return
    mode = "numpy (no KDTree)" if getattr(snapdata, "use_numpy_query", False) else "KDTree"
    lines = [
        "QuickSnap perf",
        f"points: {getattr(snapdata, 'added_points_np', 0):,}",
        f"query mode: {mode}",
        f"query: {getattr(snapdata, 'last_query_ms', 0.0):.2f} ms",
        f"wire draw: {getattr(self, 'perf_wire_ms', 0.0):.2f} ms",
        f"ingest total: {getattr(snapdata, 'processing_time_total', 0.0):.2f} s",
    ]
    font_id = 0
    x = 20
    y = context.region.height - 40
    blf.color(font_id, 1, 1, 1, 1)
    _blf_size(font_id, 16)
    for line in lines:
        blf.position(font_id, x, y, 0)
        blf.draw(font_id, line)
        y -= 22


def draw_line_3d_smooth_blend(source, target, color_a=(1, 0, 0, 1), color_b=(0, 1, 0, 1), line_width=1,
                              depth_test=False):
    """
        Draw a smooth blend line in the viewport.
    """
    draw_line_3d_smooth_blend_versionized(source, target, color_a, color_b, line_width,depth_test)       

def draw_polygon_smooth_blend(points, indices, color, depth_test):
    """
        Draw a smooth blend polygon in the viewport.
    """
    draw_polygon_smooth_blend_versionized(points, indices, color, depth_test)


def draw_points_3d(coords, color=(1, 1, 0, 1), point_width=3, depth_test=False):
    """
        Draw a list of points in the viewport.
    """
    gpu.state.blend_set("ALPHA")
    if depth_test:
        gpu.state.depth_test_set("LESS")

    gpu.state.point_size_set(point_width)
    batch = batch_for_shader(shader_3d_uniform_color, 'POINTS', {"pos": coords})
    shader_3d_uniform_color.bind()
    shader_3d_uniform_color.uniform_float("color", color)
    batch.draw(shader_3d_uniform_color)
    gpu.state.point_size_set(5)

    gpu.state.blend_set("NONE")
    if depth_test:
        gpu.state.depth_test_set("NONE")


ui_scale = bpy.context.preferences.system.ui_scale
icon_color = {
    State.IDLE: (0.917, 0.462, 0, .6),
    State.SOURCE_PICKED: (1, 1, 0, .6)
}

icon_display_duration = 2
fade_duration = 0.2



def draw_callback_2d(self, context):
    """
        Draw all QuickSnap 2D UI: Icons, source/target square. rubberband/
    """
    if self.settings.log_level == 2:
        draw_perf_hud(self, context)
    square_width=self.settings.selection_square_size
    current_time = time.time()
    if self.settings.snap_target_type_icon != 'NEVER' and current_time < self.icon_display_time + icon_display_duration or self.settings.snap_target_type_icon == 'ALWAYS':
        fade = 1

        if self.settings.snap_target_type_icon == 'FADE' and current_time > self.icon_display_time + \
                icon_display_duration - fade_duration:
            fade = (self.icon_display_time - current_time + icon_display_duration) / fade_duration
        if self.current_state == State.IDLE:
            draw_image(self, self.mouse_position[0] + 30, self.mouse_position[1] - 30, 22 * ui_scale,
                       image=self.snapdata_source.snap_type, color=icon_color[self.current_state], fade=fade)
        elif self.current_state == State.SOURCE_PICKED:
            draw_image(self, self.mouse_position[0] + 30, self.mouse_position[1] - 30, 22 * ui_scale,
                       image=self.snapdata_target.snap_type, color=icon_color[self.current_state], fade=fade)

    if self.closest_source_id >= 0:
        
        source_position_3d = self.snapdata_source.world_space[self.closest_source_id]
        source_position_2d = bpy_extras.view3d_utils.location_3d_to_region_2d(context.region,
                                                                              context.space_data.region_3d,
                                                                              source_position_3d)
        source_x, source_y = source_position_2d[0], source_position_2d[1]
        # Source selection
        if self.current_state == State.IDLE:  # no source picked
            draw_square_2d(source_x, source_y, square_width)

        else:
            # logger.info(f"source picked . self.target2d={self.target2d} -  self.settings.draw_rubberband={self.settings.draw_rubberband}")
            if self.closest_target_id >= 0:
                color = (0, 1, 0, 1)
            else:
                color = (1, 1, 0, 1)
            if self.settings.draw_rubberband:
                draw_square_2d(source_x, source_y, square_width, color=color)
            # if self.target2d:
            if self.target is not None:
                target_position_2d = bpy_extras.view3d_utils.location_3d_to_region_2d(context.region,
                                                                                      context.space_data.region_3d,
                                                                                      self.target)
                target_x, target_y = target_position_2d[0], target_position_2d[1]

                if self.closest_target_id >= 0:
                    snap_target_2d = bpy_extras.view3d_utils.location_3d_to_region_2d(
                        context.region,
                        context.space_data.region_3d,
                        self.snapdata_target.world_space[self.closest_target_id])
                    if len(self.snapping) > 0:
                        draw_square_2d(target_x, target_y, square_width,
                                       color=color, line_width=0)  # dot to target
                        draw_square_2d(snap_target_2d[0], snap_target_2d[1], square_width, color=color)  # square to snapped point
                    else:
                        draw_square_2d(target_x, target_y, square_width, color=color)
                else:
                    draw_square_2d(target_x, target_y, square_width, color=color,
                                   line_width=0)  # dot to target

                if self.settings.draw_rubberband:
                    draw_line_2d(source_x, source_y, target_x, target_y, line_width=1, color=color)

    elif self.current_state == State.IDLE:
        # Draw grey square when tool is enabled, additional indication that the tool is active
        draw_square_2d(self.mouse_position[0], self.mouse_position[1], square_width, color=(1, 1, 1, 0.3), point_width=0)


def draw_snap_axis(self, context):
    """
    Draw axis lines depending on QuickSNap operator snapping settings.
    """
    if self.closest_source_id >= 0 and self.snapping != "":
        point_position = self.snapdata_source.world_space[self.closest_source_id]
        if self.snapping_local:
            for object_name in self.selection_objects:
                obj_matrix = bpy.data.objects[object_name].matrix_world

                if 'X' in self.snapping:
                    axis_x = Vector((obj_matrix[0][0], obj_matrix[1][0], obj_matrix[2][0])).normalized()
                    start = point_position + axis_x * 10 ** 5
                    end = point_position - axis_x * 10 ** 5
                    draw_line_3d(start, end, (1, 0.5, 0.5, 0.6), 1)
                if 'Y' in self.snapping:
                    axis_y = Vector((obj_matrix[0][1], obj_matrix[1][1], obj_matrix[2][1])).normalized()
                    start = point_position + axis_y * 10 ** 5
                    end = point_position - axis_y * 10 ** 5
                    draw_line_3d(start, end, (0.5, 1, 0.5, 0.6), 1)
                if 'Z' in self.snapping:
                    axis_z = Vector((obj_matrix[0][2], obj_matrix[1][2], obj_matrix[2][2])).normalized()
                    start = point_position + axis_z * 10 ** 5
                    end = point_position - axis_z * 10 ** 5
                    draw_line_3d(start, end, (0.2, 0.6, 1, 0.6), 1)
        else:
            if 'X' in self.snapping:
                start = point_position.copy()
                start[0] = start[0] + 10 ** 5
                end = point_position.copy()
                end[0] = end[0] - 10 ** 5
                draw_line_3d(start, end, (1, 0.5, 0.5, 0.6), 1)
            if 'Y' in self.snapping:
                start = point_position.copy()
                start[1] = start[1] + 10 ** 5
                end = point_position.copy()
                end[1] = end[1] - 10 ** 5
                draw_line_3d(start, end, (0.5, 1, 0.5, 0.6), 1)
            if 'Z' in self.snapping:
                start = point_position.copy()
                start[2] = start[2] + 10 ** 5
                end = point_position.copy()
                end[2] = end[2] - 10 ** 5
                draw_line_3d(start, end, (0.2, 0.6, 1, 0.6), 1)


indices_bounds = (
    (0, 1), (1, 2), (2, 3), (3, 0),
    (4, 5), (5, 6), (6, 7), (7, 4),
    (0, 4), (1, 5), (2, 6), (3, 7),
)


def draw_bounds(points, color=(1, 1, 0, 1), line_width=3, depth_test=False):
    """
        Draw edges of bounds cube. Inputs bounds vertices.
    """
    if line_width != 1:
        gpu.state.line_width_set(line_width)
    gpu.state.blend_set("ALPHA")
    if depth_test:
        gpu.state.depth_test_set("LESS")
    vertices = points

    batch = batch_for_shader(shader_3d_uniform_color, 'LINES', {"pos": vertices}, indices=indices_bounds)
    shader_3d_uniform_color.bind()
    shader_3d_uniform_color.uniform_float("color", color)
    batch.draw(shader_3d_uniform_color)
    if line_width != 1:
        gpu.state.line_width_set(1)
    gpu.state.blend_set("NONE")
    if depth_test:
        gpu.state.depth_test_set("NONE")


sel_color = bpy.context.preferences.themes[0].view_3d.object_active
point_color = {
    True: (sel_color[0], sel_color[1], sel_color[2]),
    False: (0, 0, 0)
}


def draw_callback_3d(self, context):
    """
        Draw all 3D ui for QuickSnap: Snap axis, edge/points highlight.
    """
    draw_snap_axis(self, context)
    # Cursor-local wireframe for heavy objects (instead of native show_wire).
    if getattr(self, "local_wire_objects", None):
        wire_snapdata = self.snapdata_source if self.current_state == State.IDLE else self.snapdata_target
        if wire_snapdata is not None:
            wire_start = time.perf_counter()
            for wire_object_name in list(self.local_wire_objects):
                draw_local_wireframe(self, context, wire_snapdata, wire_object_name)
            self.perf_wire_ms = (time.perf_counter() - wire_start) * 1000.0
    else:
        self.perf_wire_ms = 0.0
    if self.current_state == State.IDLE and not (self.object_mode and self.no_selection):
        coords = [self.snapdata_source.world_space[objectid] for objectid in self.snapdata_source.origins_map]
    else:
        coords = [self.snapdata_target.world_space[objectid] for objectid in self.snapdata_target.origins_map]
    if (self.current_state == State.IDLE and self.snapdata_source.snap_type == 'ORIGINS')\
            or (self.current_state == State.SOURCE_PICKED and self.snapdata_target.snap_type == 'ORIGINS'):
        draw_points_3d(coords, point_width=5)
    elif self.settings.snap_objects_origin == 'ALWAYS':
        draw_points_3d(coords, color=(1, 1, 0, 0.5), point_width=3, depth_test=True)

    if self.settings.highlight_target_vertex_edges or self.settings.display_potential_target_points:
        if self.current_state == State.IDLE:
            if not self.settings.ignore_modifiers and self.hover_object != '' and \
                    self.settings.display_potential_target_points:
                if self.hover_object not in self.source_allowed_indices:
                    if not (self.no_selection and self.object_mode):
                        allowed_indices = self.snapdata_source.indices[:self.snapdata_source.added_points_np]
                        object_indices = self.snapdata_source.object_id[:self.snapdata_source.added_points_np]
                        self.source_allowed_indices[self.hover_object] = allowed_indices[
                            object_indices == self.snapdata_source.scene_meshes.index(self.hover_object)]
                    else:
                        self.source_allowed_indices[self.hover_object] = None
                draw_face_center(self, context,
                                 target_object=self.hover_object,
                                 face_index=self.target_face_index,
                                 allowed_indices=self.source_allowed_indices[self.hover_object],
                                 snap_type=self.snapdata_source.snap_type,
                                 ignore_modifiers=self.settings.ignore_modifiers or not self.object_mode,
                                 color=point_color[not self.no_selection]
                                 )
            if self.closest_source_id in self.snapdata_source.origins_map:
                obj_name = self.snapdata_source.origins_map[self.closest_source_id]
                if obj_name not in self.target_bounds:
                    obj = bpy.data.objects[obj_name]
                    bound_points = [v[:] for v in obj.bound_box]

                    region3d = context.space_data.region_3d
                    camera_position = region3d.view_matrix.inverted().translation
                    camera_vector = region3d.view_rotation @ Vector((0.0, 0.0, -1.0))
                    is_ortho = region3d.view_perspective == 'ORTHO'
                    points = [obj.matrix_world @ Vector(point) for point in bound_points]
                    self.target_bounds[obj_name] = [add_camera_offset(point,
                                                                      camera_position,
                                                                      camera_vector,
                                                                      is_ortho) for point in points]
                draw_bounds(self.target_bounds[obj_name], color=(1, 1, 0, 0.8), line_width=1, depth_test=True)
                return
            if self.settings.highlight_target_vertex_edges:
                draw_edge_highlight(context,
                                    target_object=self.target_object,
                                    target_id=self.closest_source_id,
                                    snapdata=self.snapdata_source,
                                    highlight_data=self.source_highlight_data,
                                    npdata=self.source_npdata,
                                    ignore_modifiers=self.settings.ignore_modifiers or not self.object_mode,
                                    width=self.settings.edge_highlight_width,
                                    color=self.settings.edge_highlight_color_source,
                                    opacity=self.settings.edge_highlight_opacity)

        elif self.current_state == State.SOURCE_PICKED:
            if not self.settings.ignore_modifiers:
                if self.hover_object != '' and self.settings.display_potential_target_points:
                    is_selection = self.hover_object in self.selection_objects
                    if self.hover_object not in self.target_allowed_indices:
                        if is_selection:
                            allowed_indices = self.snapdata_target.indices[:self.snapdata_target.added_points_np]
                            object_indices = self.snapdata_target.object_id[:self.snapdata_target.added_points_np]
                            self.target_allowed_indices[self.hover_object] = \
                                allowed_indices[
                                    object_indices == self.snapdata_target.scene_meshes.index(self.hover_object)]
                        else:
                            self.target_allowed_indices[self.hover_object] = None
                    draw_face_center(self, context,
                                     target_object=self.hover_object,
                                     face_index=self.target_face_index,
                                     allowed_indices=self.target_allowed_indices[self.hover_object],
                                     snap_type=self.snapdata_target.snap_type,
                                     ignore_modifiers=self.settings.ignore_modifiers or (
                                             is_selection and not self.object_mode),
                                     color=point_color[False]
                                     )
            if self.closest_target_id in self.snapdata_target.origins_map:
                obj_name = self.snapdata_target.origins_map[self.closest_target_id]
                if obj_name not in self.target_bounds:
                    obj = bpy.data.objects[obj_name]
                    bound_points = [v[:] for v in obj.bound_box]

                    region3d = context.space_data.region_3d
                    camera_position = region3d.view_matrix.inverted().translation
                    camera_vector = region3d.view_rotation @ Vector((0.0, 0.0, -1.0))
                    is_ortho = region3d.view_perspective == 'ORTHO'
                    points = [obj.matrix_world @ Vector(point) for point in bound_points]
                    self.target_bounds[obj_name] = [add_camera_offset(point,
                                                                      camera_position,
                                                                      camera_vector,
                                                                      is_ortho) for point in points]

                draw_bounds(self.target_bounds[obj_name], color=(1, 1, 0, 0.8), line_width=1, depth_test=True)
                return
            if self.settings.highlight_target_vertex_edges:
                draw_edge_highlight(context,
                                    target_object=self.target_object,
                                    target_id=self.closest_target_id,
                                    snapdata=self.snapdata_target,
                                    highlight_data=self.target_highlight_data,
                                    npdata=self.target_npdata,
                                    ignore_modifiers=self.settings.ignore_modifiers or (
                                            self.target_object in self.selection_objects and not self.object_mode),
                                    width=self.settings.edge_highlight_width,
                                    color=self.settings.edge_highlight_color_target,
                                    opacity=self.settings.edge_highlight_opacity)


def add_camera_offset(co, camera_position, camera_vector, is_ortho):
    """
    Offset a point towards the camera position to avoid z-fighting.
    """
    cam_point_vector = camera_position - co
    if is_ortho:
        return co - camera_vector * np.sqrt(cam_point_vector.dot(cam_point_vector)) * 0.01
    else:
        return co + cam_point_vector * 0.01


def draw_edge_highlight(context,
                        target_object,
                        target_id,
                        snapdata,
                        highlight_data,
                        npdata,
                        ignore_modifiers,
                        width=2,
                        color=(1, 1, 0),
                        opacity=1
                        ):
    """
        Store necessary information and draw edge highlight of tht target point/edge/face.
    """
    if target_id >= 0:
        if len(snapdata.indices) <= target_id:
            return
        vert_index = snapdata.indices[target_id]
        if vert_index < 0:
            return
        vert_object = bpy.data.objects[target_object]
        if vert_object.type != "MESH":
            return
        if target_object not in highlight_data:
            highlight_data[target_object] = {}
        if vert_index not in highlight_data[target_object]:
            matrix = vert_object.matrix_world
            if ignore_modifiers:
                data = vert_object.data
            else:
                data = vert_object.evaluated_get(context.evaluated_depsgraph_get()).data

            if snapdata.snap_type == 'POINTS':
                if target_object not in npdata:
                    npdata[target_object] = {}
                if "edge_verts" not in npdata[target_object]:
                    arr = np.zeros(len(data.edges) * 2, dtype=int)
                    data.edges.foreach_get('vertices', arr)
                    arr.shape = (len(data.edges), 2)
                    npdata[target_object]["edge_verts"] = arr

                filter_left = npdata[target_object]["edge_verts"][
                    npdata[target_object]["edge_verts"][:, 0] == vert_index]
                filter_right = npdata[target_object]["edge_verts"][
                    npdata[target_object]["edge_verts"][:, 1] == vert_index]
                highlight_data[target_object][vert_index] = {}
                highlight_data[target_object][vert_index]["edges"] = []
                for match in filter_left:
                    highlight_data[target_object][vert_index]["edges"].append((matrix @ data.vertices[match[0]].co,
                                                                               matrix @ data.vertices[match[1]].co))
                for match in filter_right:
                    highlight_data[target_object][vert_index]["edges"].append((matrix @ data.vertices[match[1]].co,
                                                                               matrix @ data.vertices[match[0]].co))
            elif snapdata.snap_type == 'MIDPOINTS':
                verts = data.vertices
                edges = data.edges
                if len(edges) <= vert_index:
                    return
                highlight_data[target_object][vert_index] = {}
                highlight_data[target_object][vert_index]["edges"] = []
                highlight_data[target_object][vert_index]["edges"].append(
                    (snapdata.world_space[target_id],
                     matrix @ verts[edges[vert_index].vertices[0]].co))
                highlight_data[target_object][vert_index]["edges"].append(
                    (snapdata.world_space[target_id],
                     matrix @ verts[edges[vert_index].vertices[1]].co))

            elif snapdata.snap_type == 'FACES':
                if target_object not in npdata:
                    npdata[target_object] = {}
                if "polygon_loop_tri_idx" not in npdata[target_object]:
                    data.calc_loop_triangles()
                    arr = np.zeros(len(data.loop_triangles), dtype=int)
                    data.loop_triangles.foreach_get('polygon_index', arr)
                    npdata[target_object]["polygon_loop_tri_idx"] = arr
                    arr2 = np.zeros(len(data.loop_triangles) * 3, dtype=int)
                    data.loop_triangles.foreach_get('vertices', arr2)
                    arr2.shape = (len(data.loop_triangles), 3)
                    npdata[target_object]["polygon_loop_verts"] = arr2

                verts = data.vertices
                polygons = data.polygons
                loops = data.loops
                highlight_data[target_object][vert_index] = {}
                highlight_data[target_object][vert_index]["edges"] = []
                highlight_data[target_object][vert_index]["face_co"] = []
                highlight_data[target_object][vert_index]["face_indices"] = []
                if len(polygons) <= vert_index:
                    return
                poly = polygons[vert_index]
                region3d = context.space_data.region_3d
                camera_position = region3d.view_matrix.inverted().translation
                camera_vector = region3d.view_rotation @ Vector((0.0, 0.0, -1.0))
                is_ortho = not region3d.is_perspective

                vert_local_index = {}
                verts_co = {}
                for idx in range(0, poly.loop_total):
                    current_loop = poly.loop_start + idx
                    loop_second = poly.loop_start + ((idx + 1) % poly.loop_total)
                    vert_index_a = loops[current_loop].vertex_index
                    vert_index_b = loops[loop_second].vertex_index
                    if vert_index_a not in verts_co:
                        verts_co[vert_index_a] = matrix @ verts[vert_index_a].co
                        verts_co[vert_index_a] = add_camera_offset(verts_co[vert_index_a],
                                                                   camera_position,
                                                                   camera_vector,
                                                                   is_ortho)
                        new_index = len(highlight_data[target_object][vert_index]["face_co"])
                        vert_local_index[vert_index_a] = new_index
                        highlight_data[target_object][vert_index]["face_co"].append(verts_co[vert_index_a])
                    if vert_index_b not in verts_co:
                        verts_co[vert_index_b] = matrix @ verts[vert_index_b].co
                        verts_co[vert_index_b] = add_camera_offset(verts_co[vert_index_b],
                                                                   camera_position,
                                                                   camera_vector,
                                                                   is_ortho)

                        new_index = len(highlight_data[target_object][vert_index]["face_co"])
                        vert_local_index[vert_index_b] = new_index
                        highlight_data[target_object][vert_index]["face_co"].append(verts_co[vert_index_b])
                    highlight_data[target_object][vert_index]["edges"].append(
                        (verts_co[vert_index_a], verts_co[vert_index_b]))

                filtered = np.argwhere(npdata[target_object]["polygon_loop_tri_idx"] == vert_index)
                for triangle_index in filtered:
                    triangle = npdata[target_object]["polygon_loop_verts"][triangle_index].flatten()
                    highlight_data[target_object][vert_index]["face_indices"].extend(
                        [[vert_local_index[vertid] for vertid in triangle]])

        if snapdata.snap_type == 'POINTS':
            alpha_end = 0
        else:
            alpha_end = opacity

        for edge in highlight_data[target_object][vert_index]["edges"]:
            draw_line_3d_smooth_blend(edge[0],
                                      edge[1],
                                      color_a=(*color, opacity),
                                      color_b=(*color, alpha_end),
                                      line_width=width, depth_test=False)
        if snapdata.snap_type == 'FACES':
            draw_polygon_smooth_blend(highlight_data[target_object][vert_index]["face_co"],
                                      highlight_data[target_object][vert_index]["face_indices"],
                                      color=(*color, 0.1),
                                      depth_test=True)


def draw_face_center(self, context,
                     target_object,
                     face_index,
                     allowed_indices,
                     snap_type,
                     ignore_modifiers,
                     color):
    """
        Store necessary information and draw points of the target point/edge/face.
    """
    if face_index < 0 or target_object == '':
        return
    obj = bpy.data.objects[target_object]
    if obj.type != 'MESH':
        return
    if ignore_modifiers:
        data = obj.data
    else:
        data = obj.evaluated_get(context.evaluated_depsgraph_get()).data


    region3d = context.space_data.region_3d
    camera_position = region3d.view_matrix.inverted().translation
    camera_vector = region3d.view_rotation @ Vector((0.0, 0.0, -1.0))
    is_ortho = not region3d.is_perspective
    if snap_type == 'FACES':
        # and face_index in allowed_indices
        # print(f"face index:{face_index}")
        # print(f"len(data.polygons):{len(data.polygons)}")
        if face_index < len(data.polygons) and index_allowed(allowed_indices, face_index):
            target_polygon = data.polygons[face_index]
            center = obj.matrix_world @ target_polygon.center
            region3d = context.space_data.region_3d
            camera_position = region3d.view_matrix.inverted().translation
            center = add_camera_offset(center,
                                       camera_position,
                                       camera_vector,
                                       is_ortho)
            draw_points_3d([center], color=(*color, 1), point_width=4,
                           depth_test=True)

    elif snap_type == 'MIDPOINTS':
        if face_index < len(data.polygons):
            target_polygon = data.polygons[face_index]
            camera_position = context.space_data.region_3d.view_matrix.inverted().translation
            midpoints = []
            for loop_index in range(0, target_polygon.loop_total):
                current_loop = data.loops[target_polygon.loop_start + loop_index]
                if not index_allowed(allowed_indices, current_loop.edge_index):
                    continue
                loop_second = data.loops[target_polygon.loop_start + ((loop_index + 1) % target_polygon.loop_total)]
                midpoint = obj.matrix_world @ ((data.vertices[current_loop.vertex_index].co +
                                                data.vertices[loop_second.vertex_index].co) / 2)
                midpoint = add_camera_offset(midpoint,
                                             camera_position,
                                             camera_vector,
                                             is_ortho)
                midpoints.append(midpoint)
            draw_points_3d(midpoints, color=(*color, 1), point_width=4, depth_test=True)
            
    # Draw verts points if not in edit mode + vertex mode
    elif snap_type == 'POINTS' and not (not self.object_mode and context.scene.tool_settings.mesh_select_mode[0]):
        if face_index < len(data.polygons):
            target_polygon = data.polygons[face_index]
            camera_position = context.space_data.region_3d.view_matrix.inverted().translation
            points = []
            for vert_id in target_polygon.vertices:
                if not index_allowed(allowed_indices, vert_id):
                    continue
                point = obj.matrix_world @ data.vertices[vert_id].co
                point = add_camera_offset(point,
                                          camera_position,
                                          camera_vector,
                                          is_ortho)
                points.append(point)
            draw_points_3d(points, color=(*color, 1), point_width=4, depth_test=True)


def get_icons_dir():
    return Path(os.path.dirname(__file__)) / "icons"
