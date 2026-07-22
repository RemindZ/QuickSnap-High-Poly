import bpy, mathutils, logging
from mathutils import Vector
from enum import Enum
import math
from bpy_extras import view3d_utils
import numpy as np

__name_addon__ = '.'.join(__name__.split('.')[:-1])
logger = logging.getLogger(__name_addon__)


class State(Enum):
    IDLE = 1
    SOURCE_PICKED = 2
    DESTINATION_PICKED = 3


def transform_worldspace_viewspace(world_space_coord, perspective_matrix):
    return perspective_matrix @ Vector((world_space_coord[0], world_space_coord[1], world_space_coord[2], 1.0))


def transform_viewspace_coord2d(view_space_coord, width_half, height_half):
    return Vector((width_half + width_half * (view_space_coord.x / view_space_coord.w),
                   height_half + height_half * (view_space_coord.y / view_space_coord.w),
                   ))


def transform_worldspace_coord2d(world_space_coord, region, region3d):
    return transform_viewspace_coord2d(transform_worldspace_viewspace(world_space_coord, region3d.perspective_matrix),
                                       region.width / 2.0, region.height / 2.0)


def get_selection_objects(context):
    if 'EDIT' in context.mode:
        return [obj for obj in context.selected_objects if obj.visible_get()]
    else:
        return [obj for obj in context.selected_objects if obj.visible_get()]


def get_scene_objects(exclude_selection=False):
    if exclude_selection:
        objects = [obj.name for obj in bpy.data.objects if
                   obj not in bpy.context.selected_objects and obj.visible_get()]
    else:
        objects = [obj.name for obj in bpy.data.objects if
                   obj.visible_get()]
    return objects


def include_children(objects, recursive_call=False):
    """
    Inputs a list of objects, outputs that list + children objects
    """

    result = []
    if type(objects) is list or type(objects) is set:
        if not recursive_call:
            objects = keep_only_parents(objects)
        for obj in objects:
            result.extend(include_children(obj, recursive_call=True))
    else:
        obj = objects
        result.append(obj)
        for child in obj.children:
            result.extend(include_children(child, recursive_call=True))
    return result


def keep_only_parents(objects):
    """
    Inputs a list of objects, outputs that list minus all children of objects in that list
    """
    objects = set(objects)
    return set([obj for obj in objects if not has_parent(obj, objects)])


def has_parent(obj, parent_list):
    """
    Returns True of the object has a parent among a list of objects
    """
    parent = obj.parent
    if parent == None:
        return False
    if parent in parent_list:
        return True
    return has_parent(parent, parent_list)


def set_object_mode_if_needed():
    """
    Set context to object mode, returns the previous mode.
    """
    # logger.info("entering object mode if needed")
    if bpy.context.active_object is not None:
        mode = f'{bpy.context.active_object.mode}'
    else:
        mode = 'OBJECT'
    if mode != 'OBJECT':
        # logger.info('Going to Object Mode')
        bpy.ops.object.mode_set(mode='OBJECT')
    return mode


def revert_mode(previous_mode):
    if bpy.context.active_object is not None and bpy.context.active_object.mode != previous_mode:
        bpy.ops.object.mode_set(mode=previous_mode)


def translate_object_worldspace(obj, translation):
    obj.matrix_world = translation @ obj.matrix_world


def translate_vertices_worldspace(obj, bmesh, backup_vertices, translation):
    if hasattr(bmesh.verts, "ensure_lookup_table"):
        bmesh.verts.ensure_lookup_table()
    world_matrix = obj.matrix_world
    world_matrix_inverted = world_matrix.copy().inverted()
    for (index, co, _, _, _, _) in backup_vertices:
        bmesh.verts[index].co = world_matrix_inverted @ translation @ world_matrix @ co
    bmesh.to_mesh(obj.data)


def dump(obj):
    print(f"\n\n=============== Dump({obj}) ===============")
    for attr in dir(obj):
        if hasattr(obj, attr):
            print(f'{attr} : {getattr(obj, attr)}')
    print(f"=============== END Dump({obj}) ===============\n\n")


def get_addon_settings():
    addon = bpy.context.preferences.addons.get(__name_addon__)
    if addon:
        return addon.preferences
    return None


def get_object_vertex_count(obj, depsgraph=None):
    """
    Vertex count used to gate the heavy-mesh paths. With a depsgraph and modifiers, returns the
    evaluated (displayed) count so subsurf/multires sculpts gate the same way they are ingested.
    """
    if obj is None or obj.type != 'MESH':
        return 0
    if depsgraph is not None and len(obj.modifiers) > 0:
        try:
            return len(obj.evaluated_get(depsgraph).data.vertices)
        except (RuntimeError, AttributeError):
            pass
    return len(obj.data.vertices)


def is_heavy_object(obj, settings=None, depsgraph=None):
    """True if the object is above the (user-set) vertex threshold and should use the heavy paths."""
    if settings is None:
        settings = get_addon_settings()
    if settings is None or not getattr(settings, "optimize_heavy_meshes", True):
        return False
    # Match ingestion: count evaluated verts unless modifiers are ignored.
    if getattr(settings, "ignore_modifiers", False):
        depsgraph = None
    return get_object_vertex_count(obj, depsgraph) >= settings.heavy_mesh_threshold * 1000


_FIT_COS_5 = math.cos(math.radians(5.0))
_FIT_ABS_TOL = 1e-7


def _mesh_fit_data(obj):
    mesh = obj.data
    vertex_count = len(mesh.vertices)
    polygon_count = len(mesh.polygons)
    loop_count = len(mesh.loops)
    edge_count = len(mesh.edges)

    vertices = np.empty(vertex_count * 3, dtype=np.float64)
    mesh.vertices.foreach_get('co', vertices)
    vertices.shape = (vertex_count, 3)
    matrix = np.array(obj.matrix_world, dtype=np.float64)
    inverse = np.array(obj.matrix_world.inverted(), dtype=np.float64)
    vertices = vertices @ matrix[:3, :3].T + matrix[:3, 3]

    loop_vertices = np.empty(loop_count, dtype=np.int32)
    loop_edges = np.empty(loop_count, dtype=np.int32)
    mesh.loops.foreach_get('vertex_index', loop_vertices)
    mesh.loops.foreach_get('edge_index', loop_edges)

    loop_starts = np.empty(polygon_count, dtype=np.int32)
    loop_totals = np.empty(polygon_count, dtype=np.int32)
    centers = np.empty(polygon_count * 3, dtype=np.float64)
    normals = np.empty(polygon_count * 3, dtype=np.float64)
    mesh.polygons.foreach_get('loop_start', loop_starts)
    mesh.polygons.foreach_get('loop_total', loop_totals)
    mesh.polygons.foreach_get('center', centers)
    mesh.polygons.foreach_get('normal', normals)
    centers.shape = (polygon_count, 3)
    normals.shape = (polygon_count, 3)
    centers = centers @ matrix[:3, :3].T + matrix[:3, 3]
    normals = normals @ inverse[:3, :3]
    lengths = np.linalg.norm(normals, axis=1)
    lengths[lengths == 0] = 1.0
    normals /= lengths[:, None]

    edge_vertices = np.empty(edge_count * 2, dtype=np.int32)
    mesh.edges.foreach_get('vertices', edge_vertices)
    edge_vertices.shape = (edge_count, 2)
    edge_lengths = np.linalg.norm(vertices[edge_vertices[:, 0]] - vertices[edge_vertices[:, 1]], axis=1)

    loop_polygons = np.repeat(np.arange(polygon_count, dtype=np.int32), loop_totals)
    edge_order = np.argsort(loop_edges, kind='stable')
    edge_counts = np.bincount(loop_edges, minlength=edge_count)
    edge_starts = np.concatenate(([0], np.cumsum(edge_counts)))

    return {
        'mesh': mesh,
        'vertices': vertices,
        'loop_vertices': loop_vertices,
        'loop_edges': loop_edges,
        'loop_starts': loop_starts,
        'loop_totals': loop_totals,
        'loop_polygons': loop_polygons,
        'polygon_centers': centers,
        'polygon_normals': normals,
        'edge_lengths': edge_lengths,
        'edge_polygons': loop_polygons[edge_order],
        'edge_starts': edge_starts,
        'polygon_geometry': {},
        'polygon_patches': {},
    }


def _seed_polygons(mesh_data, snap_type, element_index):
    if element_index < 0:
        return []
    if snap_type == 'POINTS' and element_index < len(mesh_data['vertices']):
        mask = mesh_data['loop_vertices'] == element_index
        return np.unique(mesh_data['loop_polygons'][mask]).tolist()
    if snap_type == 'MIDPOINTS' and element_index < len(mesh_data['edge_lengths']):
        mask = mesh_data['loop_edges'] == element_index
        return np.unique(mesh_data['loop_polygons'][mask]).tolist()
    if snap_type == 'FACES' and element_index < len(mesh_data['loop_starts']):
        return [element_index]
    return []


def _polygon_geometry(mesh_data, polygon_index):
    cached = mesh_data['polygon_geometry'].get(polygon_index)
    if cached is not None:
        return cached
    start = int(mesh_data['loop_starts'][polygon_index])
    total = int(mesh_data['loop_totals'][polygon_index])
    vertex_indices = mesh_data['loop_vertices'][start:start + total]
    coordinates = mesh_data['vertices'][vertex_indices]
    if len(coordinates) < 3:
        area = 0.0
    else:
        triangles = np.cross(coordinates[1:-1] - coordinates[0], coordinates[2:] - coordinates[0])
        area = 0.5 * float(np.linalg.norm(triangles, axis=1).sum())
    cached = {
        'vertices': vertex_indices,
        'area': area,
        'center': mesh_data['polygon_centers'][polygon_index],
        'normal': mesh_data['polygon_normals'][polygon_index],
    }
    mesh_data['polygon_geometry'][polygon_index] = cached
    return cached


def _edge_neighbors(mesh_data, edge_index):
    start = int(mesh_data['edge_starts'][edge_index])
    end = int(mesh_data['edge_starts'][edge_index + 1])
    return mesh_data['edge_polygons'][start:end]


def _grow_planar_patch(mesh_data, seed_polygon, cos_planar=_FIT_COS_5):
    if seed_polygon in mesh_data['polygon_patches']:
        return mesh_data['polygon_patches'][seed_polygon]

    component = {int(seed_polygon)}
    queue = [int(seed_polygon)]
    while queue:
        polygon_index = queue.pop()
        start = int(mesh_data['loop_starts'][polygon_index])
        total = int(mesh_data['loop_totals'][polygon_index])
        normal = mesh_data['polygon_normals'][polygon_index]
        center = mesh_data['polygon_centers'][polygon_index]
        for edge_index in mesh_data['loop_edges'][start:start + total]:
            tolerance = max(0.005 * float(mesh_data['edge_lengths'][edge_index]), _FIT_ABS_TOL)
            for neighbor in _edge_neighbors(mesh_data, int(edge_index)):
                neighbor = int(neighbor)
                if neighbor in component:
                    continue
                neighbor_normal = mesh_data['polygon_normals'][neighbor]
                if float(normal @ neighbor_normal) < cos_planar:
                    continue
                neighbor_center = mesh_data['polygon_centers'][neighbor]
                if abs(float((neighbor_center - center) @ normal)) > tolerance:
                    continue
                if abs(float((center - neighbor_center) @ neighbor_normal)) > tolerance:
                    continue
                component.add(neighbor)
                queue.append(neighbor)

    polygon_indices = np.array(sorted(component), dtype=np.int32)
    geometry = [_polygon_geometry(mesh_data, int(index)) for index in polygon_indices]
    areas = np.array([item['area'] for item in geometry], dtype=np.float64)
    total_area = float(areas.sum())
    patch = None
    if total_area > 0:
        point = (mesh_data['polygon_centers'][polygon_indices] * areas[:, None]).sum(axis=0) / total_area
        normal = (mesh_data['polygon_normals'][polygon_indices] * areas[:, None]).sum(axis=0)
        normal_length = float(np.linalg.norm(normal))
        if normal_length > 0:
            normal /= normal_length
            vertex_indices = np.unique(np.concatenate([item['vertices'] for item in geometry]))
            coordinates = mesh_data['vertices'][vertex_indices]
            extent = float(np.linalg.norm(coordinates.max(axis=0) - coordinates.min(axis=0)))
            tolerance = max(0.005 * extent, _FIT_ABS_TOL)
            residual = float(np.max(np.abs((mesh_data['polygon_centers'][polygon_indices] - point) @ normal)))
            if extent > 0 and residual <= tolerance:
                boundary_edges = set()
                for polygon_index in polygon_indices:
                    start = int(mesh_data['loop_starts'][polygon_index])
                    total = int(mesh_data['loop_totals'][polygon_index])
                    for edge_index in mesh_data['loop_edges'][start:start + total]:
                        neighbors = _edge_neighbors(mesh_data, int(edge_index))
                        if any(int(neighbor) not in component for neighbor in neighbors):
                            boundary_edges.add(int(edge_index))
                patch = {
                    'id': tuple(int(index) for index in polygon_indices),
                    'polygons': component,
                    'boundary_edges': tuple(sorted(boundary_edges)),
                    'point': point,
                    'normal': normal,
                    'area': total_area,
                    'extent': extent,
                    'residual': residual,
                    'tolerance': tolerance,
                }

    for polygon_index in component:
        mesh_data['polygon_patches'][polygon_index] = patch
    return patch


def _patch_sort_key(patch):
    normal = patch['normal'].copy()
    dominant = int(np.argmax(np.abs(normal)))
    if normal[dominant] < 0:
        normal *= -1.0
    return tuple(np.round(normal, 9)) + (
        round(float(normal @ patch['point']), 9),
        round(float(patch['area']), 9),
    )


def _candidate_patches(mesh_data, seed_polygons):
    patches = {}
    frontier = []
    for polygon_index in seed_polygons:
        patch = _grow_planar_patch(mesh_data, int(polygon_index))
        if patch is not None and patch['id'] not in patches:
            patches[patch['id']] = patch
            frontier.append(patch)

    for _ in range(2):
        next_frontier = []
        for patch in frontier:
            for edge_index in patch['boundary_edges']:
                for polygon_index in _edge_neighbors(mesh_data, edge_index):
                    polygon_index = int(polygon_index)
                    if polygon_index in patch['polygons']:
                        continue
                    neighbor = _grow_planar_patch(mesh_data, polygon_index)
                    if neighbor is not None and neighbor['id'] not in patches:
                        patches[neighbor['id']] = neighbor
                        next_frontier.append(neighbor)
        frontier = next_frontier
    return sorted(patches.values(), key=_patch_sort_key)


def _plane_pairs(patches, contact):
    opposed_limit = math.cos(math.radians(170.0))
    pairs = []
    for i, first in enumerate(patches):
        for second in patches[i + 1:]:
            if float(first['normal'] @ second['normal']) > opposed_limit:
                continue
            axis = first['normal'] - second['normal']
            length = float(np.linalg.norm(axis))
            if length == 0:
                continue
            axis /= length
            dominant = int(np.argmax(np.abs(axis)))
            if axis[dominant] < 0:
                axis *= -1.0
            first_d = float(axis @ first['point'])
            second_d = float(axis @ second['point'])
            if first_d <= second_d:
                low, high = first, second
                low_d, high_d = first_d, second_d
            else:
                low, high = second, first
                low_d, high_d = second_d, first_d
            tolerance = first['tolerance'] + second['tolerance']
            separation = high_d - low_d
            contact_d = float(axis @ contact)
            if separation <= tolerance:
                continue
            if contact_d < low_d - tolerance or contact_d > high_d + tolerance:
                continue
            pairs.append({
                'axis': axis,
                'low_patch': low,
                'high_patch': high,
                'low': low_d,
                'high': high_d,
                'mid': 0.5 * (low_d + high_d),
                'center': 0.5 * (low['point'] + high['point']),
                'separation': separation,
                'tolerance': tolerance,
            })
    return sorted(pairs, key=lambda pair: tuple(np.round(pair['axis'], 9)) + (round(pair['mid'], 9),))


def _match_plane_pairs(source_pairs, target_pairs, contact):
    opposed_limit = math.cos(math.radians(170.0))
    matches = []
    for source in source_pairs:
        candidates = []
        for target in target_pairs:
            if float(source['axis'] @ target['axis']) < _FIT_COS_5:
                continue
            if float(source['low_patch']['normal'] @ target['low_patch']['normal']) > opposed_limit:
                continue
            if float(source['high_patch']['normal'] @ target['high_patch']['normal']) > opposed_limit:
                continue
            tolerance = source['tolerance'] + target['tolerance']
            clearance = target['separation'] - source['separation']
            if clearance <= tolerance:
                continue
            delta = target['mid'] - source['mid']
            if abs(delta) > min(0.25 * source['separation'], 2.0 * clearance) + tolerance:
                continue
            distance = float(np.linalg.norm(target['center'] - contact))
            candidates.append((distance, tolerance, target, clearance, delta))
        if not candidates:
            continue
        candidates.sort(key=lambda item: item[0])
        if len(candidates) > 1 and candidates[1][0] - candidates[0][0] <= candidates[0][1] + candidates[1][1]:
            continue
        _, tolerance, target, clearance, delta = candidates[0]
        matches.append({
            'axis': source['axis'],
            'source': source,
            'target': target,
            'clearance': clearance,
            'delta': delta,
            'tolerance': tolerance,
        })

    independent = []
    remaining = sorted(matches, key=lambda item: tuple(np.round(item['axis'], 9)))
    while remaining:
        match = remaining.pop(0)
        # Competing source slabs on one axis are ambiguous; never let polygon order choose one.
        same_axis = []
        next_remaining = []
        for other in remaining:
            if abs(float(match['axis'] @ other['axis'])) >= _FIT_COS_5:
                same_axis.append(other)
            else:
                next_remaining.append(other)
        remaining = next_remaining
        if not same_axis:
            independent.append(match)
    return independent


def _solve_pair_translation(matches):
    if not matches:
        return None
    axes = np.array([match['axis'] for match in matches], dtype=np.float64)
    deltas = np.array([match['delta'] for match in matches], dtype=np.float64)
    try:
        translation = np.linalg.lstsq(axes, deltas, rcond=0.1)[0]
        _, singular, vh = np.linalg.svd(axes, full_matrices=False)
    except np.linalg.LinAlgError:
        return None
    if len(singular) == 0 or singular[0] <= 0:
        return None
    basis = vh[singular >= 0.1 * singular[0]]
    if len(basis) == 0:
        return None
    translation = basis.T @ (basis @ translation)
    scale = max(match['target']['separation'] for match in matches)
    if not np.isfinite(translation).all() or float(np.linalg.norm(translation)) <= 1e-12 * scale:
        return None
    return translation


def _validate_pair_translation(matches, translation):
    for match in matches:
        source = match['source']
        target = match['target']
        shift = float(match['axis'] @ translation)
        low_before = source['low'] - target['low']
        high_before = target['high'] - source['high']
        low_after = source['low'] + shift - target['low']
        high_after = target['high'] - source['high'] - shift
        tolerance = match['tolerance']
        if low_after < -tolerance or high_after < -tolerance:
            return False
        if abs(low_after - high_after) >= abs(low_before - high_before):
            return False
        if abs(low_after - high_after) > tolerance:
            return False
    return True


def compute_precision_fit(context, settings,
                          source_object_name, source_snap_type, source_element_index,
                          target_object_name, target_snap_type, target_element_index,
                          contact_point):
    """Center clean opposed plane pairs seeded by the user's source and target snap elements."""
    source_obj = bpy.data.objects.get(source_object_name)
    target_obj = bpy.data.objects.get(target_object_name)
    if source_obj is None or target_obj is None or source_obj.type != 'MESH' or target_obj.type != 'MESH':
        logger.debug("Precision fit skipped: source or target mesh is unavailable")
        return None
    depsgraph = context.evaluated_depsgraph_get()
    ignore_modifiers = getattr(settings, 'ignore_modifiers', False)
    source_fit = source_obj if ignore_modifiers else source_obj.evaluated_get(depsgraph)
    target_fit = target_obj if ignore_modifiers else target_obj.evaluated_get(depsgraph)
    if len(source_fit.data.polygons) == 0 or len(target_fit.data.polygons) == 0:
        logger.debug("Precision fit skipped: source or target mesh is empty")
        return None

    contact = np.array(contact_point, dtype=np.float64)
    source_data = _mesh_fit_data(source_fit)
    target_data = _mesh_fit_data(target_fit)
    source_seeds = _seed_polygons(source_data, source_snap_type, source_element_index)
    target_seeds = _seed_polygons(target_data, target_snap_type, target_element_index)
    if not source_seeds or not target_seeds:
        logger.debug("Precision fit skipped: snap element is stale or unsupported")
        return None
    source_patches = _candidate_patches(source_data, source_seeds)
    target_patches = _candidate_patches(target_data, target_seeds)
    source_pairs = _plane_pairs(source_patches, contact)
    target_pairs = _plane_pairs(target_patches, contact)
    matches = _match_plane_pairs(source_pairs, target_pairs, contact)
    translation = _solve_pair_translation(matches)
    if translation is None:
        logger.debug("Precision fit skipped: no unambiguous clearance pair")
        return None
    if not _validate_pair_translation(matches, translation):
        logger.debug("Precision fit skipped: proposed translation failed pair validation")
        return None
    return Vector(tuple(float(value) for value in translation))


def get_axis_target(origin, target, axis_constraint, obj=None):
    """
    Returns the snapping target taking into account constrain options
    if obj is not None the constraint will be calculated in object space.
    """
    if len(axis_constraint) == 0:
        return target
    if obj is None:
        world_matrix = mathutils.Matrix.Identity(4)
    else:
        world_matrix = obj.matrix_world.to_quaternion()

    # Axis constraint
    if len(axis_constraint) == 1:
        if axis_constraint == 'X':
            point2 = origin + world_matrix @ Vector((1, 0, 0))
        elif axis_constraint == 'Y':
            point2 = origin + world_matrix @ Vector((0, 1, 0))
        else:
            point2 = origin + world_matrix @ Vector((0, 0, 1))
        return mathutils.geometry.intersect_point_line(target, origin, point2)[0]

    # Planar constraint
    if len(axis_constraint) == 2:
        if axis_constraint == 'XY':
            point2 = origin + world_matrix @ Vector((1, 0, 0))
            point3 = origin + world_matrix @ Vector((0, 1, 0))
        elif axis_constraint == 'YZ':
            point2 = origin + world_matrix @ Vector((0, 1, 0))
            point3 = origin + world_matrix @ Vector((0, 0, 1))
        else:
            point2 = origin + world_matrix @ Vector((1, 0, 0))
            point3 = origin + world_matrix @ Vector((0, 0, 1))

        normal = mathutils.geometry.normal(origin, point2, point3)
        if not normal.dot(origin - target) > 0:  # flip normal if it is pointing the wrong direction
            normal = -1 * normal
        new_target = mathutils.geometry.intersect_ray_tri(origin, point2, point3, normal, target, False)
        return new_target


def get_target_free(origin, camera_position, camera_vector, snapping, obj=None, is_ortho=False):
    """
    Get the target position if there is no target point, taking constraint into consideration.
    If obj is not None the constraint will be calculated in object space.
    """
    camera_point_b = camera_position + camera_vector

    # If no constraint target will be the intersection between the mouse ray and the plane perpendicular to camera
    # at origin position
    if len(snapping) == 0:
        return mathutils.geometry.intersect_line_plane(camera_position, camera_point_b, origin, camera_vector * -1)
    if obj is None:
        world_matrix = mathutils.Matrix.Identity(4)
    else:
        world_matrix = obj.matrix_world.to_quaternion()

    # Axis constraint
    if len(snapping) == 1:
        if snapping == 'X':
            offset_vector = Vector((1, 0, 0))
        elif snapping == 'Y':
            offset_vector = Vector((0, 1, 0))
        else:
            offset_vector = Vector((0, 0, 1))

        if abs(camera_vector.normalized().dot(offset_vector)) == 1:
            return origin

        point2 = origin + world_matrix @ offset_vector
        result = mathutils.geometry.intersect_line_line(camera_position, camera_point_b, origin, point2)
        if result is None:
            return origin
        return result[1]

    # Planar constraint
    if len(snapping) == 2:
        if snapping == 'XY':
            axis_vector = Vector((0, 0, 1))
            point2 = origin + world_matrix @ Vector((1000, 0, 0))
            point3 = origin + world_matrix @ Vector((0, 1000, 0))
        elif snapping == 'YZ':
            axis_vector = Vector((1, 0, 0))
            point2 = origin + world_matrix @ Vector((0, 1000, 0))
            point3 = origin + world_matrix @ Vector((0, 0, 1000))
        else:
            axis_vector = Vector((0, 1, 0))
            point2 = origin + world_matrix @ Vector((1000, 0, 0))
            point3 = origin + world_matrix @ Vector((0, 0, 1000))

        if is_ortho and camera_vector.normalized().dot(axis_vector) != 1:
            return origin

        normal = mathutils.geometry.normal(origin, point2, point3)
        new_target = mathutils.geometry.intersect_line_plane(camera_position, camera_point_b, origin, normal, False)
        if new_target is None:
            return origin
        return new_target


def display_keymap(kmi, layout):
    """
    Display keymap in UILayout
    """
    layout.emboss = 'NORMAL'
    if kmi is None:
        return
    map_type = kmi.map_type

    row = layout.row()
    row.prop(kmi, "active", text="", emboss=False)
    row.alignment = 'EXPAND'
    label_container = row.row().row()
    label_container.alignment = 'LEFT'
    label_container.emboss = 'NONE'
    label_container.enabled = False
    label_container.operator(kmi.idname, text=kmi.name)

    split = row.split()
    row = split.row()
    row.alignment = 'RIGHT'
    insert_prop_with_width(kmi, "map_type", row, text="", size=5)
    if map_type == 'KEYBOARD':
        insert_prop_with_width(kmi, "type", row, text="", size=8, full_event=True)
    elif map_type == 'MOUSE':
        insert_prop_with_width(kmi, "type", row, text="", size=8, full_event=True)
    elif map_type == 'NDOF':
        insert_prop_with_width(kmi, "type", row, text="", size=8, full_event=True)
    elif map_type == 'TWEAK':
        subrow = row.row()
        insert_prop_with_width(kmi, "type", subrow, text="", size=4)
        insert_prop_with_width(kmi, "value", subrow, text="", size=4)
    elif map_type == 'TIMER':
        insert_prop_with_width(kmi, "type", row, text="", size=8)
    else:
        insert_prop_with_width(kmi, "type", row, text="", size=8)


def insert_prop_with_width(property_object, property_name, layout, align='CENTER', text=None, icon='NONE',
                           expand=False, slider=False, icon_only=False, toggle=False, size=5, enabled=True,
                           full_event=False):
    """
    Insert UILayout prop with a fixed width
    """
    ui_container = layout.row()
    ui_container.alignment = align
    ui_container.ui_units_x = size
    if not enabled:
        ui_container.enabled = False
    ui_container.prop(property_object, property_name, icon=icon, toggle=toggle, text=text, expand=expand, slider=slider,
                      icon_only=icon_only, full_event=full_event)


icons_list = bpy.types.UILayout.bl_rna.functions[
            "prop"].parameters["icon"].enum_items.keys()


def insert_ui_hotkey(container, key, description, control=False, shift=False, alt=False):
    """
    Insert UI hotkey information: KeyMap icons + description
    """
    line = container.row(align=True)
    container_description = line.split(factor=0.39)
    row = container_description.row(align=True)
    row.alignment = 'RIGHT'


    if alt:
        row.label(text="", icon="EVENT_ALT")
    if control:
        row.label(text="", icon="EVENT_CTRL")
    if shift:
        row.label(text="", icon="EVENT_SHIFT")

    if key == "EVENT_RIGHTMOUSE":
        key = "MOUSE_RMB"
    elif key == "EVENT_LEFTMOUSE":
        key = "MOUSE_LMB"
    elif key == "EVENT_MIDDLEMOUSE":
        key = "MOUSE_MMB"
        
    if key in icons_list:
        row.label(text="", icon=key)
    else:
        row.label(text=f"[{key.replace('EVENT_','')}]")
    container_description.label(text=description)


def flatten(nested_list):
    """
    Flattens nested lists
    """
    return [item for sublist in nested_list for item in sublist]


def translate_curvepoints_worldspace(obj, backup_data, translation):
    """
    Apply translation to curve points
    """
    curve_data = obj.data
    for (curve_index, index, co, bezier, left, right) in backup_data:
        if bezier:
            curve_data.splines[curve_index].bezier_points[index].co = translation @ co.copy()
            curve_data.splines[curve_index].bezier_points[index].handle_left = translation @ left.copy()
            curve_data.splines[curve_index].bezier_points[index].handle_right = translation @ right.copy()
        else:
            original_point = Vector((co[0], co[1], co[2]))
            target_position = translation @ original_point
            curve_data.splines[curve_index].points[index].co = (target_position[0],
                                                                target_position[1],
                                                                target_position[2],
                                                                0)
    pass


def has_points_selected(selected_meshes):
    """
    Returns True if any point of the selected meshes is selected.
    """

    for obj_name in selected_meshes:
        obj = bpy.data.objects[obj_name]
        data = obj.data
        if obj.type == 'MESH':
            if data.total_vert_sel>0:
                return True
        elif obj.type == 'CURVE':
            for spline in data.splines:
                for point in spline.bezier_points:
                    if point.select_control_point:
                        return True
                for point in spline.points:
                    if point.select:
                        return True
    return False


mouse_pointer_offsets = [
    Vector((-40, -40)),
    Vector((-40, 0)),
    Vector((-40, 40)),
    Vector((0, 40)),
    Vector((40, 40)),
    Vector((40, 0)),
    Vector((40, -40)),
    Vector((0, -40))
]


def check_close_objects(context, region, depsgraph, mouse_position):
    """
    Cast 8 rays around the mouse, returns the hit objects.
    """
    mouse_position = Vector(mouse_position)
    points = [mouse_position]
    points.extend([mouse_position + point for point in mouse_pointer_offsets])
    hit_objects = []
    # logger.info(f"check_close_objects: {points}")
    for point in points:
        if region.data.view_perspective == 'CAMERA' and not region.data.is_perspective:
            depth_location = context.space_data.camera.location
            view_position = view3d_utils.region_2d_to_location_3d(region, region.data, point,
                                                                  depth_location)
        else:
            view_position = view3d_utils.region_2d_to_origin_3d(region, region.data, point)
        # view_position = view3d_utils.region_2d_to_origin_3d(region, context.space_data.region_3d, point)
        mouse_vector = view3d_utils.region_2d_to_vector_3d(region, context.space_data.region_3d, point)
        (hit, _, _, _, obj, *_) = context.scene.ray_cast(depsgraph, origin=view_position,
                                                         direction=mouse_vector)
        if hit:
            hit_objects.append(obj)
    # logger.info(f"hit_objects: {hit_objects}")
    return hit_objects


def set_select_all_points(object_names, selected=False):
    for obj_name in object_names:
        obj = bpy.data.objects[obj_name]
        if obj.type == 'MESH':
            bpy.ops.object.mode_set(mode='OBJECT')
            obj.data.polygons.foreach_set('select', np.full(len(obj.data.polygons), selected))
            obj.data.edges.foreach_set('select', np.full(len(obj.data.edges), selected))
            obj.data.vertices.foreach_set('select', np.full(len(obj.data.vertices), selected))
            bpy.ops.object.mode_set(mode='EDIT')
            pass
        elif obj.type == 'CURVE':
            for spline in obj.data.splines:
                spline.points.foreach_set('select', np.full(len(spline.points), selected))
                spline.bezier_points.foreach_set('select_control_point', np.full(len(spline.bezier_points), selected))
            pass



