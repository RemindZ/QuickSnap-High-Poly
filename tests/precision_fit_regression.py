import importlib.util
import math
from pathlib import Path
from types import SimpleNamespace

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("quicksnap_utils_under_test", ROOT / "quicksnap_utils.py")
quicksnap_utils = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quicksnap_utils)


def make_mesh(name, vertices, faces, reverse_face_order=False):
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata(vertices, [], list(reversed(faces)) if reverse_face_order else faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


class MeshBuilder:
    def __init__(self):
        self.vertices = []
        self.faces = []
        self._indices = {}

    @staticmethod
    def _key(point):
        return tuple(round(float(value), 6) for value in point)

    def vertex(self, point):
        key = self._key(point)
        index = self._indices.get(key)
        if index is None:
            index = len(self.vertices)
            self._indices[key] = index
            self.vertices.append(key)
        return index

    def index(self, point):
        return self._indices[self._key(point)]

    def quad_grid(self, p00, p10, p11, p01, subdivisions):
        corners = tuple(Vector(point) for point in (p00, p10, p11, p01))
        grid = []
        for row in range(subdivisions + 1):
            v = row / subdivisions
            indices = []
            for column in range(subdivisions + 1):
                u = column / subdivisions
                point = ((1 - u) * (1 - v) * corners[0] +
                         u * (1 - v) * corners[1] +
                         u * v * corners[2] +
                         (1 - u) * v * corners[3])
                indices.append(self.vertex(point))
            grid.append(indices)
        for row in range(subdivisions):
            for column in range(subdivisions):
                self.faces.append((
                    grid[row][column],
                    grid[row][column + 1],
                    grid[row + 1][column + 1],
                    grid[row + 1][column],
                ))


def make_peg(subdivisions=1, reverse_face_order=False):
    builder = MeshBuilder()
    quads = [
        ((-0.6, -0.7, -1.0), (-0.6, 0.5, -1.0), (0.4, 0.5, -1.0), (0.4, -0.7, -1.0)),
        ((-0.6, -0.7, 0.0), (0.4, -0.7, 0.0), (0.4, 0.5, 0.0), (-0.6, 0.5, 0.0)),
        ((-0.6, -0.7, -1.0), (0.4, -0.7, -1.0), (0.4, -0.7, 0.0), (-0.6, -0.7, 0.0)),
        ((0.4, -0.7, -1.0), (0.4, 0.5, -1.0), (0.4, 0.5, 0.0), (0.4, -0.7, 0.0)),
        ((0.4, 0.5, -1.0), (-0.6, 0.5, -1.0), (-0.6, 0.5, 0.0), (0.4, 0.5, 0.0)),
        ((-0.6, 0.5, -1.0), (-0.6, -0.7, -1.0), (-0.6, -0.7, 0.0), (-0.6, 0.5, 0.0)),
    ]
    for quad in quads:
        builder.quad_grid(*quad, subdivisions)
    seed = builder.index((-0.6, -0.7, 0.0))
    return make_mesh("Peg", builder.vertices, builder.faces, reverse_face_order), seed


def make_socket(subdivisions=1, reverse_face_order=False,
                x_bounds=(-0.6, 0.6), y_bounds=(-0.7, 0.7)):
    builder = MeshBuilder()
    x_low, x_high = x_bounds
    y_low, y_high = y_bounds
    quads = [
        ((-2.0, -2.0, 0.0), (2.0, -2.0, 0.0), (x_high, y_low, 0.0), (x_low, y_low, 0.0)),
        ((2.0, -2.0, 0.0), (2.0, 2.0, 0.0), (x_high, y_high, 0.0), (x_high, y_low, 0.0)),
        ((2.0, 2.0, 0.0), (-2.0, 2.0, 0.0), (x_low, y_high, 0.0), (x_high, y_high, 0.0)),
        ((-2.0, 2.0, 0.0), (-2.0, -2.0, 0.0), (x_low, y_low, 0.0), (x_low, y_high, 0.0)),
        ((x_low, y_low, 0.0), (x_high, y_low, 0.0), (x_high, y_low, -1.2), (x_low, y_low, -1.2)),
        ((x_high, y_low, 0.0), (x_high, y_high, 0.0), (x_high, y_high, -1.2), (x_high, y_low, -1.2)),
        ((x_high, y_high, 0.0), (x_low, y_high, 0.0), (x_low, y_high, -1.2), (x_high, y_high, -1.2)),
        ((x_low, y_high, 0.0), (x_low, y_low, 0.0), (x_low, y_low, -1.2), (x_low, y_high, -1.2)),
    ]
    for quad in quads:
        builder.quad_grid(*quad, subdivisions)
    seed = builder.index((x_low, y_low, 0.0))
    return make_mesh("Socket", builder.vertices, builder.faces, reverse_face_order), seed


def make_wedge(angle_degrees):
    angle = math.radians(angle_degrees)
    direction = Vector((math.cos(angle), 0.0, math.sin(angle)))
    vertices = [
        (0.0, -0.7, 0.0), (0.0, 0.7, 0.0), (1.0, 0.7, 0.0), (1.0, -0.7, 0.0),
        tuple(direction), tuple(direction + Vector((0.0, 1.4, 0.0))),
    ]
    return make_mesh("Wedge", vertices, [(0, 1, 2, 3), (0, 4, 5, 1)]), 0


def make_irregular():
    vertices = [
        (0.0, 0.0, 0.0), (1.0, 0.0, 0.1), (0.2, 1.1, -0.1),
        (0.1, 0.2, 1.0),
    ]
    return make_mesh("Irregular", vertices, [(0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)]), 0


def make_neighboring_sockets():
    builder = MeshBuilder()
    x_cuts = (-2.0, -0.6, 0.6, 1.4, 2.6, 4.0)
    for x_low, x_high in zip(x_cuts, x_cuts[1:]):
        builder.quad_grid(
            (x_low, -2.0, 0.0), (x_high, -2.0, 0.0),
            (x_high, -0.7, 0.0), (x_low, -0.7, 0.0), 1)
        builder.quad_grid(
            (x_low, 0.7, 0.0), (x_high, 0.7, 0.0),
            (x_high, 2.0, 0.0), (x_low, 2.0, 0.0), 1)
    for x_low, x_high in ((-2.0, -0.6), (0.6, 1.4), (2.6, 4.0)):
        builder.quad_grid(
            (x_low, -0.7, 0.0), (x_high, -0.7, 0.0),
            (x_high, 0.7, 0.0), (x_low, 0.7, 0.0), 1)
    for x_low, x_high in ((-0.6, 0.6), (1.4, 2.6)):
        walls = [
            ((x_low, -0.7, 0.0), (x_high, -0.7, 0.0), (x_high, -0.7, -1.2), (x_low, -0.7, -1.2)),
            ((x_high, -0.7, 0.0), (x_high, 0.7, 0.0), (x_high, 0.7, -1.2), (x_high, -0.7, -1.2)),
            ((x_high, 0.7, 0.0), (x_low, 0.7, 0.0), (x_low, 0.7, -1.2), (x_high, 0.7, -1.2)),
            ((x_low, 0.7, 0.0), (x_low, -0.7, 0.0), (x_low, -0.7, -1.2), (x_low, 0.7, -1.2)),
        ]
        for wall in walls:
            builder.quad_grid(*wall, 1)
    seed = builder.index((-0.6, -0.7, 0.0))
    return make_mesh("NeighboringSockets", builder.vertices, builder.faces), seed


def make_slot():
    builder = MeshBuilder()
    quads = [
        ((-0.6, -0.7, 0.0), (-0.6, -0.7, -1.2), (-0.6, 0.7, -1.2), (-0.6, 0.7, 0.0)),
        ((-0.6, -0.7, -1.2), (-0.6, 0.7, -1.2), (0.6, 0.7, -1.2), (0.6, -0.7, -1.2)),
        ((0.6, -0.7, -1.2), (0.6, -0.7, 0.0), (0.6, 0.7, 0.0), (0.6, 0.7, -1.2)),
    ]
    for quad in quads:
        builder.quad_grid(*quad, 1)
    seed = builder.index((-0.6, -0.7, 0.0))
    return make_mesh("Slot", builder.vertices, builder.faces), seed


def assert_vector_close(actual, expected, tolerance=1e-9):
    if actual is None or (actual - expected).length > tolerance:
        delta = None if actual is None else tuple(actual[index] - expected[index] for index in range(3))
        distance = None if actual is None else (actual - expected).length
        raise AssertionError(
            f"expected {tuple(expected)}, got {tuple(actual) if actual is not None else None}, "
            f"delta {delta}, distance {distance}, tolerance {tolerance}"
        )


def assert_patch_directions(obj, seed, expected_directions):
    mesh_data = quicksnap_utils._mesh_fit_data(obj)
    seeds = quicksnap_utils._seed_polygons(mesh_data, 'POINTS', seed)
    patches = quicksnap_utils._candidate_patches(mesh_data, seeds)
    normals = [Vector(patch['normal']) for patch in patches]
    for expected in expected_directions:
        if not any(normal.dot(expected) > 0.999 for normal in normals):
            raise AssertionError(f"missing patch normal {tuple(expected)}; got {[tuple(n) for n in normals]}")


def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)


def run_corner_case(subdivisions, reverse_face_order):
    clear_scene()
    peg, peg_seed = make_peg(subdivisions, reverse_face_order)
    socket, socket_seed = make_socket(subdivisions, reverse_face_order)
    assert_patch_directions(peg, peg_seed, (
        Vector((1, 0, 0)), Vector((-1, 0, 0)),
        Vector((0, 1, 0)), Vector((0, -1, 0)),
        Vector((0, 0, 1)), Vector((0, 0, -1)),
    ))
    assert_patch_directions(socket, socket_seed, (
        Vector((1, 0, 0)), Vector((-1, 0, 0)),
        Vector((0, 1, 0)), Vector((0, -1, 0)),
        Vector((0, 0, 1)),
    ))
    contact = socket.matrix_world @ socket.data.vertices[socket_seed].co
    return quicksnap_utils.compute_precision_fit(
        bpy.context,
        SimpleNamespace(ignore_modifiers=True),
        peg.name, 'POINTS', peg_seed,
        socket.name, 'POINTS', socket_seed,
        contact,
    )


def run_slot_case():
    clear_scene()
    peg, peg_seed = make_peg()
    slot, slot_seed = make_slot()
    contact = slot.matrix_world @ slot.data.vertices[slot_seed].co
    return quicksnap_utils.compute_precision_fit(
        bpy.context,
        SimpleNamespace(ignore_modifiers=True),
        peg.name, 'POINTS', peg_seed,
        slot.name, 'POINTS', slot_seed,
        contact,
    )


def run_pair(source, source_seed, target, target_seed):
    contact = target.matrix_world @ target.data.vertices[target_seed].co
    return quicksnap_utils.compute_precision_fit(
        bpy.context,
        SimpleNamespace(ignore_modifiers=True),
        source.name, 'POINTS', source_seed,
        target.name, 'POINTS', target_seed,
        contact,
    )


def run_wedge_case(angle_degrees):
    clear_scene()
    peg, peg_seed = make_peg()
    wedge, wedge_seed = make_wedge(angle_degrees)
    return run_pair(peg, peg_seed, wedge, wedge_seed)


def run_organic_case():
    clear_scene()
    source, source_seed = make_irregular()
    target, target_seed = make_irregular()
    return run_pair(source, source_seed, target, target_seed)


def run_width_case(x_bounds, y_bounds):
    clear_scene()
    peg, peg_seed = make_peg()
    socket, socket_seed = make_socket(x_bounds=x_bounds, y_bounds=y_bounds)
    return run_pair(peg, peg_seed, socket, socket_seed)


def run_stale_index_case():
    clear_scene()
    peg, _ = make_peg()
    socket, socket_seed = make_socket()
    contact = socket.matrix_world @ socket.data.vertices[socket_seed].co
    return quicksnap_utils.compute_precision_fit(
        bpy.context,
        SimpleNamespace(ignore_modifiers=True),
        peg.name, 'POINTS', 10_000,
        socket.name, 'POINTS', socket_seed,
        contact,
    )


def run_neighboring_socket_case():
    clear_scene()
    peg, peg_seed = make_peg()
    sockets, socket_seed = make_neighboring_sockets()
    return run_pair(peg, peg_seed, sockets, socket_seed)


def main():
    for subdivisions, reverse_face_order in ((1, False), (8, False), (8, True)):
        fit = run_corner_case(subdivisions, reverse_face_order)
        assert_vector_close(fit, Vector((0.1, 0.1, 0.0)), tolerance=1e-7)
        print(f"corner subdivisions={subdivisions} reverse={reverse_face_order}: PASS")
    assert_vector_close(run_slot_case(), Vector((0.1, 0.0, 0.0)), tolerance=1e-7)
    print("slot: PASS")
    assert run_wedge_case(120) is None
    assert run_wedge_case(150) is None
    print("wedges: PASS")
    assert run_organic_case() is None
    print("organic: PASS")
    assert run_width_case((-0.6, 0.4), (-0.7, 0.5)) is None
    assert run_width_case((-0.6, 0.3), (-0.7, 0.4)) is None
    print("impossible fits: PASS")
    assert run_stale_index_case() is None
    print("stale index: PASS")
    assert_vector_close(run_neighboring_socket_case(), Vector((0.1, 0.1, 0.0)), tolerance=1e-7)
    print("neighboring socket: PASS")
    print("precision_fit_regression: PASS")


if __name__ == "__main__":
    main()
