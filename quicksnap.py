import time
import bmesh
import bpy
import json
import logging
import numpy as np
import os
from mathutils import Vector

from . import quicksnap_render
from . import quicksnap_utils
from .quicksnap_snapdata import SnapData
from bpy_extras import view3d_utils
from .quicksnap_utils import State
from . import addon_updater_ops

__name_addon__ = '.'.join(__name__.split('.')[:-1])
logger = logging.getLogger(__name_addon__)
addon_keymaps = []



class QuickVertexSnapOperator(bpy.types.Operator):
    bl_idname = "object.quicksnap"
    bl_label = "QuickSnap Tool"
    bl_options = { 'REGISTER', 'UNDO'}
    bl_description = "Quickly snap selection from/to a selected vertex, curve point, object origin, edge midpoint, face" \
                     " center.\nUse the same keymap to open the tool PIE menu."

    def initialize(self, context):
        self.icons = {}
        addon_updater_ops.check_for_update_background()
        # Get 'WINDOW' region of the context. Useful when the active context region is UI within the 3DView
        region = None
        for region_item in context.area.regions:
            if region_item.type == 'WINDOW':
                region = region_item

        if not region:
            return False  # If no window region, cancel the operation.

        #set log level
        if self.settings.log_level == 0:
            logger.setLevel(logging.NOTSET)
        elif self.settings.log_level == 1:
            logger.setLevel(logging.INFO)
            logger.info("QuickSnap: Setting logger level to: INFO")
            self.report({'INFO'},
                        f"QuickSnap: Setting logger level to: INFO. Use Ctrl+Shift+TAB to change debug level.")
        if self.settings.log_level == 2:
            logger.setLevel(logging.DEBUG)
            logger.debug("QuickSnap: Setting logger level to: DEBUG")
            self.report({'INFO'},
                        f"QuickSnap: Setting logger level to: DEBUG. Use Ctrl+Shift+TAB to change debug level.")

        #icons time
        self.icon_display_time = time.time()

        # Get selection, if false cancel operation
        self.selection_objects = [obj.name for obj in quicksnap_utils.get_selection_objects(context)]
        self.no_selection = False
        if not self.selection_objects or len(self.selection_objects) == 0:
            self.no_selection = True

        self.object_mode = context.active_object is None or context.active_object.mode == 'OBJECT'
        if not self.object_mode and not quicksnap_utils.has_points_selected(self.selection_objects):
            self.no_selection = True

        # Hide objects to ignore if we are in local view.
        if context.space_data.local_view is not None:
            all_scene_objects = [obj for obj in context.view_layer.objects if not obj.hide_get()]
            ignored_objs = set([obj for obj in all_scene_objects if obj not in context.visible_objects])
            self.ignored_obj_names = set([obj.name for obj in ignored_objs])
            for obj in ignored_objs:
                obj.hide_set(True)

        # Create SnapData objects that will store all the vertex/point info (World space, view space, and kdtree to
        # search the closest point)
        self.snapdata_source = SnapData(context, region, self.settings, self.selection_objects,
                                        quicksnap_utils.get_scene_objects(False),
                                        is_origin=True,
                                        no_selection=self.no_selection)
        if self.no_selection:
            self.snapdata_target = SnapData(context, region, self.settings, [],
                                            [])
        else:
            self.snapdata_target = SnapData(context, region, self.settings, self.selection_objects,
                                            quicksnap_utils.get_scene_objects(True))

        # Store 3DView camera information.
        region3d = context.space_data.region_3d
        self.camera_position = region3d.view_matrix.inverted().translation
        self.mouse_vector = view3d_utils.region_2d_to_vector_3d(region, context.space_data.region_3d,
                                                                self.mouse_position)
        self.perspective_matrix = context.space_data.region_3d.perspective_matrix
        self.perspective_matrix_inverse = self.perspective_matrix.inverted()
        self.target_bounds = {}
        self.target_npdata = {}
        self.local_wire_objects = set()
        self.local_wire_data = {}
        self._heavy_cache = {}
        self._corner_cache = {}
        self.perf_wire_ms = 0.0
        self.selection_hidden = False
        self.snap_paused = False
        self.no_selection_target = None
        self.ignore_modifiers = self.settings.ignore_modifiers
        self.source_object = ""
        self.source_element_index = -1
        self.source_snap_type = ""
        self.target_face_index = -1
        self.target_object_display_backup = {}
        self.source_highlight_data = {}
        self.target_highlight_data = {}
        self.source_allowed_indices = {}
        self.target_allowed_indices = {}
        self.source_npdata = {}
        self.backup_data(context)
        self.update(context, region)
        self.clickdrag = True
        self.last_event = None
        self.clicktime = 0
        context.area.header_text_set(f"QuickSnap: Pick a vertex/point from the selection to start move-snapping")
        self.detect_hotkey()
        return True

    def backup_data(self, context):
        """
        Backup points positions if in Object mode, otherwise backup object positions. used for cancelling operator
        """
        self.backup_object_positions = {}
        if self.object_mode:
            selection = quicksnap_utils.keep_only_parents(
                [bpy.data.objects[obj_name] for obj_name in self.selection_objects])
            for obj in selection:
                self.backup_object_positions[obj.name] = obj.matrix_world.copy()
        else:
            self.backup_curve_points = {}
            self.bmeshs = {}
            for object_name in self.snapdata_source.selected_ids:
                obj = bpy.data.objects[object_name]
                if obj.type == "MESH":
                    self.bmeshs[object_name] = bmesh.new()
                    self.bmeshs[object_name].from_mesh(obj.data)

                elif obj.type == "CURVE":
                    self.backup_curve_points[object_name] = quicksnap_utils.flatten([[
                        (spline_index, index, point.co.copy(), 1, point.handle_left.copy(), point.handle_right.copy())
                        for index, point in enumerate(spline.bezier_points) if point.select_control_point]
                        for spline_index, spline in enumerate(obj.data.splines)])

                    self.backup_curve_points[object_name].extend(quicksnap_utils.flatten([[(
                        spline_index, index, point.co.copy(), 0, 0, 0)
                        for index, point in enumerate(spline.points) if point.select]
                        for spline_index, spline in enumerate(obj.data.splines)]))

    def store_object_display(self, object_name):
        if object_name not in self.target_object_display_backup:
            self.target_object_display_backup[object_name] = (bpy.data.objects[object_name].show_wire,
                                                              bpy.data.objects[object_name].show_name,
                                                              bpy.data.objects[object_name].show_bounds,
                                                              bpy.data.objects[object_name].display_bounds_type)

    def revert_object_display(self, object_name):
        # Clear the local-wire flag alongside the native display revert.
        self.local_wire_objects.discard(object_name)
        if object_name in self.target_object_display_backup:
            (bpy.data.objects[object_name].show_wire,
             bpy.data.objects[object_name].show_name,
             bpy.data.objects[object_name].show_bounds,
             bpy.data.objects[object_name].display_bounds_type) = self.target_object_display_backup[object_name]

    def set_object_display(self, target_object="", hover_object="", is_root=False, mesh_vertid=-1, force=True):
        """
        Defines the target object.
        Enables wireframe/bounds/display name on the target object and disable all that on the previous target object
        """
        if self.target_object != "":
            self.revert_object_display(self.target_object)
        if self.hover_object != "":
            self.revert_object_display(self.hover_object)

        if target_object != "":
            self.store_object_display(target_object)
            if self.settings.display_target_wireframe:
                self._apply_wireframe_display(target_object)
            if is_root:
                bpy.data.objects[target_object].show_name = True

        self.target_object = target_object
        self.target_object_is_root = is_root

        if hover_object != "" and hover_object != target_object:
            self.store_object_display(hover_object)
            if self.settings.display_target_wireframe:
                self._apply_wireframe_display(hover_object)

        self.hover_object = hover_object
        self.closest_vertexid = mesh_vertid

    def _apply_wireframe_display(self, object_name):
        """
        Show the target/hover wireframe. Style is user-selectable; in automatic mode heavy meshes
        skip the native show_wire (too slow) and use the cursor-local wireframe instead. The heavy
        check evaluates modifiers, so memoize it per object instead of paying it every mouse move.
        """
        style = self.settings.wireframe_style
        if style == 'LOCAL' and bpy.data.objects[object_name].type == 'MESH':
            self.local_wire_objects.add(object_name)
            quicksnap_render.ensure_wire_static(self, bpy.context, object_name)
            return
        if style == 'NATIVE':
            bpy.data.objects[object_name].show_wire = True
            return
        heavy = self._heavy_cache.get(object_name)
        if heavy is None:
            depsgraph = bpy.context.evaluated_depsgraph_get()
            heavy = quicksnap_utils.is_heavy_object(bpy.data.objects[object_name], self.settings, depsgraph)
            self._heavy_cache[object_name] = heavy
        if heavy:
            self.local_wire_objects.add(object_name)
            # Build the wire data now (modal side) rather than inside the draw handler.
            quicksnap_render.ensure_wire_static(self, bpy.context, object_name)
        else:
            bpy.data.objects[object_name].show_wire = True

    def corner_score_candidates(self, snapdata, object_ids, mesh_indices, spline_ids):
        """
        Corner-likeness in [0,1] for each snap candidate, used to bias vertex picking towards
        feature corners. A vertex's incident edge directions cancel out on flat areas and along
        straight edges, but all point into the solid at a corner, so the length of their mean is
        a cheap, topology-exact cornerness measure. Uses the wireframe adjacency cache; memoized
        per (object, vertex) since the same candidates recur across mouse moves.
        """
        boost = np.zeros(len(object_ids), dtype=np.float64)
        try:
            self._fill_corner_boost(snapdata, object_ids, mesh_indices, spline_ids, boost)
        except Exception as error:
            # Corner bias is a non-essential enhancement; never let it break the snap query.
            logger.debug(f"corner scoring skipped: {error}")
        return boost

    def _fill_corner_boost(self, snapdata, object_ids, mesh_indices, spline_ids, boost):
        for i in range(len(object_ids)):
            oid = int(object_ids[i])
            vid = int(mesh_indices[i])
            if vid < 0 or int(spline_ids[i]) >= 0 or oid < 0 or oid >= len(snapdata.scene_meshes):
                continue
            key = (snapdata.scene_meshes[oid], vid)
            cached = self._corner_cache.get(key)
            if cached is None:
                cached = 0.0
                cache = quicksnap_render.ensure_wire_static(self, bpy.context, key[0])
                if cache is not None and vid < len(cache["adj_off"]) - 1:
                    lo = int(cache["adj_off"][vid])
                    hi = int(cache["adj_off"][vid + 1])
                    if hi - lo >= 2:
                        pair = cache["edge_verts"][cache["adj_edge"][lo:hi]]
                        others = np.where(pair[:, 0] == vid, pair[:, 1], pair[:, 0])
                        dirs = cache["vert_world"][others].astype(np.float64) - cache["vert_world"][vid]
                        lengths = np.linalg.norm(dirs, axis=1)
                        valid = lengths > 0
                        if valid.sum() >= 2:
                            dirs = dirs[valid] / lengths[valid][:, None]
                            resultant = float(np.linalg.norm(dirs.mean(axis=0)))
                            cached = min(resultant / 0.5, 1.0)  # saturate: a box corner is ~0.58
                self._corner_cache[key] = cached
            boost[i] = cached
        return boost

    def get_corner_score_fn(self, snapdata):
        """The corner bias callback for find_closest, or None when the feature is off."""
        if not self.settings.corner_snapping:
            return None
        return lambda object_ids, mesh_indices, spline_ids: \
            self.corner_score_candidates(snapdata, object_ids, mesh_indices, spline_ids)

    def set_selection_hidden(self, hidden):
        """
        Hide/show the objects being moved (stage 2 clarity feature). Hiding drops the selection,
        so unhiding re-selects. While hidden the live translate is skipped by Blender, which is
        fine: the position only matters when visible, and every unhide is followed by an apply.
        """
        if not self.object_mode or self.selection_hidden == hidden:
            return
        for object_name in self.selection_objects:
            obj = bpy.data.objects.get(object_name)
            if obj is None:
                continue
            obj.hide_set(hidden)
            if not hidden:
                obj.select_set(True)
        self.selection_hidden = hidden

    def run_precision_fit(self, context):
        """
        Optional post-snap refinement (object mode): nudge the selection so the geometry around the
        snapped point seats onto the target surface. Translation only, runs once on confirm.
        Skipped with axis constraints (it would break them) and origin/cursor/free-space targets.
        """
        if not getattr(self.settings, "precision_fit", False):
            return
        if not self.object_mode or len(self.snapping) > 0:
            return
        if self.closest_target_id < 0 or self.target is None or self.target_object == "":
            return
        if self.closest_target_id in self.snapdata_target.origins_map:
            return
        if self.source_snap_type not in {'POINTS', 'MIDPOINTS', 'FACES'}:
            return
        if self.snapdata_target.snap_type not in {'POINTS', 'MIDPOINTS', 'FACES'}:
            return
        try:
            fit = quicksnap_utils.compute_precision_fit(
                context, self.settings,
                self.source_object, self.source_snap_type, self.source_element_index,
                self.target_object, self.snapdata_target.snap_type, self.closest_vertexid,
                self.target)
        except Exception as error:
            logger.warning(f"Precision fit skipped: {error}")
            return
        if fit is None:
            return
        if self.last_translation is not None:
            self.last_translation = self.last_translation + fit
        bpy.ops.transform.translate(value=fit, orient_type='GLOBAL', snap=False,
                                    use_automerge_and_split=False)
        logger.info(f"Precision fit: corrected by {fit.length:.6f}")
        self.report({'INFO'}, f"QuickSnap precision fit: {fit.length:.4f}")

    def revert_data(self, context, apply=False):
        """
        Revert the backed up data (verts/curve points positions if in EDIT mode, objects locations if in OBJECT mode)
        """
        if self.object_mode:
            for object_name in self.backup_object_positions:
                bpy.data.objects[object_name].matrix_world = self.backup_object_positions[object_name].copy()
        else:
            # If the operation is not cancelled, simply move the selection back.
            if not apply and self.last_translation is not None:
                bpy.ops.transform.translate(value=self.last_translation * -1,
                                            orient_type='GLOBAL',
                                            snap=False,
                                            use_automerge_and_split=False)
                return
            # Otherwise, properly revert all vertex/points data.
            object_mode_backup = quicksnap_utils.set_object_mode_if_needed()
            for object_name in self.bmeshs:
                obj = bpy.data.objects[object_name]
                self.bmeshs[object_name].to_mesh(bpy.data.objects[object_name].data)

            for object_name in self.backup_curve_points:
                obj = bpy.data.objects[object_name]
                data = obj.data
                for (curveindex, index, co, bezier, left, right) in self.backup_curve_points[object_name]:
                    if bezier == 1:
                        data.splines[curveindex].bezier_points[index].co = co
                        data.splines[curveindex].bezier_points[index].handle_left = left
                        data.splines[curveindex].bezier_points[index].handle_right = right
                    else:
                        data.splines[curveindex].points[index].co = co

            quicksnap_utils.revert_mode(object_mode_backup)

    def update(self, context, region):
        """
        Main Update Loop
        """

        # Update 3DView camera information
        region3d = context.region_data
        self.camera_position = region3d.view_matrix.inverted().translation
        if region3d.view_perspective == 'CAMERA' and not region3d.is_perspective:
            depth_location = context.space_data.camera.location
            self.mouse_position_world = view3d_utils.region_2d_to_location_3d(region, region.data, self.mouse_position,
                                                                              depth_location)
        else:
            self.mouse_position_world = view3d_utils.region_2d_to_origin_3d(region, region.data, self.mouse_position)
        self.mouse_vector = view3d_utils.region_2d_to_vector_3d(region, region.data,
                                                                self.mouse_position)

        mouse_coord_screen_flat = Vector((self.mouse_position[0], self.mouse_position[1], 0))

        depsgraph = context.evaluated_depsgraph_get()
        hover_object = ""
        if self.current_state == State.IDLE:
            if self.snapdata_source.snap_type != 'ORIGINS':
                if self.no_selection and self.object_mode:
                    selection = []

                    self.snapdata_source.add_nearby_objects(context, region, depsgraph, self.mouse_position, selection)
                # Find object under the mouse
                (direct_hit, _, _, self.target_face_index, direct_hit_object, _) = context.scene.ray_cast(
                    context.evaluated_depsgraph_get(),
                    origin=self.mouse_position_world,
                    direction=self.mouse_vector)
                # If found, we push this object on top of the stack of objects to process
                if direct_hit and (direct_hit_object.name in self.selection_objects or (self.no_selection and self.object_mode)):
                    hover_object = direct_hit_object.name
                    self.snapdata_source.add_object_data(direct_hit_object.name,
                                                         depsgraph=depsgraph,
                                                         is_selected=True,
                                                         set_first_priority=True)

            # Find source vert/point the closest to the mouse, change cursor crosshair
            closest = self.snapdata_source.find_closest(mouse_coord_screen_flat,
                                                        search_origins_only=self.snapdata_source.snap_type == 'ORIGINS',
                                                        corner_score_fn=self.get_corner_score_fn(self.snapdata_source))
            if closest is not None:
                (self.closest_source_id, self.distance, target_name, is_root, mesh_vertid) = closest
                self.source_object = target_name
                self.source_element_index = mesh_vertid
                self.source_snap_type = self.snapdata_source.snap_type
                self.set_object_display(target_name, hover_object, is_root)
                if self.object_mode and self.no_selection and self.no_selection_target is None or \
                        self.no_selection_target != target_name:
                    self.no_selection_target = target_name
                self.closest_actionable = True  # Points too far from the mouse are highlighted but can't be moved
                bpy.context.window.cursor_set("SCROLL_XY")
            else:
                if self.object_mode and self.no_selection and self.no_selection_target is not None:
                    self.no_selection_target = None
                self.closest_source_id = -1
                self.closest_vertexid = -1
                self.set_object_display("", hover_object)
                self.distance = -1
                self.closest_actionable = False
                bpy.context.window.cursor_set("CROSSHAIR")

        elif self.current_state == State.SOURCE_PICKED:
            if self.snap_paused:
                # Shift held: no raycast, no loading, no closest-point search. The selection
                # free-follows the mouse so the user can look around and position cheaply.
                self.closest_target_id = -1
                self.closest_vertexid = -1
                self.distance = -1
                if self.target_object != "" or self.hover_object != "":
                    self.set_object_display("", "")
            # If we are only snapping to origins, only search through origin points.
            elif self.snapdata_target.snap_type == 'ORIGINS':
                closest = self.snapdata_target.find_closest(mouse_coord_screen_flat, search_origins_only=True)
                if closest is not None:
                    (self.closest_target_id, self.distance, target_object_name, is_root, mesh_vertid) = closest
                    self.set_object_display(target_object_name, hover_object, is_root, mesh_vertid=mesh_vertid)
                else:
                    self.closest_vertexid = -1
                    self.closest_target_id = -1
                    self.distance = -1
                    self.set_object_display("", hover_object)

            else:  # Snapping to all verts/points
                # First hide the selection mesh not to raycast against it.
                selected_objs = [bpy.data.objects[obj] for obj in self.selection_objects]
                for obj in selected_objs:
                    obj.hide_set(True)

                (direct_hit, direct_hit_object_name, self.target_face_index) = \
                    self.snapdata_target.add_nearby_objects(context, region, depsgraph, self.mouse_position,
                                                            self.selection_objects)

                if direct_hit:
                    hover_object = direct_hit_object_name

                # Revert hidden objects
                for obj in self.selection_objects:
                    bpy.data.objects[obj].hide_set(False)
                for obj in self.selection_objects:  # re-select selection that might be lost in previous steps
                    bpy.data.objects[obj].select_set(True)
                self.selection_hidden = False  # the raycast dance above just unhid everything

                # Find the closest target points
                closest = self.snapdata_target.find_closest(
                    mouse_coord_screen_flat, corner_score_fn=self.get_corner_score_fn(self.snapdata_target))
                if closest is not None:
                    (self.closest_target_id, self.distance, target_object_name, is_root, mesh_vertid) = closest
                    self.set_object_display(target_object_name, hover_object, is_root, mesh_vertid=mesh_vertid)
                else:
                    self.closest_vertexid = -1
                    self.closest_target_id = -1
                    self.distance = -1
                    self.set_object_display("", hover_object)

            # Hide the moving objects while the mouse is over another object or while snapping is
            # paused (Shift), so the target geometry is unobstructed; they reappear as soon as the
            # mouse leaves the target / Shift is released.
            if self.settings.hide_selection_over_target:
                self.set_selection_hidden(hover_object != "" or self.snap_paused)


    def apply(self, context, region, use_auto_merge=False):
        """
        Apply operator modifications: Translate objects or vertices/points from source point to target point.
        """
        self.target = None
        self.target2d = None
        if self.current_state == State.SOURCE_PICKED:
            self.revert_data(context)  # We first revert objects/verts/points to their original position

            origin = self.snapdata_source.world_space[self.closest_source_id]

            # If there is a target vert/point, use it and apply axis constraint if needed.
            if self.closest_target_id >= 0:
                self.target = self.snapdata_target.world_space[self.closest_target_id]
                if len(self.snapping) == 0 or not self.snapping_local:
                    self.target = quicksnap_utils.get_axis_target(origin, self.target, self.snapping)
                else:
                    self.target = quicksnap_utils.get_axis_target(origin,
                                                                  self.snapdata_target.world_space[
                                                                      self.closest_target_id],
                                                                  self.snapping,
                                                                  bpy.data.objects[self.selection_objects[0]])
            # If there is no target, get the target on the place perpendicular to the camera,
            # or closest to constrained axis.
            else:
                is_ortho = context.space_data.region_3d.view_perspective == 'ORTHO'
                # The 3D location in this direction
                if len(self.snapping) == 0 or not self.snapping_local:
                    self.target = quicksnap_utils.get_target_free(origin, self.mouse_position_world, self.mouse_vector,
                                                                  self.snapping, is_ortho=is_ortho)
                else:
                    self.target = quicksnap_utils.get_target_free(origin, self.mouse_position_world, self.mouse_vector,
                                                                  self.snapping,
                                                                  bpy.data.objects[self.selection_objects[0]],
                                                                  is_ortho=is_ortho)

            self.last_translation = (Vector(self.target) - Vector(origin))
            tool_settings = context.tool_settings
            use_auto_merge = use_auto_merge and not self.object_mode and tool_settings.use_mesh_automerge
            bpy.ops.transform.translate(value=self.last_translation,
                                        orient_type='GLOBAL',
                                        snap=False,
                                        use_automerge_and_split=use_auto_merge)

            # Get the 2D position of the target for ui rendering
            self.target2d = quicksnap_utils.transform_worldspace_coord2d(self.target, region,
                                                                         context.space_data.region_3d)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.icons = None
        self.icon_display_time = 0
        self.view_distance = None
        self.view_camera_zoom = None
        self.no_selection = False
        self.no_selection_target = None
        self.mouse_position_world = None
        self.ignored_obj_names = set()
        self.clicktime = 0
        self.last_event = None
        self.clickdrag = None
        self.ignore_modifiers = None
        self.target_face_index = -1
        self.hotkey_type = 'V'
        self.hotkey_alt = False
        self.hotkey_ctrl = True
        self.hotkey_shift = True
        self.menu_open = False
        self.hover_object = ""
        self.local_wire_objects = set()
        self.local_wire_data = {}
        self._heavy_cache = {}
        self._corner_cache = {}
        self.perf_wire_ms = 0.0
        self.selection_hidden = False
        self.snap_paused = False
        self.source_object = ""
        self.source_element_index = -1
        self.source_snap_type = ""
        self.target_bounds = None
        self.source_highlight_data = None
        self.source_allowed_indices = None
        self.target_highlight_data = None
        self.target_allowed_indices = None
        self.source_npdata = None
        self.target_npdata = None
        self.backup_curve_points = None
        self.last_translation = None
        self.translate_ops = None
        self._timer = None
        self._handle_3d = None
        self._handle = None
        self.mouse_position = None
        self.bmeshs = None
        self.backup_vertices = {}
        self.backup_object_positions = {}
        self.perspective_matrix_inverse = None
        self.perspective_matrix = None
        self.camera_position = None
        self.mouse_vector = None
        self.closest_target_object = ""
        self.snapdata_target = None
        self.snapdata_source = None
        self.object_mode = None
        self.target_object_display_backup = None
        self.target_object_show_bounds_backup = False
        self.target_object_display_bounds_type_backup = False
        self.target_object_show_name_backup = False
        self.target_object_show_wire_backup = False
        self.target_object_is_root = False
        self.target_object = ""
        self.camera_moved = False
        self.target2d = None
        self.target = None
        self.distance = 0
        self.closest_actionable = False
        self.closest_target_id = -1
        self.closest_source_id = -1
        self.closest_vertexid = -1
        self.current_state = State.IDLE
        self.selection_objects = None
        self.settings = get_addon_settings()
        self.snapping_local = False
        self.snapping = ""

    def __del__(self):
        pass

    def refresh_vertex_data(self, context, region):
        """
        Re-Init the snapdata if the view camera moved. (Updates 2d positions of all points)
        Projection only depends on the view, so on a mouse-move-only frame this bails out and
        nothing gets re-projected. Orbit/pan/zoom change the matrix below and trigger a rebuild.
        """
        region3d = context.space_data.region_3d
        if self.camera_position == region3d.view_matrix.inverted().translation \
                and self.perspective_matrix == region3d.perspective_matrix \
                and self.view_distance == region3d.view_distance \
                and self.view_camera_zoom == region3d.view_camera_zoom:
            return
        logger.info("refresh data")
        self.camera_position = region3d.view_matrix.inverted().translation
        self.view_distance = region3d.view_distance
        self.view_camera_zoom = region3d.view_camera_zoom
        self.perspective_matrix = context.space_data.region_3d.perspective_matrix
        self.perspective_matrix_inverse = self.perspective_matrix.inverted()
        self.init_snap_data(context, region, self.current_state == State.IDLE, True)

    def modal(self, context, event):

        # Get 'WINDOW' region of the current context, useful when the context region is a child UI region of the window
        region = None
        for area_region in context.area.regions:
            if area_region.type == 'WINDOW':
                region = area_region

        if event.type not in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE',
                                                                   'TIMER'}:
            self.refresh_vertex_data(context, region)
            # Holding Shift after the source pick pauses target evaluation: the selection follows
            # the mouse freely and nothing under the cursor gets loaded or searched.
            self.snap_paused = event.shift and self.current_state == State.SOURCE_PICKED
        snapdata_updated = False
        if self.current_state == State.IDLE:
            ti = time.perf_counter()
            snapdata_updated = snapdata_updated or self.snapdata_source.process_iteration(context)
            self.snapdata_source.processing_time_total += time.perf_counter() - ti
            if not self.snapdata_source.keep_processing:  # if all source are processed, start processing target points
                ti = time.perf_counter()
                snapdata_updated = snapdata_updated or self.snapdata_target.process_iteration(context)
                self.snapdata_target.processing_time_total += time.perf_counter() - ti
        elif not self.snap_paused:
            ti = time.perf_counter()
            snapdata_updated = snapdata_updated or self.snapdata_target.process_iteration(context)
            self.snapdata_target.processing_time_total += time.perf_counter() - ti
        context.area.tag_redraw()

        self.handle_hotkeys(context, event, region)

        if event.type in {'RIGHTMOUSE', 'ESC'} and not self.menu_open and event.value == 'PRESS':  # Cancel
            self.terminate(context, revert=True)
            return {'CANCELLED'}

        elif event.type == 'LEFTMOUSE' and not self.menu_open:  # Confirm
            if event.value == 'PRESS':
                self.clicktime = time.time()
            elif self.last_event == event.type or time.time()-self.clicktime <= 0.10:
                # Detect single clicks: either if mouse press was last event or if press was less than 0.1s ago
                self.clickdrag = False

            if self.current_state == State.IDLE and self.closest_source_id >= 0 and self.closest_actionable:
                if self.no_selection:
                    obj_name = self.snapdata_source.get_object_name_at_index(self.closest_source_id)
                    if self.object_mode:
                        self.snapdata_source.keep_processing = False
                        if obj_name is not None:
                            self.selection_objects.append(obj_name)
                            bpy.data.objects[obj_name].select_set(True)
                            context.view_layer.objects.active = bpy.data.objects[obj_name]
                            self.revert_object_display(obj_name)
                        else:
                            print("Error: Could not find target object.")
                            self.terminate(context)
                            return {'FINISHED'}
                    else:
                        obj = bpy.data.objects[obj_name]
                        if self.closest_source_id in self.snapdata_source.origins_map and \
                                self.snapdata_source.origins_map[self.closest_source_id] == obj_name:
                            bpy.ops.object.mode_set(mode='OBJECT')
                            self.selection_objects.append(obj_name)
                            if obj_name in self.snapdata_target.to_process_scene:
                                self.snapdata_target.to_process_scene.remove(obj_name)
                            self.revert_object_display(obj_name)
                        else:
                            self.snapdata_source.select_points(obj, self.closest_source_id)

                    self.backup_data(context)
                    self.snapdata_target.is_enabled = False
                    self.snapdata_target.__init__(context, region, self.settings, self.selection_objects,
                                                  quicksnap_utils.get_scene_objects(True))
                self.current_state = State.SOURCE_PICKED
                self.icon_display_time = time.time()
                self.set_object_display("", "")
                self.update_header(context)
            elif event.value == 'PRESS' or self.clickdrag:  # Disable the tool on mouse release if click dragging.
                # Unhide before the final apply: translate skips hidden objects.
                self.set_selection_hidden(False)
                # Last translation for applying auto-merge
                self.apply(context, region, use_auto_merge=self.settings.use_auto_merge)
                self.run_precision_fit(context)
                self.terminate(context)
                return {'FINISHED'}

        elif event.type == 'MOUSEMOVE' or snapdata_updated:  # Apply
            if self.menu_open:
                self.handle_pie_menu_closed(context, event, region)
                self.menu_open = False
            self.update_mouse_position(context, event)
            self.update(context, region)
            self.apply(context, region)
            self.update_header(context)

        if event.type != 'TIMER':
            self.last_event = event.type

        # Allow navigation
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            self.update_mouse_position(context, event)
            if event.type == 'MIDDLEMOUSE' and self.current_state == State.SOURCE_PICKED:
                # Orbiting: pause snapping and keep the dragged objects out of the view. The next
                # mouse move after the orbit re-evaluates and unhides as usual.
                self.snap_paused = True
                if self.settings.hide_selection_over_target:
                    self.set_selection_hidden(True)
            return {'PASS_THROUGH'}

        return {'RUNNING_MODAL'}

    def handle_hotkeys(self, context, event, region):
        """
        Toggle axis constraint and origin snapping.
        """
        if event.is_repeat or event.value != 'PRESS':
            return
        event_type = event.type
        logger.debug(f"Input key: {event_type}")
        if not self.menu_open and event_type == self.hotkey_type and event.shift == self.hotkey_shift \
                and event.ctrl == self.hotkey_ctrl and event.alt == self.hotkey_alt and self.current_state == State.IDLE:
            self.menu_open = True
            logger.info(f"Pie menu called.")
            bpy.ops.wm.call_menu_pie(name="VIEW3D_MT_PIE_quicksnap")
        elif event_type == 'ONE' or event_type == 'NUMPAD_1':
            self.icon_display_time = time.time()
            if self.current_state == State.IDLE:
                if self.settings.snap_source_type != 'POINTS':
                    self.settings.snap_source_type = 'POINTS'
                    self.handle_pie_menu_closed(context, event, region)
            elif self.current_state == State.SOURCE_PICKED:
                if self.settings.snap_target_type != 'POINTS':
                    self.settings.snap_target_type = 'POINTS'
                    self.handle_pie_menu_closed(context, event, region)
        elif event_type == 'TWO' or event_type == 'NUMPAD_2':
            self.icon_display_time = time.time()
            if self.current_state == State.IDLE:
                if self.settings.snap_source_type != 'MIDPOINTS':
                    self.settings.snap_source_type = 'MIDPOINTS'
                    self.handle_pie_menu_closed(context, event, region)
            elif self.current_state == State.SOURCE_PICKED:
                if self.settings.snap_target_type != 'MIDPOINTS':
                    self.settings.snap_target_type = 'MIDPOINTS'
                    self.handle_pie_menu_closed(context, event, region)
        elif event_type == 'THREE' or event_type == 'NUMPAD_3':
            self.icon_display_time = time.time()
            if self.current_state == State.IDLE:
                if self.settings.snap_source_type != 'FACES':
                    self.settings.snap_source_type = 'FACES'
                    self.handle_pie_menu_closed(context, event, region)
            elif self.current_state == State.SOURCE_PICKED:
                if self.settings.snap_target_type != 'FACES':
                    self.settings.snap_target_type = 'FACES'
                    self.handle_pie_menu_closed(context, event, region)
        elif event_type == 'O':
            self.icon_display_time = time.time()
            if self.current_state == State.IDLE:
                if self.settings.snap_source_type != 'ORIGINS':
                    self.settings.snap_source_type = 'ORIGINS'
                    self.handle_pie_menu_closed(context, event, region)
            elif self.current_state == State.SOURCE_PICKED:
                if self.settings.snap_target_type != 'ORIGINS':
                    self.settings.snap_target_type = 'ORIGINS'
                    self.handle_pie_menu_closed(context, event, region)

        elif event_type == 'X':
            if event.shift:
                new_snapping = 'YZ'
            else:
                new_snapping = 'X'
            if self.snapping == new_snapping:
                if not self.snapping_local and len(self.selection_objects) == 1:
                    self.snapping_local = not self.snapping_local
                else:
                    self.snapping_local = False
                    self.snapping = ""
            else:
                self.snapping = new_snapping
            self.update(context, region)
            self.apply(context, region)
        elif event_type == 'Y':
            if event.shift:
                new_snapping = 'XZ'
            else:
                new_snapping = 'Y'
            if self.snapping == new_snapping:
                if not self.snapping_local and len(self.selection_objects) == 1:
                    self.snapping_local = not self.snapping_local
                else:
                    self.snapping_local = False
                    self.snapping = ""
            else:
                self.snapping = new_snapping
            self.update(context, region)
            self.apply(context, region)
        elif event_type == 'Z':
            if event.shift:
                new_snapping = 'XY'
            else:
                new_snapping = 'Z'
            if self.snapping == new_snapping:
                if not self.snapping_local and len(self.selection_objects) == 1:
                    self.snapping_local = not self.snapping_local
                else:
                    self.snapping_local = False
                    self.snapping = ""
            else:
                self.snapping = new_snapping
            self.update(context, region)
            self.apply(context, region)

        elif event_type == 'W':
            self.settings.display_target_wireframe = not self.settings.display_target_wireframe
            self.set_object_display(self.target_object, self.hover_object, self.target_object_is_root, force=True)
        elif event_type == 'M':
            self.settings.ignore_modifiers = not self.settings.ignore_modifiers

            self.refresh_vertex_data(context, region)
            self.set_object_display(self.target_object, self.hover_object, self.target_object_is_root, force=True)
        elif event_type == 'TAB' and event.shift and event.ctrl:
            loglevel = logger.level
            if loglevel == logging.NOTSET:
                self.settings.log_level = 1
                logger.setLevel(logging.INFO)
                logger.info("QuickSnap: Setting logger level to: INFO.")
                logger.info("Use Ctrl+Shift+TAB when QuickSnap is enabled to change debug level.")
                self.report({'INFO'},
                            f"QuickSnap: Setting logger level to: INFO.\nUse Ctrl+Shift+TAB when QuickSnap is enabled to change debug level.")
            elif loglevel == logging.INFO:
                self.settings.log_level = 2
                logger.setLevel(logging.DEBUG)
                logger.debug("QuickSnap: Setting logger level to: DEBUG.")
                logger.debug("Use Ctrl+Shift+TAB when QuickSnap is enabled to change debug level.")
                self.report({'INFO'},
                            f"QuickSnap: Setting logger level to: DEBUG.\nUse Ctrl+Shift+TAB when QuickSnap is enabled to change debug level.")
            if loglevel == logging.DEBUG:
                self.settings.log_level = 0
                logger.setLevel(logging.NOTSET)
                self.report({'INFO'}, f"QuickSnap: Disabling debug.")
                self.report({'INFO'}, f"Use Ctrl+Shift+TAB when QuickSnap is enabled to change debug level.")
                print("QuickSnap: Disabling debug. Use Ctrl+Shift+TAB when QuickSnap is enabled to change debug level.")
        self.update_header(context)

    def terminate(self, context, revert=False):
        """
        End modal operator, reset header, etc
        """
        # logger.info("terminate")
        self.set_selection_hidden(False)
        if revert:
            self.revert_data(context, apply=True)

        if context.space_data.local_view is not None:
            for obj_name in self.ignored_obj_names:
                bpy.data.objects[obj_name].hide_set(False)
        self.set_object_display("", "")
        context.area.header_text_set(None)
        if self.object_mode:
            if context.active_object is not None:
                bpy.ops.object.mode_set(mode='OBJECT')
            bpy.context.window.cursor_set("DEFAULT")
        else:
            if context.active_object is not None:
                bpy.ops.object.mode_set(mode='EDIT')
            bpy.context.window.cursor_set("CROSSHAIR")
        quicksnap_render.remove_draw_handlers()
        self.snapdata_target.is_enabled = False
        context.window_manager.event_timer_remove(self._timer)

        # Revert mode and selection
        if self.object_mode:
            if context.active_object is None:
                context.view_layer.objects.active = context.selected_objects[0]
            bpy.ops.object.mode_set(mode='OBJECT')

        if self.no_selection:
            if self.object_mode:
                for selected_object in self.selection_objects:
                    bpy.data.objects[selected_object].select_set(False)
            else:
                quicksnap_utils.set_select_all_points(self.selection_objects)
                pass
        else:
            for selected_object in self.selection_objects:
                bpy.data.objects[selected_object].select_set(True)

        if self.target_npdata is not None and len(self.target_npdata) > 0:
            for bm in self.target_npdata:
                self.target_npdata[bm] = None
            self.target_npdata = {}
        # Release the wire cache arrays (can be hundreds of MB for very dense meshes).
        self.local_wire_data = {}
        self._heavy_cache = {}
        self._corner_cache = {}
        try:
            save_settings()  # keep the settings backup fresh even if Blender never unregisters
        except Exception:
            pass

    def update_mouse_position(self, context, event):
        self.mouse_position = (event.mouse_region_x, event.mouse_region_y)

    def update_header(self, context):
        ignore_modifiers_msg = ""
        axis_msg = ""
        snapping_msg = f"Use (Shift+)X/Y/Z to constraint to the world/local axis or plane. Use O to snap to object " \
                       f"origins. 1,2,3 to snap to verts, edge midpoints, face centers. Right Mouse Button/ESC to cancel the operation. "

        if len(self.snapping) > 0:
            if len(self.snapping) == 1:
                snapping_msg = f"{snapping_msg}Constrained on {self.snapping} axis"
            if len(self.snapping) == 2:
                snapping_msg = f"{snapping_msg}Constrained on {self.snapping} plane"
            if self.snapping_local:
                axis_msg = "(Local)"
            else:
                axis_msg = "(World)"
        if self.settings.ignore_modifiers:
            ignore_modifiers_msg = " [MODIFIERS ARE IGNORED]"
        if self.snap_paused:
            ignore_modifiers_msg = f"{ignore_modifiers_msg} [SNAPPING PAUSED (Shift held)]"
        if self.current_state == State.IDLE:
            context.area.header_text_set(f"QuickSnap: Pick the source vertex/point. {snapping_msg}{axis_msg} "
                                         f"{ignore_modifiers_msg}")
        elif self.current_state == State.SOURCE_PICKED:
            context.area.header_text_set(
                f"QuickSnap: Move the mouse over the target vertex/point. {snapping_msg}{axis_msg} "
                f"{ignore_modifiers_msg}")

    def invoke(self, context, event):
        if context.area is None:
            return {'CANCELLED'}
        if context.area.type != 'VIEW_3D':
            self.report({'WARNING'}, "View3D not found, cannot run operator")
            return {'CANCELLED'}

        self.update_mouse_position(context, event)
        if not self.initialize(context):
            return {'CANCELLED'}

        context.window.cursor_modal_set("DEFAULT")

        # Registered via the render module, which tracks the handles so an orphaned handler (if the
        # operator is ever freed without terminate) can always be removed.
        quicksnap_render.add_draw_handlers(self, context)
        self._handle = None
        self._handle_3d = None
        self._timer = context.window_manager.event_timer_add(0.005, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def handle_pie_menu_closed(self, context, event, region):
        if self.ignore_modifiers != self.settings.ignore_modifiers:
            # Evaluated/raw mesh choice changed: wire caches and heavy gating are stale.
            self.local_wire_data = {}
            self._heavy_cache = {}
            self._corner_cache = {}
        if self.settings.snap_source_type != self.snapdata_source.snap_type or \
                self.ignore_modifiers != self.settings.ignore_modifiers:
            self.init_snap_data(context, region, True, False)
            if self.current_state == State.IDLE:
                self.icon_display_time = time.time()
        if self.settings.snap_target_type != self.snapdata_target.snap_type or \
                self.ignore_modifiers != self.settings.ignore_modifiers:
            self.init_snap_data(context, region, False, True)
            if self.current_state == State.SOURCE_PICKED:
                self.icon_display_time = time.time()
        self.ignore_modifiers = self.settings.ignore_modifiers
        self.update(context,region)
        pass

    def init_snap_data(self, context, region, revert_source, revert_target):
        # The local-wire cache stays: its static part (world coords/edges) is view-independent and
        # its screen part re-projects itself when the view matrix no longer matches.
        if revert_source:
            self.snapdata_source.__init__(context, region, self.settings, self.selection_objects,
                                          quicksnap_utils.get_scene_objects(False), is_origin=True,
                                          no_selection=self.no_selection)

            self.closest_actionable = False
            self.closest_source_id = -1

            self.source_highlight_data = {}
            self.source_allowed_indices = {}
            self.source_npdata = {}
        if revert_target:
            self.snapdata_target.is_enabled = False
            self.snapdata_target.__init__(context, region, self.settings, self.selection_objects,
                                          quicksnap_utils.get_scene_objects(True))
        self.target_highlight_data = {}
        self.target_allowed_indices = {}
        self.target_bounds = {}
        self.target_npdata = {}
        self.target_face_index = -1
        self.closest_target_id = -1
        self.closest_vertexid = -1

    def detect_hotkey(self):
        logger.info(
            f"Detecting current hotkey")

        key_config = bpy.context.window_manager.keyconfigs.addon
        categories = set([cat for (cat, key) in addon_keymaps])
        id_names = [key.idname for (cat, key) in addon_keymaps]
        for cat in categories:
            active_cat = key_config.keymaps.find(cat.name, space_type=cat.space_type,
                                                 region_type=cat.region_type).active()
            for active_key in active_cat.keymap_items:
                if active_key.idname in id_names:
                    self.hotkey_type = active_key.type
                    self.hotkey_ctrl = active_key.ctrl
                    self.hotkey_shift = active_key.shift
                    self.hotkey_alt = active_key.alt
                    logger.info(f"Tool hotkey stored: Ctrl:{self.hotkey_ctrl} - Shift:{self.hotkey_shift} - Alt:{self.hotkey_alt} - Key:{self.hotkey_type}")
        pass


def get_addon_settings():
    addon = bpy.context.preferences.addons.get(__name_addon__)
    if addon:
        return addon.preferences
    return None


class QuickVertexSnapPreference(bpy.types.AddonPreferences):
    bl_idname = __name_addon__

    draw_rubberband: bpy.props.BoolProperty(name="Draw Rubber Band", default=True)
    use_auto_merge: bpy.props.BoolProperty(
        name="Use vertices Auto-Merge in Edit mode",
        description="With this option enabled, QuickSnap will use the Auto-Merge toggle visible in the top right corner"
                    " of the viewport and automatically merge vertices if it is enabled.",
        default=True)
    snap_objects_origin: bpy.props.EnumProperty(
        name="Snap from/to objects origins",
        items=[
            ("ALWAYS", "Always ON", "", 0),
            ("KEY", "Only in 'Snap to origins' mode (\"O\" key)", "", 1)
        ],
        default="ALWAYS", )
    display_target_wireframe: bpy.props.BoolProperty(name="Display target object wireframe", default=True)
    wireframe_style: bpy.props.EnumProperty(
        name="Wireframe style",
        description="How the target/hover object wireframe is drawn",
        items=[
            ("AUTO", "Automatic (by vertex threshold)",
             "Native full wireframe for light meshes, cursor-local wireframe for heavy ones", 0),
            ("LOCAL", "Cursor-local always",
             "Always draw only the edges around the cursor, regardless of mesh size", 1),
            ("NATIVE", "Native full wireframe always",
             "Always use Blender's full object wireframe overlay", 2),
        ],
        default="AUTO")
    hide_selection_over_target: bpy.props.BoolProperty(
        name="Hide dragged objects over the target",
        description="While picking the snap destination, hide the objects being moved whenever the"
                    " mouse is over another object so the target geometry is unobstructed. They"
                    " reappear when the mouse moves off the target and on confirm/cancel."
                    " Object mode only",
        default=True)
    corner_snapping: bpy.props.BoolProperty(
        name="Prefer corners (vertex snapping)",
        description="When snapping to vertices, favor corner vertices (where the mesh edges point"
                    " into the surface, like the corners of a peg or socket) over vertices on flat"
                    " areas near the cursor. Makes grabbing the corners of mating features easier",
        default=True)
    highlight_target_vertex_edges: bpy.props.BoolProperty(name="Enable highlighting of target vertex edges*",
                                                          default=True)
    edge_highlight_width: bpy.props.IntProperty(name="Highlight Width", default=2, min=1, max=10)
    selection_square_size: bpy.props.IntProperty(name="Selection Square Size", default=7, min=5, max=15)
    edge_highlight_color_source: bpy.props.FloatVectorProperty(
        name="Highlight Color (Selected object)",
        subtype='COLOR',
        default=(1.0, 1.0, 0.0),
        min=0.0, max=1.0
    )
    edge_highlight_color_target: bpy.props.FloatVectorProperty(
        name="Highlight Color (Target object)",
        subtype='COLOR',
        default=(1.0, 1.0, 0.0),
        min=0.0, max=1.0
    )
    edge_highlight_opacity: bpy.props.FloatProperty(name="Highlight Opacity", default=1, min=0, max=1)
    display_potential_target_points: bpy.props.BoolProperty(name="Display near edge midpoints/face centers*"
                                                            , default=True)
    ignore_modifiers: bpy.props.BoolProperty(name="Ignore modifiers (For heavy scenes)", default=False)

    # High-poly settings. Gate the heavy-mesh paths; meshes below the threshold are unchanged.
    optimize_heavy_meshes: bpy.props.BoolProperty(
        name="Optimize high-poly meshes",
        description="Enable the high-poly optimization paths for objects above the vertex threshold:"
                    " a cursor-local wireframe instead of the native full-object overlay, and a"
                    " localized point query instead of building a KDTree over millions of points",
        default=True)
    heavy_mesh_threshold: bpy.props.IntProperty(
        name="High-poly vertex threshold (x1000)",
        description="Objects with at least this many thousand vertices use the optimized high-poly"
                    " paths. Meshes below this count keep the original behavior. Example: 500 = 500,000"
                    " vertices",
        default=500, min=1, soft_max=20000, step=10)
    local_wireframe_radius: bpy.props.IntProperty(
        name="Cursor wireframe radius (px)",
        description="Pixel radius around the cursor for the high-poly cursor-local wireframe."
                    " A bit larger than the snap radius so the wire reads as context",
        default=60, min=10, max=400)
    local_wireframe_color: bpy.props.FloatVectorProperty(
        name="Cursor wireframe color",
        subtype='COLOR',
        default=(1.0, 1.0, 1.0),
        min=0.0, max=1.0)
    local_wireframe_opacity: bpy.props.FloatProperty(
        name="Cursor wireframe opacity", default=0.9, min=0.0, max=1.0)
    local_wireframe_xray: bpy.props.BoolProperty(
        name="Wireframe through geometry (x-ray)",
        description="Draw the cursor wireframe through the mesh. Off (default) shows only the edges"
                    " on the surface you are looking at; on also shows edges on the far side",
        default=False)

    # Post-snap precision fit (object mode).
    precision_fit: bpy.props.BoolProperty(
        name="Post-snap precision fit (object mode)",
        description="After snapping, nudge the selection (translation only, no rotation) so the"
                    " geometry around the snapped point seats onto the target surface. Useful for"
                    " pegs/holes whose vertices do not correspond exactly. Skipped when an axis"
                    " constraint is active",
        default=True)
    precision_fit_samples: bpy.props.IntProperty(
        name="Fit samples",
        description="How many vertices around the snapped point are matched against the target"
                    " surface when fitting",
        default=300, min=50, max=2000)

    snap_source_type: bpy.props.EnumProperty(
        name="Snap From",
        items=[
            ("POINTS", "Vertices, Curve points", "", 0),
            ("MIDPOINTS", "Edges mid-points", "", 1),
            ("FACES", "Face centers", "", 2),
            ("ORIGINS", "Objects origins", "", 3)
        ],
        default="POINTS", )

    snap_target_type: bpy.props.EnumProperty(
        name="Snap To",
        items=[
            ("POINTS", "Vertices, Curve points", "", 0),
            ("MIDPOINTS", "Edges mid-points", "", 1),
            ("FACES", "Face centers", "", 2),
            ("ORIGINS", "Objects origins", "", 3)
        ],
        default="POINTS", )

    snap_target_type_icon: bpy.props.EnumProperty(
        name="Display Snap Target Icons",
        items=[
            ("ALWAYS", "Always", "", 0),
            ("FADE", "Fade after 2 seconds", "", 1),
            ("NEVER", "Never", "", 2)
        ],
        default="FADE", )

    # addon updater preferences from `__init__`, be sure to copy all of them
    auto_check_update: bpy.props.BoolProperty(
        name="Auto-check for Update",
        description="If enabled, auto-check for updates using an interval",
        default=True,
    )

    updater_interval_months: bpy.props.IntProperty(
        name='Months',
        description="Number of months between checking for updates",
        default=0,
        min=0
    )
    updater_interval_days: bpy.props.IntProperty(
        name='Days',
        description="Number of days between checking for updates",
        default=7,
        min=0,
    )
    updater_interval_hours: bpy.props.IntProperty(
        name='Hours',
        description="Number of hours between checking for updates",
        default=0,
        min=0,
        max=23
    )
    updater_interval_minutes: bpy.props.IntProperty(
        name='Minutes',
        description="Number of minutes between checking for updates",
        default=0,
        min=0,
        max=59
    )
    # log level
    log_level: bpy.props.IntProperty(
        name='Log Level',
        default=0
    )

    def draw(self, context=None):
        layout = self.layout
        col = layout.column(align=True)
        col.use_property_split = True
        col.prop(self, "ignore_modifiers")
        col.prop(self, "use_auto_merge")
        heavy_box = col.box().column()
        heavy_box.label(text="High-poly performance:")
        heavy_box.prop(self, "optimize_heavy_meshes")
        if self.optimize_heavy_meshes:
            heavy_box.prop(self, "heavy_mesh_threshold")
            heavy_box.prop(self, "local_wireframe_radius")
            heavy_box.prop(self, "local_wireframe_color")
            heavy_box.prop(self, "local_wireframe_opacity")
            heavy_box.prop(self, "local_wireframe_xray")
        fit_box = col.box().column()
        fit_box.label(text="Precision fit:")
        fit_box.prop(self, "precision_fit")
        if self.precision_fit:
            fit_box.prop(self, "precision_fit_samples")
        col.prop(self, "snap_objects_origin")
        col.prop(self, "draw_rubberband")
        col.prop(self, "hide_selection_over_target")
        col.prop(self, "corner_snapping")
        col.prop(self, "display_target_wireframe")
        if self.display_target_wireframe:
            col.prop(self, "wireframe_style")
        col.prop(self, "display_potential_target_points")
        col.prop(self, "selection_square_size")
        col.separator()
        col.prop(self, "snap_target_type_icon")
        col.separator()
        container = col.box().column()
        container.label(text="Selection/Target Highlight*:")
        container.prop(self, "highlight_target_vertex_edges")
        if self.highlight_target_vertex_edges:
            container.prop(self, "edge_highlight_width")
            container.prop(self, "edge_highlight_opacity")
            container.prop(self, "edge_highlight_color_source")
            container.prop(self, "edge_highlight_color_target")

        col.label(text="*Can noticeably impact performances")
        box_content = layout.box()
        header = box_content.row(align=True)
        header.label(text="Keymap", icon='EVENT_A')
        col = box_content.column(align=True)
        col.use_property_split = False
        global addon_keymaps
        key_config = bpy.context.window_manager.keyconfigs.addon
        categories = set([cat for (cat, key) in addon_keymaps])
        id_names = [key.idname for (cat, key) in addon_keymaps]
        quicksnap_keymap = None
        for cat in categories:
            active_cat = key_config.keymaps.find(cat.name, space_type=cat.space_type,
                                                 region_type=cat.region_type).active()
            for active_key in active_cat.keymap_items:
                if active_key.idname in id_names:
                    quicksnap_keymap = active_key
                    quicksnap_utils.display_keymap(active_key, col)
        col.separator()
        col.label(text="QuickSnap hotkeys:")
        if quicksnap_keymap is not None:
            quicksnap_utils.insert_ui_hotkey(col, f'EVENT_{quicksnap_keymap.type}',
                                             "Open PIE menu (Same keymap as the QuickSnap Tool)",
                                             shift=quicksnap_keymap.shift,
                                             control=quicksnap_keymap.ctrl,
                                             alt=quicksnap_keymap.alt,
                                             )

        quicksnap_utils.insert_ui_hotkey(col, 'EVENT_X', "Constraint to X Axis")
        quicksnap_utils.insert_ui_hotkey(col, 'EVENT_X', "Constraint to X Plane", shift=True)
        quicksnap_utils.insert_ui_hotkey(col, 'EVENT_Y', "Constraint to Y Axis")
        quicksnap_utils.insert_ui_hotkey(col, 'EVENT_Y', "Constraint to Y Plane", shift=True)
        quicksnap_utils.insert_ui_hotkey(col, 'EVENT_Z', "Constraint to Z Axis")
        quicksnap_utils.insert_ui_hotkey(col, 'EVENT_Z', "Constraint to Z Plane", shift=True)
        quicksnap_utils.insert_ui_hotkey(col, 'EVENT_1', "Snap from/to vertices and curve points")
        quicksnap_utils.insert_ui_hotkey(col, 'EVENT_2', "Snap from/to edge mid-points")
        quicksnap_utils.insert_ui_hotkey(col, 'EVENT_3', "Snap from/to face centers")
        quicksnap_utils.insert_ui_hotkey(col, 'EVENT_O', "Snap from/to object origins")
        quicksnap_utils.insert_ui_hotkey(col, 'EVENT_W', "Enable/Disable wireframe on target object")
        quicksnap_utils.insert_ui_hotkey(col, 'EVENT_M', "Enable/Disable 'Ignore Modifiers'")
        quicksnap_utils.insert_ui_hotkey(col, 'EVENT_ESC', "Cancel Snap")
        quicksnap_utils.insert_ui_hotkey(col, 'MOUSE_RMB', "Cancel Snap")

        addon_updater_ops.update_settings_ui(self, context)



class VIEW3D_MT_PIE_quicksnap(bpy.types.Menu):
    # label is displayed at the center of the pie menu.
    bl_label = "QuickSnap_Pie"

    def draw(self, context):
        layout = self.layout
        settings = get_addon_settings()

        pie = layout.menu_pie()
        source_column = pie.column()
        source_column.label(text="Snap From:")
        source_column.prop(settings, "snap_source_type", expand=True)

        # operator_enum will just spread all available options
        # for the type enum of the operator on the pie
        target_column = pie.column()
        target_column.label(text="Snap To:")
        target_column.prop(settings, "snap_target_type", expand=True)
        pie.operator("quicksnap.open_settings")
        pie.prop(settings, "ignore_modifiers")


class QUICKSNAP_OT_OpenSettings(bpy.types.Operator):
    bl_idname = "quicksnap.open_settings"
    bl_label = "Open Addon Settings"
    bl_options = {'REGISTER', 'INTERNAL'}

    def execute(self, context):
        bpy.ops.screen.userpref_show()
        bpy.context.preferences.active_section = 'ADDONS'
        bpy.data.window_managers["WinMan"].addon_search = "QuickSnap"
        bpy.data.window_managers["WinMan"].addon_filter = 'All'
        return {"FINISHED"}


class QUICKSNAP_PT_toolbar(bpy.types.Panel):
    """Quick access to the per-session workflow toggles, in the 3D view sidebar (N panel)."""
    bl_label = "QuickSnap"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "QuickSnap"

    def draw(self, context):
        settings = get_addon_settings()
        if settings is None:
            return
        col = self.layout.column()
        col.prop(settings, "precision_fit", text="Post-snap precision fit")
        col.prop(settings, "corner_snapping", text="Prefer corners")
        col.prop(settings, "hide_selection_over_target", text="Hide dragged over target")


blender_classes = [
    QuickVertexSnapOperator,
    QuickVertexSnapPreference,
    QUICKSNAP_OT_OpenSettings,
    QUICKSNAP_PT_toolbar,
    VIEW3D_MT_PIE_quicksnap
]


def settings_file_path():
    """Path of the settings backup, independent of the addon's module name and install."""
    config_dir = bpy.utils.user_resource('CONFIG')
    if not config_dir:
        return None
    return os.path.join(config_dir, "quicksnap_settings.json")


def save_settings():
    """
    Back up the addon preferences to a json in Blender's config folder. Blender wipes preferences
    when an addon is removed (and keys them to the module name), so without this a version upgrade
    done as remove+install, or installed under another folder name, loses all settings.
    """
    settings = quicksnap_utils.get_addon_settings()
    path = settings_file_path()
    if settings is None or path is None:
        return
    data = {}
    for prop in settings.bl_rna.properties:
        key = prop.identifier
        if key in {'rna_type', 'bl_idname'} or prop.is_readonly:
            continue
        value = getattr(settings, key)
        try:
            json.dumps(value)
        except TypeError:
            try:
                value = list(value)
            except TypeError:
                continue
        data[key] = value
    try:
        with open(path, 'w') as settings_file:
            json.dump(data, settings_file, indent=1)
    except OSError as error:
        logger.debug(f"Could not save settings backup: {error}")


def load_settings():
    """Restore preferences from the backup (fresh installs and renamed installs pick them up)."""
    settings = quicksnap_utils.get_addon_settings()
    path = settings_file_path()
    if settings is None or path is None or not os.path.isfile(path):
        return
    try:
        with open(path) as settings_file:
            data = json.load(settings_file)
    except (OSError, ValueError) as error:
        logger.debug(f"Could not read settings backup: {error}")
        return
    for key, value in data.items():
        if key in {'rna_type', 'bl_idname'}:
            continue
        try:
            setattr(settings, key, value)
        except Exception:
            pass  # property removed or renamed in this version


def _load_settings_deferred():
    load_settings()
    return None


def register():
    for blender_class in blender_classes:
        bpy.utils.register_class(blender_class)
    # Preferences are not accessible yet while the addon is still enabling; restore right after.
    try:
        bpy.app.timers.register(_load_settings_deferred, first_interval=0.2)
    except Exception:
        pass
    window_manager = bpy.context.window_manager
    key_config = window_manager.keyconfigs.addon
    if key_config:
        export_category = key_config.keymaps.new('3D View', space_type='VIEW_3D', region_type='WINDOW', modal=False)
        export_key = export_category.keymap_items.new("object.quicksnap", type='V', value='PRESS', shift=True,
                                                      ctrl=True)
        addon_keymaps.append((export_category, export_key))


def unregister():
    try:
        save_settings()  # while the preferences still exist
    except Exception:
        pass
    for (cat, key) in addon_keymaps:
        cat.keymap_items.remove(key)
    addon_keymaps.clear()
    for blender_class in blender_classes:
        bpy.utils.unregister_class(blender_class)
