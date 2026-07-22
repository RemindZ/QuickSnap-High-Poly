import importlib.util
from pathlib import Path
from types import SimpleNamespace

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("quicksnap_utils_under_test", ROOT / "quicksnap_utils.py")
quicksnap_utils = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quicksnap_utils)


def make_mesh(name, vertices, faces):
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


def make_peg():
    vertices = [
        (-0.6, -0.7, -1.0),
        (0.4, -0.7, -1.0),
        (0.4, 0.5, -1.0),
        (-0.6, 0.5, -1.0),
        (-0.6, -0.7, 0.0),
        (0.4, -0.7, 0.0),
        (0.4, 0.5, 0.0),
        (-0.6, 0.5, 0.0),
    ]
    faces = [
        (0, 3, 2, 1),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    ]
    return make_mesh("Peg", vertices, faces), 4


def make_socket():
    vertices = [
        (-2.0, -2.0, 0.0),
        (2.0, -2.0, 0.0),
        (2.0, 2.0, 0.0),
        (-2.0, 2.0, 0.0),
        (-0.6, -0.7, 0.0),
        (0.6, -0.7, 0.0),
        (0.6, 0.7, 0.0),
        (-0.6, 0.7, 0.0),
        (-0.6, -0.7, -1.2),
        (0.6, -0.7, -1.2),
        (0.6, 0.7, -1.2),
        (-0.6, 0.7, -1.2),
    ]
    faces = [
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
        (4, 5, 9, 8),
        (5, 6, 10, 9),
        (6, 7, 11, 10),
        (7, 4, 8, 11),
    ]
    return make_mesh("Socket", vertices, faces), 4


def assert_vector_close(actual, expected, tolerance=1e-9):
    if actual is None or (actual - expected).length > tolerance:
        raise AssertionError(f"expected {tuple(expected)}, got {actual}")


def main():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    peg, peg_seed = make_peg()
    socket, socket_seed = make_socket()
    contact = socket.matrix_world @ socket.data.vertices[socket_seed].co

    fit = quicksnap_utils.compute_precision_fit(
        bpy.context,
        SimpleNamespace(ignore_modifiers=True),
        peg.name, 'POINTS', peg_seed,
        socket.name, 'POINTS', socket_seed,
        contact,
    )
    assert_vector_close(fit, Vector((0.1, 0.1, 0.0)))
    print("precision_fit_regression: PASS")


if __name__ == "__main__":
    main()
