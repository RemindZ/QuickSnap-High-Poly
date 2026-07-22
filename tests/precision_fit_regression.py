import importlib.util
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


def make_socket(subdivisions=1, reverse_face_order=False):
    builder = MeshBuilder()
    quads = [
        ((-2.0, -2.0, 0.0), (2.0, -2.0, 0.0), (0.6, -0.7, 0.0), (-0.6, -0.7, 0.0)),
        ((2.0, -2.0, 0.0), (2.0, 2.0, 0.0), (0.6, 0.7, 0.0), (0.6, -0.7, 0.0)),
        ((2.0, 2.0, 0.0), (-2.0, 2.0, 0.0), (-0.6, 0.7, 0.0), (0.6, 0.7, 0.0)),
        ((-2.0, 2.0, 0.0), (-2.0, -2.0, 0.0), (-0.6, -0.7, 0.0), (-0.6, 0.7, 0.0)),
        ((-0.6, -0.7, 0.0), (0.6, -0.7, 0.0), (0.6, -0.7, -1.2), (-0.6, -0.7, -1.2)),
        ((0.6, -0.7, 0.0), (0.6, 0.7, 0.0), (0.6, 0.7, -1.2), (0.6, -0.7, -1.2)),
        ((0.6, 0.7, 0.0), (-0.6, 0.7, 0.0), (-0.6, 0.7, -1.2), (0.6, 0.7, -1.2)),
        ((-0.6, 0.7, 0.0), (-0.6, -0.7, 0.0), (-0.6, -0.7, -1.2), (-0.6, 0.7, -1.2)),
    ]
    for quad in quads:
        builder.quad_grid(*quad, subdivisions)
    seed = builder.index((-0.6, -0.7, 0.0))
    return make_mesh("Socket", builder.vertices, builder.faces, reverse_face_order), seed


def assert_vector_close(actual, expected, tolerance=1e-9):
    if actual is None or (actual - expected).length > tolerance:
        raise AssertionError(f"expected {tuple(expected)}, got {actual}")


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


def main():
    for subdivisions, reverse_face_order in ((1, False), (8, False), (8, True)):
        fit = run_corner_case(subdivisions, reverse_face_order)
        assert_vector_close(fit, Vector((0.1, 0.1, 0.0)), tolerance=1.4e-9)
        print(f"corner subdivisions={subdivisions} reverse={reverse_face_order}: PASS")
    print("precision_fit_regression: PASS")


if __name__ == "__main__":
    main()
