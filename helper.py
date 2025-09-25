import os
import shutil
import random
import math
import mathutils
import bpy
from bpy.app.handlers import persistent


# global addon script variables
EMPTY_NAME = "BlenderNeRF Sphere"
CAMERA_NAME = "BlenderNeRF Camera"

## property poll and update functions


# camera pointer property poll function
def poll_is_camera(self, obj):
    return obj.type == "CAMERA"


def visualize_sphere(self, context):
    scene = context.scene

    if EMPTY_NAME not in scene.objects.keys() and not scene.sphere_exists:
        # if empty sphere does not exist, create
        bpy.ops.object.empty_add(
            type="SPHERE"
        )  # non default location, rotation and scale here are sometimes not applied, so we enforce them manually below
        empty = context.active_object
        empty.name = EMPTY_NAME
        empty.location = scene.sphere_location
        empty.rotation_euler = scene.sphere_rotation
        empty.scale = scene.sphere_scale
        empty.empty_display_size = scene.sphere_radius

        scene.sphere_exists = True

    elif EMPTY_NAME in scene.objects.keys() and scene.sphere_exists:
        if CAMERA_NAME in scene.objects.keys() and scene.camera_exists:
            delete_camera(scene, CAMERA_NAME)

        objects = bpy.data.objects
        objects.remove(objects[EMPTY_NAME], do_unlink=True)

        scene.sphere_exists = False


def visualize_camera(self, context):
    scene = context.scene

    if CAMERA_NAME not in scene.objects.keys() and not scene.camera_exists:
        if EMPTY_NAME not in scene.objects.keys():
            scene.show_sphere = True

        bpy.ops.object.camera_add()
        camera = context.active_object
        camera.name = CAMERA_NAME
        camera.data.name = CAMERA_NAME
        camera.location = sample_from_sphere(scene)
        bpy.data.cameras[CAMERA_NAME].lens = scene.focal

        cam_constraint = camera.constraints.new(type="TRACK_TO")
        cam_constraint.track_axis = "TRACK_Z" if scene.outwards else "TRACK_NEGATIVE_Z"
        cam_constraint.up_axis = "UP_Y"
        cam_constraint.target = bpy.data.objects[EMPTY_NAME]

        scene.camera_exists = True

    elif CAMERA_NAME in scene.objects.keys() and scene.camera_exists:
        objects = bpy.data.objects
        objects.remove(objects[CAMERA_NAME], do_unlink=True)

        for block in bpy.data.cameras:
            if CAMERA_NAME in block.name:
                bpy.data.cameras.remove(block)

        scene.camera_exists = False


def delete_camera(scene, name):
    objects = bpy.data.objects
    objects.remove(objects[name], do_unlink=True)

    scene.show_camera = False
    scene.camera_exists = False

    for block in bpy.data.cameras:
        if name in block.name:
            bpy.data.cameras.remove(block)


# non uniform sampling when stretched or squeezed sphere
def sample_from_sphere(scene):
    if scene.sequential_trajectory:
        # Sequential trajectory: evenly distribute cameras around the sphere
        total_frames = scene.cos_nb_frames
        current_frame_index = scene.frame_current - scene.frame_start

        # Ensure we stay within bounds
        if current_frame_index < 0:
            current_frame_index = 0
        elif current_frame_index >= total_frames:
            current_frame_index = total_frames - 1

        # Calculate position using spiral pattern for better coverage
        if total_frames > 1:
            progress = current_frame_index / (total_frames - 1)  # 0 to 1
        else:
            progress = 0

        # Sequential trajectory with fewer rotations, starting from horizontal

        # Reduce number of rotations - make fewer spins around the sphere
        max_rotations = 1.5  # 1.5 full rotations instead of many
        theta = progress * 2 * math.pi * max_rotations

        # Vary elevation (phi) to cover different heights, starting horizontal
        if scene.upper_views:
            # Upper hemisphere: start horizontal, go up gradually
            phi_start = math.pi / 2  # Start at horizon (90 degrees)
            phi_end = math.pi / 6  # End at 30 degrees from top
            phi = phi_start - progress * (phi_start - phi_end)
        else:
            # Full sphere: start horizontal, vary up and down
            phi_center = math.pi / 2  # Horizontal center
            phi_range = math.pi * 0.3  # ±54 degrees from horizontal
            # Use sine wave for smooth vertical movement
            phi = phi_center + math.sin(progress * math.pi * 2) * phi_range * 0.5

        # Convert spherical to cartesian coordinates
        unit_x = math.cos(theta) * math.sin(phi)
        unit_y = math.sin(theta) * math.sin(phi)
        unit_z = abs(math.cos(phi)) if scene.upper_views else math.cos(phi)
        unit = mathutils.Vector((unit_x, unit_y, unit_z))
    else:
        # Original random sampling
        seed = (2654435761 * (scene.seed + 1)) ^ (805459861 * (scene.frame_current + 1))
        rng = random.Random(seed)  # random number generator

        # sample random angles
        theta = rng.random() * 2 * math.pi
        phi = math.acos(
            1 - 2 * rng.random()
        )  # ensure uniform sampling from unit sphere

        # uniform sample from unit sphere, given theta and phi
        unit_x = math.cos(theta) * math.sin(phi)
        unit_y = math.sin(theta) * math.sin(phi)
        unit_z = abs(math.cos(phi)) if scene.upper_views else math.cos(phi)
        unit = mathutils.Vector((unit_x, unit_y, unit_z))

    # ellipsoid sample : center + rotation @ radius * unit sphere
    point = scene.sphere_radius * mathutils.Vector(scene.sphere_scale) * unit
    rotation = mathutils.Euler(scene.sphere_rotation).to_matrix()
    point = mathutils.Vector(scene.sphere_location) + rotation @ point

    return point


## two way property link between sphere and ui (property and handler functions)
# https://blender.stackexchange.com/questions/261174/2-way-property-link-or-a-filtered-property-display


def properties_ui_upd(self, context):
    can_scene_upd(self, context)


@persistent
def properties_desgraph_upd(scene):
    can_properties_upd(scene)


def properties_ui(self, context):
    scene = context.scene

    if EMPTY_NAME in scene.objects.keys():
        upd_off()
        bpy.data.objects[EMPTY_NAME].location = scene.sphere_location
        bpy.data.objects[EMPTY_NAME].rotation_euler = scene.sphere_rotation
        bpy.data.objects[EMPTY_NAME].scale = scene.sphere_scale
        bpy.data.objects[EMPTY_NAME].empty_display_size = scene.sphere_radius
        upd_on()

    if CAMERA_NAME in scene.objects.keys():
        upd_off()
        bpy.data.cameras[CAMERA_NAME].lens = scene.focal
        bpy.context.scene.objects[CAMERA_NAME].constraints["Track To"].track_axis = (
            "TRACK_Z" if scene.outwards else "TRACK_NEGATIVE_Z"
        )
        upd_on()


# if empty sphere modified outside of ui panel, edit panel properties
def properties_desgraph(scene):
    if scene.show_sphere and EMPTY_NAME in scene.objects.keys():
        upd_off()
        scene.sphere_location = bpy.data.objects[EMPTY_NAME].location
        scene.sphere_rotation = bpy.data.objects[EMPTY_NAME].rotation_euler
        scene.sphere_scale = bpy.data.objects[EMPTY_NAME].scale
        scene.sphere_radius = bpy.data.objects[EMPTY_NAME].empty_display_size
        upd_on()

    if scene.show_camera and CAMERA_NAME in scene.objects.keys():
        upd_off()
        scene.focal = bpy.data.cameras[CAMERA_NAME].lens
        scene.outwards = (
            bpy.context.scene.objects[CAMERA_NAME].constraints["Track To"].track_axis
            == "TRACK_Z"
        )
        upd_on()

    if EMPTY_NAME not in scene.objects.keys() and scene.sphere_exists:
        if CAMERA_NAME in scene.objects.keys() and scene.camera_exists:
            delete_camera(scene, CAMERA_NAME)

        scene.show_sphere = False
        scene.sphere_exists = False

    if CAMERA_NAME not in scene.objects.keys() and scene.camera_exists:
        scene.show_camera = False
        scene.camera_exists = False

        for block in bpy.data.cameras:
            if CAMERA_NAME in block.name:
                bpy.data.cameras.remove(block)

    if CAMERA_NAME in scene.objects.keys():
        scene.objects[CAMERA_NAME].location = sample_from_sphere(scene)


def empty_fn(self, context):
    pass


can_scene_upd = properties_ui
can_properties_upd = properties_desgraph


def upd_off():  # make sub function to an empty function
    global can_scene_upd, can_properties_upd
    can_scene_upd = empty_fn
    can_properties_upd = empty_fn


def upd_on():
    global can_scene_upd, can_properties_upd
    can_scene_upd = properties_ui
    can_properties_upd = properties_desgraph


## blender handler functions


# reset properties back to intial
@persistent
def post_render(scene):
    if any(scene.rendering):  # execute this function only when rendering with addon
        dataset_names = (
            scene.sof_dataset_name,
            scene.ttc_dataset_name,
            scene.cos_dataset_name,
        )
        method_dataset_name = dataset_names[list(scene.rendering).index(True)]

        if scene.rendering[0]:
            scene.frame_step = scene.init_frame_step  # sof : reset frame step

        if scene.rendering[1]:  # ttc : reset frame end
            scene.frame_end = scene.init_frame_end

        if scene.rendering[2]:  # cos : reset camera settings
            if not scene.init_camera_exists:
                delete_camera(scene, CAMERA_NAME)
            if not scene.init_sphere_exists:
                objects = bpy.data.objects
                objects.remove(objects[EMPTY_NAME], do_unlink=True)
                scene.show_sphere = False
                scene.sphere_exists = False

            scene.camera = scene.init_active_camera
            scene.frame_end = scene.init_frame_end

        scene.rendering = (False, False, False)
        scene.render.filepath = scene.init_output_path  # reset filepath

        # clean directory name (unsupported characters replaced) and output path
        output_dir = bpy.path.clean_name(method_dataset_name)
        output_path = os.path.join(scene.save_path, output_dir)

        # compress dataset and remove folder (only keep zip)
        shutil.make_archive(
            output_path, "zip", output_path
        )  # output filename = output_path
        shutil.rmtree(output_path)


# set initial property values (bpy.data and bpy.context require a loaded scene)
@persistent
def set_init_props(scene):
    filepath = bpy.data.filepath
    filename = bpy.path.basename(filepath)
    default_save_path = filepath[
        : -len(filename)
    ]  # remove file name from blender file path = directoy path

    scene.save_path = default_save_path
    scene.init_frame_step = scene.frame_step
    scene.init_output_path = scene.render.filepath

    bpy.app.handlers.depsgraph_update_post.remove(set_init_props)


# update cos camera when changing frame
@persistent
def cos_camera_update(scene):
    if CAMERA_NAME in scene.objects.keys():
        scene.objects[CAMERA_NAME].location = sample_from_sphere(scene)
