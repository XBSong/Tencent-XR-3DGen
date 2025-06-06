import argparse
import os
import sys
import time

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from numpy import arange, sin, cos, arccos


def load_mesh(mesh_path: str):
    version_info = bpy.app.version
    if version_info[0] > 2:
        bpy.ops.wm.obj_import(filepath=mesh_path,
                              forward_axis='NEGATIVE_Z', up_axis='Y')
    else:
        bpy.ops.import_scene.obj(
            filepath=mesh_path, axis_forward='-Z', axis_up='Y')
    bpy.ops.object.select_all(action='DESELECT')
    meshes = []
    for ind, obj in enumerate(bpy.context.scene.objects):
        if obj.type == 'MESH':
            meshes.append(obj)
    return meshes


def join_list_of_mesh(mesh_list):
    assert len(mesh_list) > 0
    if len(mesh_list) > 1:
        bpy.ops.object.select_all(action='DESELECT')
        for ind, obj in enumerate(mesh_list):
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
        bpy.ops.object.join()
        joint_mesh = bpy.context.object
    else:
        joint_mesh = mesh_list[0]
    return joint_mesh


def triangulate(the_mesh):
    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.view_layer.objects.active = the_mesh
    the_mesh.select_set(True)
    the_mesh.modifiers.new("triangulate", "TRIANGULATE")
    bpy.ops.object.convert(target='MESH')  # bake modifier to mesh
    return the_mesh


def solidify(the_mesh, thickness=0.005):
    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.view_layer.objects.active = the_mesh
    the_mesh.select_set(True)
    the_mesh.modifiers.new("solidify", "SOLIDIFY")
    the_mesh.modifiers["solidify"].thickness = thickness
    bpy.ops.object.convert(target='MESH')  # bake modifier to mesh
    return the_mesh


def decimate(the_mesh, target_faces_num):
    num_faces = len(the_mesh.data.polygons)
    if num_faces > target_faces_num:
        decimate_ratio = target_faces_num / num_faces
        decimator = the_mesh.modifiers.new("decimate", "DECIMATE")
        decimator.ratio = decimate_ratio
        bpy.ops.object.convert(target='MESH')
    return the_mesh


def remesh(the_mesh, voxel_size):
    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.view_layer.objects.active = the_mesh
    the_mesh.select_set(True)
    the_mesh.modifiers.new("remesh", "REMESH")
    the_mesh.modifiers["remesh"].voxel_size = voxel_size
    the_mesh.modifiers.new("triangulate", "TRIANGULATE")

    bpy.ops.object.convert(target='MESH')  # bake modifier to mesh
    return the_mesh


def export_mesh_obj(mesh, mesh_path, path_mode='STRIP', global_scale=1, z_up=False):
    print("export mesh", mesh, "# triangles", len(mesh.data.polygons))
    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.view_layer.objects.active = mesh
    mesh.select_set(True)
    version_info = bpy.app.version
    if version_info[0] > 2:
        if z_up:
            bpy.ops.wm.obj_export(filepath=mesh_path,
                                  path_mode=path_mode,
                                  forward_axis='Y', up_axis='Z',
                                  global_scale=global_scale,
                                  export_selected_objects=True)
        else:
            bpy.ops.wm.obj_export(filepath=mesh_path,
                                  path_mode=path_mode,
                                  forward_axis='NEGATIVE_Z', up_axis='Y',
                                  global_scale=global_scale,
                                  export_selected_objects=True)
    else:
        if z_up:
            bpy.ops.export_scene.obj(filepath=mesh_path,
                                     use_selection=True,
                                     path_mode=path_mode,
                                     axis_forward='Y', axis_up='Z',
                                     global_scale=global_scale)
        else:
            bpy.ops.export_scene.obj(filepath=mesh_path,
                                     use_selection=True,
                                     path_mode=path_mode,
                                     axis_forward='-Z', axis_up='Y',
                                     global_scale=global_scale)
    bpy.ops.object.select_all(action='DESELECT')
    return mesh


def toggle_alpha_blend_mode(object):
    if object.material_slots:
        for slot in object.material_slots:
            if slot.material:
                if slot.material.blend_method == 'OPAQUE':
                    slot.material.blend_method == 'BLEND'
                else:
                    slot.material.blend_method == 'OPAQUE'


def remove_alpha_image(object):
    if object.material_slots:
        for slot in object.material_slots:
            if slot.material:
                node_tree = slot.material.node_tree

                for node in node_tree.nodes:
                    if node.type == 'BSDF_PRINCIPLED':
                        if len(node.inputs["Alpha"].links) > 0:
                            l = node.inputs["Alpha"].links[0]
                            if l is not None:
                                alpha_tex_image_node = l.from_node
                                node_tree.links.remove(l)
                                node.inputs["Alpha"].default_value = 1.0
                                if alpha_tex_image_node is not None:
                                    node_tree.nodes.remove(
                                        alpha_tex_image_node)


def toggle_alpha_linkage(object):
    if object.material_slots:
        for slot in object.material_slots:
            if slot.material:
                node_tree = slot.material.node_tree
                for node in node_tree.nodes:
                    if node.type == 'BSDF_PRINCIPLED':
                        if len(node.inputs["Alpha"].links) > 0:
                            l = node.inputs["Alpha"].links[0]
                            node.inputs["Alpha"].links.new(
                                l.input.outputs["Alpha"], node.inputs["Alpha"])


def toggle_texture_node_blend_mode(object):
    image_names = []
    if object.material_slots:
        for slot in object.material_slots:
            if slot.material:
                node_tree = slot.material.node_tree
                for node in node_tree.nodes:
                    if node.type == 'TEX_IMAGE':
                        l_alpha = node.outputs["Alpha"]
                        l_color = node.outputs["Color"]
                        if len(l_alpha.links) > 0:
                            l = l_alpha.links[0]
                            if l.to_socket.name == 'Base Color' or l.to_socket.name == 'Alpha':
                                image_path = node.image.filepath
                                image_filename = os.path.split(image_path)[1]
                                image_names.append(image_filename)
                                node.image.alpha_mode = 'NONE'
                        elif len(l_color.links) > 0:
                            l = l_color.links[0]
                            if l.to_socket.name == 'Base Color' or l.to_socket.name == 'Alpha':
                                image_path = node.image.filepath
                                image_filename = os.path.split(image_path)[1]
                                image_names.append(image_filename)
                                node.image.alpha_mode = 'NONE'
    for image_name in image_names:
        bpy.data.images[image_name].alpha_mode = 'NONE'

    return image_names


def fix_transparency(textured_mesh, remove_alpha: bool = False, change_blend_mode: bool = False,
                     change_linkage: bool = False, set_none: bool = False):
    if remove_alpha:
        print("Fix transparency by removing alpha........")
        remove_alpha_image(textured_mesh)

    if change_blend_mode:
        print("Fix transparency by toggle blend mode........")
        toggle_alpha_blend_mode(textured_mesh)

    if change_linkage:
        print("Fix transparency by toggle input of BSDF alpha linkage........")
        toggle_alpha_linkage(textured_mesh)

    if set_none:
        print("Fix transparency by toggle alpha node of image texture node........")
        toggle_texture_node_blend_mode(textured_mesh)


def delete_occluded_faces_from_cameras(themesh, cameras, fix_normal=False, anchors=[[0.333, 0.333, 0.334]]):
    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.view_layer.objects.active = themesh
    bpy.ops.object.mode_set(mode='EDIT')
    me = themesh.data
    bm = bmesh.from_edit_mesh(me)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    raycast_mesh = themesh
    # construct camera tuples
    camera_items = []
    for cam in cameras:
        ray_origin = cam.location
        ray_begin_local = raycast_mesh.matrix_world.inverted() @ ray_origin
        depsgraph = bpy.context.evaluated_depsgraph_get()
        bvhtree = BVHTree.FromObject(raycast_mesh, depsgraph)
        item = (ray_origin, ray_begin_local, bvhtree)
        camera_items.append(item)
    assert themesh.type == "MESH"

    faces_select = []  # list of faces to retain
    faces_flip = []  # list of faces that has flip normal

    for idx, face in enumerate(bm.faces):
        observed = False
        vert_vector = [v.co for v in face.verts]
        for anchor in anchors:
            anchor_pos = anchor[0] * vert_vector[0] + anchor[1] * \
                         vert_vector[1] + anchor[2] * vert_vector[2]
            for item in camera_items:
                ray_origin, ray_begin_local, bvhtree = item
                ray_direction = anchor_pos - ray_begin_local
                ray_direction.normalize()
                position, norm, faceID, _ = bvhtree.ray_cast(
                    ray_begin_local, ray_direction, 50)
                if idx == faceID:
                    if norm != Vector((0.0000, 0.0000, 0.0000)):
                        observed = True
                        break

            if observed:
                break

        if not observed:
            faces_select.append(face)

    bmesh.ops.delete(bm, geom=faces_select, context="FACES")
    bmesh.update_edit_mesh(me)
    bm.free()
    bpy.ops.object.mode_set(mode='OBJECT')

    return themesh


def put_cam_around_obj(n_cam, obj_center, length, fix_kpts=None):
    pi = 3.14

    def sphere_point_sample(n=300):
        # use fibonacci spiral
        goldenRatio = (1 + 5 ** 0.5) / 2
        i = arange(0, n)
        theta = 2 * pi * i / goldenRatio
        phi = arccos(1 - 2 * (i + 0.5) / n)
        x, y, z = cos(theta) * sin(phi), sin(theta) * sin(phi), cos(phi)
        return np.stack([x, y, z], axis=-1)

    def look_at(obj_camera, point):
        loc_camera = obj_camera.location
        direction = point - loc_camera
        # point the cameras '-Z' and use its 'Y' as up
        rot_quat = direction.to_track_quat('-Z', 'Y')
        # assume we're using euler rotation
        obj_camera.rotation_euler = rot_quat.to_euler()

    def set_camera(bpy_cam, angle=pi / 3, W=600, H=600):
        bpy_cam.angle = angle
        bpy_scene = bpy.context.scene
        bpy_scene.render.resolution_x = W
        bpy_scene.render.resolution_y = H

    # 设置Camera，在物体为中心的球面上采样相机
    points = sphere_point_sample(n_cam)
    points = points * length * 1.5  # scale
    points = obj_center[None] + points
    cam_names = ["cam-%04d" % i for i in range(n_cam)]
    for i in range(n_cam):
        camera_data = bpy.data.cameras.new(name=cam_names[i])
        camera_object = bpy.data.objects.new(cam_names[i], camera_data)
        bpy.context.scene.collection.objects.link(camera_object)
        camera_object.location = Vector(points[i])
        look_at_point = Vector(obj_center)  # Vector((0,0,0))
        camera_data.display_size = 0.1
        camera_data.clip_start = 0.01
        camera_data.clip_end = 100
        set_camera(camera_data, angle=pi / 3, W=600, H=600)
        look_at(camera_object, look_at_point)
        bpy.context.view_layer.update()  # update camera params

    # add camera around key points
    if fix_kpts is not None:
        for k, v in fix_kpts.items():
            cam_name = "cam-" + k
            cam_names.append(cam_name)
            camera_data = bpy.data.cameras.new(name=cam_name)
            camera_object = bpy.data.objects.new(cam_name, camera_data)
            bpy.context.scene.collection.objects.link(camera_object)
            camera_object.location = Vector((v[0], v[1], v[2]))
            camera_data.display_size = 0.05
            camera_data.clip_start = 0.01
            camera_data.clip_end = 100
            bpy.context.view_layer.update()
    return [bpy.data.objects[cam] for cam in cam_names]


def read_mesh_to_ndarray(mesh, mode="edit"):
    ''' read the vert coordinate of a deformed mesh
    :param mesh: mesh object
    :return: numpy array of the mesh
    '''
    assert mode in ["edit", "object"]

    if mode == "object":
        bm = bmesh.new()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        bm.from_object(mesh, depsgraph)
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        mverts_co = [(v.co) for v in bm.verts]
        mverts_co = np.asarray(mverts_co, dtype=np.float32)
        bm.free()
    elif mode == "edit":
        bpy.context.view_layer.objects.active = mesh
        bpy.ops.object.editmode_toggle()
        bm = bmesh.from_edit_mesh(mesh.data)
        mverts_co = [(v.co) for v in bm.verts]
        mverts_co = np.asarray(mverts_co, dtype=np.float32)
        bm.free()
        bpy.ops.object.editmode_toggle()

    return mverts_co


def compute_mesh_size(meshes):
    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.view_layer.objects.active = None
    verts = []
    for ind, mesh in enumerate(meshes):
        vert = read_mesh_to_ndarray(mesh, mode="edit")
        mat = np.asarray(mesh.matrix_world)
        R, t = mat[:3, :3], mat[:3, 3:]  # Apply World Scale
        verts.append((R @ vert.T + t).T)
    verts = np.concatenate(verts, axis=0)

    min_0 = verts[:, 0].min(axis=0)
    max_0 = verts[:, 0].max(axis=0)
    min_1 = verts[:, 1].min(axis=0)
    max_1 = verts[:, 1].max(axis=0)
    min_2 = verts[:, 2].min(axis=0)
    max_2 = verts[:, 2].max(axis=0)

    min_ = np.array([min_0, min_1, min_2])
    max_ = np.array([max_0, max_1, max_2])

    obj_center = (min_ + max_) / 2

    # use max len of xyz, instead of z
    length = max(max_ - min_)
    diagonal = np.linalg.norm(max_ - min_)

    return obj_center, length, diagonal, min_, max_


if __name__ == '__main__':
    t_start = time.time()
    local_time = time.localtime(t_start)
    local_time_str = time.strftime('%Y-%m-%d-%H-%M-%S', local_time)
    print("Manifold process start. Local time is %s" % (local_time_str))

    argv = sys.argv
    raw_argv = argv[argv.index("--") + 1:]  # get all args after "--"

    parser = argparse.ArgumentParser(description='File converter.')
    parser.add_argument('--mesh_path', type=str,
                        help='path to mesh to be converted')
    parser.add_argument('--output_mesh_path', type=str,
                        help='path of output mesh')
    parser.add_argument('--skip_occlusion', action='store_true',
                        help='Not use BVH Tree to remove interior polygons')
    parser.add_argument('--ray_tracer_camera_number', type=int, default=30,
                        help='ray tracer camera number for deleting mesh under mesh')
    parser.add_argument('--z_up', action='store_true',
                        help='use z up axis in obj output')
    parser.add_argument('--fix_transparency', action='store_true',
                        help='fix transparency error on some models. HACKY.')
    parser.add_argument('--remove_alpha', action='store_true',
                        help='fix transparency error on some models by moving alpha in BSDF.')
    parser.add_argument('--change_blend_mode', action='store_true',
                        help='fix transparency error on some models by change material\'s blend mode.')
    parser.add_argument('--change_linkage', action='store_true',
                        help='fix transparency error on some models by changing material\'s alpha input to alpha of image.')
    parser.add_argument('--set_none', action='store_true',
                        help='fix transparency error on some models by setting alpha mode on texture node to NONE.')
    parser.add_argument('--copy_texture', action='store_true',
                        help='copy texture image of the object')
    args = parser.parse_args(raw_argv)

    copy_texture = args.copy_texture

    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()

    skip_occlusion = args.skip_occlusion
    z_up = args.z_up

    anchors = [[0.33, 0.33, 0.34],
               [0.70, 0.15, 0.15],
               [0.15, 0.70, 0.15],
               [0.15, 0.15, 0.70],
               [0.98, 0.01, 0.01],
               [0.01, 0.98, 0.01],
               [0.01, 0.01, 0.98]]

    mesh_path = args.mesh_path
    output_mesh_path = args.output_mesh_path
    combine = output_mesh_path
    mesh_folder = os.path.split(mesh_path)[0]
    mesh_name = os.path.split(mesh_path)[1]
    mesh_basename = os.path.splitext(mesh_name)[0]
    if "_resize" == mesh_name[-7:]:
        mesh_basename.replace("_resize", "")

    texture_meshes = load_mesh(mesh_path)
    obj_center, length, diagonal, _, _ = compute_mesh_size(texture_meshes)

    print("Texture mesh center is %s, length is %f....." %
          (str(obj_center), length))

    the_texture_mesh = join_list_of_mesh(texture_meshes)

    if not skip_occlusion:
        texture_cameras = put_cam_around_obj(
            n_cam=args.ray_tracer_camera_number, obj_center=obj_center, length=length, fix_kpts=None)
        texture_mesh = delete_occluded_faces_from_cameras(
            the_texture_mesh, texture_cameras, anchors=anchors)
    else:
        texture_mesh = the_texture_mesh

    if args.fix_transparency:
        fix_transparency(textured_mesh=texture_mesh,
                         remove_alpha=args.remove_alpha,
                         change_blend_mode=args.change_blend_mode,
                         change_linkage=args.change_linkage,
                         set_none=args.set_none)
        if copy_texture:
            export_mesh_obj(texture_mesh, combine, 'COPY', z_up=z_up)
        else:
            export_mesh_obj(texture_mesh, combine, 'AUTO', z_up=z_up)
    else:
        if copy_texture:
            export_mesh_obj(texture_mesh, combine, 'COPY', z_up=z_up)
        else:
            export_mesh_obj(texture_mesh, combine, 'AUTO', z_up=z_up)

    t_end = time.time()
    local_time = time.localtime(t_end)
    local_time_str = time.strftime('%Y-%m-%d-%H-%M-%S', local_time)
    print("Manifold process color mesh step done. Local time is %s" %
          (local_time_str))
