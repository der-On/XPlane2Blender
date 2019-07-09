"""
This module is the starting point for converting 2.49's
combined UV + Texture, Material TextureFace button hybrid
model to our Material + Material's Textures model

It is not named material_and_texture_converter because
there is no texture datablock or setting to convert and
our modern model is entirely material based.
"""

import collections
import functools
import re
import sys
from typing import Callable, Dict, List, Match, Optional, Set, Tuple, Union, cast

import bmesh
import bpy
import ctypes
import mathutils
from io_xplane2blender import xplane_constants, xplane_helpers
from io_xplane2blender.tests import test_creation_helpers
from io_xplane2blender.xplane_249_converter import (xplane_249_constants,
                                                    xplane_249_dataref_decoder,
                                                    xplane_249_helpers)
from io_xplane2blender.xplane_helpers import logger

# The members, and any collection of dealing with these things,
# they are in the order that 2.49's interface presents them in.
# An arbitrary choice had to be made, this is it.

# True when pressed (we interpret what that means later)
_TexFaceModes = collections.namedtuple(
        "_TexFaceModes",
        ["TEX",
         "TILES",
         "LIGHT",
         "INVISIBLE",
         "DYNAMIC", # This is pressed by default, unlike the others (also, called "Collision" in UI)
         "TWOSIDE",
         "SHADOW",
         "ALPHA",
         "CLIP"
         ]) # type: Tuple[bool, bool, bool, bool, bool, bool, bool, bool, bool]

_TexFaceModes.__repr__ = lambda self: (
    "TEX={}, TILES={}, LIGHT={}, INVISIBLE={}, DYNAMIC={}, TWOSIDE={}, SHADOW={}, ALPHA={}, CLIP={}"
     .format(self.TEX, self.TILES, self.LIGHT, self.INVISIBLE, self.DYNAMIC, self.TWOSIDE, self.SHADOW, self.ALPHA, self.CLIP))

"""
def _get_short_name(self):
    short_name = ""
    for field in self._fields:
        # If we includ DY in every single new material, this is going to get old fast
        if not getattr(self, "DYNAMIC"):
            """
_cmp_dyn = lambda self, field: (field == "DYNAMIC" and not getattr(self, "DYNAMIC")) or (field != "DYNAMIC" and getattr(self, field))
_TexFaceModes.short_name = lambda self: ''.join([field[:2] for field in self._fields if _cmp_dyn(self, field)])

def _get_tf_modes_from_ctypes(obj:bpy.types.Object)->Dict[_TexFaceModes, int]:
    """
    This giant method finds the information from MPoly* and MTexPoly* in DNA_mesh_types.h's Mesh struct,
    and returns a dictionary of pressed states and all polygon indexes that share it

    If the mesh was not unwrapped, this throws a ValueError: NULL pointer access
    """
    assert obj.type == "MESH", obj.name + " is not a MESH type"
    import sys

    def repr_all(self, include_attrs: Optional[Set[str]]=None)->str:
        """
        A general purpose __repr__ for all attributes in a ctypes.Structure,
        or if specified, only a subset of them
        """
        if not include_attrs:
            include_attrs = {}

        s = ("(" + " ".join((name + "={" + name + "}," for name, ctype in self._fields_)) + ")")
        return s.format(**{
            key:getattr(self, key)
            for key, ctype in filter(lambda k: k in include_attrs, self._fields_)})

    class ID(ctypes.Structure):
        pass

        def __repr__(self):
            return repr_all(self, {"name"})

    ID._fields_ = [
                ("next",       ctypes.c_void_p), # void*
                ("prev",       ctypes.c_void_p), # void*
                ("newid",      ctypes.POINTER(ID)), # ID*
                ("lib",        ctypes.c_void_p), # Library*
                ("name",       ctypes.c_char * 66), # char [66]
                ("flag",       ctypes.c_short),
                ("tag",        ctypes.c_short),
                ("pad_s1",     ctypes.c_short),
                ("us",         ctypes.c_int),
                ("icon_id",    ctypes.c_int),
                ("properties", ctypes.c_void_p) # IDProperty *
            ]

    # /* new face structure, replaces MFace, which is now only used for storing tessellations.*/
    class MPoly(ctypes.Structure):
        _fields_ = [
                #/* offset into loop array and number of loops in the face */
                ("loopstart", ctypes.c_int),
                ("totloop",   ctypes.c_int), # /* keep signed since we need to subtract when getting the previous loop */
                ("mat_nr", ctypes.c_short), # We can use this to interact with Mesh.mat, to get a Material *. 0 is no material?
                ("flag", ctypes.c_char),
                ("pad", ctypes.c_char),
            ]

        def __repr__(self):
            return repr_all(self, {"loopstart", "totloop", "mat_nr"})

    class MTexPoly(ctypes.Structure):
        _fields_ = [
                ("tpage", ctypes.c_void_p), # Image *
                ("flag",  ctypes.c_char),
                ("transp", ctypes.c_char), # Also this!
                ("mode",   ctypes.c_short), # THIS IS WHAT IT HAS ALL BEEN ABOUT! RIGHT HERE!
                ("tile",   ctypes.c_short),
                ("pad",    ctypes.c_short)
            ]

        def __repr__(self):
            return repr_all(self, {"transp", "mode"})

    class CustomData(ctypes.Structure):
        _fields_ = [
            ("layers",   ctypes.c_void_p),   # CustomDataLayer *      /* CustomDataLayers, ordered by type */
            ("typemap",  ctypes.c_int * 42), # /* runtime only! - maps types to indices of first layer of that type,
                                             #  * MUST be >= CD_NUMTYPES, but we cant use a define here.
                                             #  * Correct size is ensured in CustomData_update_typemap assert() */
            ("pad_i1",   ctypes.c_int),
            ("totlayer", ctypes.c_int),
            ("maxlayer", ctypes.c_int),    # /* number of layers, size of layers array */
            ("totsize",  ctypes.c_int),    # /* in editmode, total size of all data layers */
            ("pool",     ctypes.c_void_p), # BLI_mempool *     /* (BMesh Only): Memory pool for allocation of blocks */
            ("external", ctypes.c_void_p), # CustomDataExternal * /* external file storing customdata layers */
        ]

    class Mesh(ctypes.Structure):
        _fields_ = [
            ('id', ID),
            ('adt', ctypes.c_void_p), # AnimData *
            ('bb',  ctypes.c_void_p), # BoundBox *
            ('ipo', ctypes.c_void_p), #Ipo * (deprecated)
            ('key', ctypes.c_void_p), #Key *
            ('mat', ctypes.c_void_p), # Material **
            ('mselect',  ctypes.c_void_p), # MSelect *
            ('mpoly',    ctypes.POINTER(MPoly)), #MPoly *
            ('mtpoly',   ctypes.POINTER(MTexPoly)), #MTexPoly *, THIS IS WHAT WE'VE BEEN FIGHTING FOR!!!
            ("mloop",    ctypes.c_void_p), # MLoop *
            ("mloopuv",  ctypes.c_void_p), # MLoopUV *
            ("mloopcol", ctypes.c_void_p), # MLoopCol *

            # /* mface stores the tessellation (triangulation) of the mesh,
            # * real faces are now stored in nface.*/
            ("mface",  ctypes.c_void_p), # MFace *  /* array of mesh object mode faces for tessellation */
            ("mtface", ctypes.c_void_p), # MTFace * /* store tessellation face UV's and texture here */
            ("tface",  ctypes.c_void_p), # TFace *  /* deprecated, use mtface */
            ("mvert",  ctypes.c_void_p), # MVert *  /* array of verts */
            ("medge",  ctypes.c_void_p), # MEdge *  /* array of edges */
            ("dvert",  ctypes.c_void_p), # MDeformVert * /* deformgroup vertices */

            #/* array of colors for the tessellated faces, must be number of tessellated
            # * faces * 4 in length */
            ("mcol",      ctypes.c_void_p), # MCol *
            ("texcomesh", ctypes.c_void_p), # Mesh *

            #/* When the object is available, the preferred access method is: BKE_editmesh_from_object(ob) */
            ("edit_btmesh", ctypes.c_void_p), # BMEditMesh * /* not saved in file! */

            ("vdata", CustomData), # CustomData is CD_MVERT
            ("edata", CustomData), # CustomData is CD_MEDGE
            ("fdata", CustomData), # CustomData is CD_MFACE

        #/* BMESH ONLY */
            ("pdata", CustomData), # CustomData is CD_MPOLY
            ("ldata", CustomData), # CustomData is CD_MLOOP
        #/* END BMESH ONLY */

            ("totvert",   ctypes.c_int), # Applies to length of mvert
            ("totedge",   ctypes.c_int), # Applies to length of medge
            ("totface",   ctypes.c_int), # Applies to length of mface
            ("totselect", ctypes.c_int),

        #/* BMESH ONLY */
            ("totpoly", ctypes.c_int), # Applies to length of mpoly
            ("totloop", ctypes.c_int), # Applies to length of mloop
        #/* END BMESH ONLY */

            #/* the last selected vertex/edge/face are used for the active face however
            # * this means the active face must always be selected, this is to keep track
            # * of the last selected face and is similar to the old active face flag where
            # * the face does not need to be selected, -1 is inactive */
            ("act_face", ctypes.c_int),

            #/* texture space, copied as one block in editobject.c */
            ("loc",  ctypes.c_float * 3),
            ("size", ctypes.c_float * 3),
            ("rot",  ctypes.c_float * 3),

            ("drawflag",   ctypes.c_int),
            ("texflag",    ctypes.c_short),
            ("flag",       ctypes.c_int),
            ("smoothresh", ctypes.c_float),
            ("pad2",       ctypes.c_int),

            #/* customdata flag, for bevel-weight and crease, which are now optional */
            ("cd_flag", ctypes.c_char),
            ("pad",     ctypes.c_char),

            ("subdiv",      ctypes.c_char),
            ("subdivr",     ctypes.c_char),
            ("subsurftype", ctypes.c_char), #/* only kept for ("compat",ctypes.c_backwards), not used anymore */
            ("editflag",    ctypes.c_char),

            ("totcol", ctypes.c_short),

            ("mr", ctypes.c_void_p), # Multires * DNA_DEPRECATED /* deprecated multiresolution modeling data, only keep for loading old files */
        ]

        def __repr__(self):
            return repr_all(self, {"id", "mpoly", "mtpoly", "totpoly"})

    mesh = Mesh.from_address(obj.data.as_pointer())
    poly_c_info = collections.defaultdict(list) # type: Dict[_CMembers, List[int]]
    for idx, (mpoly_current, mtpoly_current) in enumerate(zip(mesh.mpoly[:mesh.totpoly], mesh.mtpoly[:mesh.totpoly])):
        mtpoly_mode = mtpoly_current.mode
        mtpoly_transp = int.from_bytes(mtpoly_current.transp, sys.byteorder)
        print("mtpoly_mode", "mypoly_transp", mtpoly_mode, mtpoly_transp)
        tf_modes = _TexFaceModes(
                        # From DNA_meshdata_types.h, lines 477-495
                        TEX       = bool(mtpoly_mode & (1 << 2)),
                        TILES     = bool(mtpoly_mode & (1 << 7)),
                        LIGHT     = bool(mtpoly_mode & (1 << 4)),
                        INVISIBLE = bool(mtpoly_mode & (1 << 10)),
                        DYNAMIC   = bool(mtpoly_mode & (1 << 0)),
                        TWOSIDE   = bool(mtpoly_mode & (1 << 9)),
                        SHADOW    = bool(mtpoly_mode & (1 << 13)),
                        # From DNA_meshdata_types.h, lines 502-503
                        ALPHA     = bool(mtpoly_transp & (1 << 1)),
                        CLIP      = bool(mtpoly_transp & (1 << 2)),
                    )

        poly_c_info[tf_modes].append(idx)

    return poly_c_info

def _convert_material(scene: bpy.types.Scene,
                      root_object: bpy.types.Object,
                      search_obj: bpy.types.Object,
                      is_cockpit: bool,
                      tf_modes: _TexFaceModes,
                      mat: bpy.types.Material):
    #TODO: During split, what if Object already has a material?
    print("Convertering", mat.name)


    #material_changes = { "blend_v1000":mat.xplane.blend_v1000 }

    new_material = mat.copy()
    new_material.name = mat.name + "_split_" tf_modes.short_name()

    converted_something_at_all = False
    # This section roughly mirrors the order in which 2.49 deals with these face buttons
    #---TEX----------------------------------------------------------
    if tf_modes.TEX:
        if tf_modes.ALPHA:
            if (xplane_249_helpers.find_property_in_parents(search_obj, "ATTR_shadow_blend")[1]):
                new_material.xplane.blend_v1000 = xplane_constants.BLEND_SHADOW
                new_material.xplane.blendRatio = 0.5
                logger.info("{}: Blend Mode='Shadow' and Blend Ratio=0.5".format(mat.name))
                converted_something_at_all = True
            if (xplane_249_helpers.find_property_in_parents(search_obj, "GLOBAL_shadow_blend")[1]):
                new_material.xplane.blend_v1000 = xplane_constants.BLEND_SHADOW
                new_material.xplane.blendRatio = 0.5
                root_object.xplane.layer.export_type = xplane_constants.EXPORT_TYPE_INSTANCED_SCENERY
                logger.info("{}: Blend Mode='Shadow' and Blend Ratio=0.5, now Instanced Scenery".format(mat.name))
                converted_something_at_all = True
        if tf_modes.CLIP:
            if (xplane_249_helpers.find_property_in_parents(search_obj, "ATTR_no_blend")[1]):
                new_material.xplane.blend_v1000 = xplane_constants.BLEND_OFF
                new_material.xplane.blendRatio = 0.5
                logger.info("{}: Blend Mode='Off' and Blend Ratio=0.5".format(mat.name))
                converted_something_at_all = True
            if (xplane_249_helpers.find_property_in_parents(search_obj, "GLOBAL_no_blend")[1]):
                new_material.xplane.blend_v1000 = xplane_constants.BLEND_OFF
                new_material.xplane.blendRatio = 0.5
                root_object.xplane.layer.export_type = xplane_constants.EXPORT_TYPE_INSTANCED_SCENERY
                logger.info("{}: Blend Mode='Off' and Blend Ratio=0.5, now Instanced Scenery".format(mat.name))
                converted_something_at_all = True
    #-----------------------------------------------------------------

    #---TILES/LIGHT---------------------------------------------------
    # Yes! This is not 2.49's code, but it is what 2.49 produces!
    if not is_cockpit and (tf_modes.TILES or tf_modes.LIGHT):
        if xplane_249_helpers.find_property_in_parents(search_obj, "ATTR_draped")[1]:
            new_material.xplane.draped = True
            logger.info("{}: Draped={}".format(mat.name, new_material.xplane.draped))
            converted_something_at_all = True
        else:
            new_material.xplane.poly_os = 2
            logger.info("{}: Poly Offset={}".format(mat.name, new_material.xplane.poly_os))
            converted_something_at_all = True
    #-----------------------------------------------------------------

    #---INVISIBLE-----------------------------------------------------
    if tf_modes.INVISIBLE:
        new_material.xplane.draw = False
        logger.info("{}: Draw Objects With This Material={}".format(mat.name, new_material.xplane.draw))
        converted_something_at_all = True
    #-----------------------------------------------------------------

    #---DYNAMIC-------------------------------------------------------
    if (not tf_modes.INVISIBLE
        and not is_cockpit
        and not tf_modes.DYNAMIC):
        new_material.xplane.solid_camera = True
        logger.info("{}: Solid Camera={}".format(mat.name, new_material.xplane.solid_camera))
        converted_something_at_all = True
    #-----------------------------------------------------------------

    #---TWOSIDE-------------------------------------------------------
    if tf_modes.TWOSIDE:
        logger.warn("{}: Two Sided is deprecated, skipping".format(mat.name))
        pass
    #-----------------------------------------------------------------

    #---SHADOW--------------------------------------------------------
    new_material.xplane.shadow_local = not tf_modes.SHADOW
    if not new_material.xplane.shadow_local:
        logger.info("{}: Cast Shadow (Local)={}".format(mat.name, new_material.xplane.shadow_local))
        converted_something_at_all = True
    #-----------------------------------------------------------------
    return new_material

def convert_materials(scene: bpy.types.Scene, workflow_type: xplane_249_constants.WorkflowType, root_object: bpy.types.Object)->List[bpy.types.Object]:
    if workflow_type == xplane_249_constants.WorkflowType.REGULAR:
        search_objs = scene.objects
    elif workflow_type == xplane_249_constants.WorkflowType.BULK:
        search_objs = [root_object] + xplane_249_helpers.get_all_children_recursive(root_object, scene)
    else:
        assert False, "Unknown workflow type"

    ISCOCKPIT = any(
                [(root_object.xplane.layer.name.lower() + ".obj").endswith(cockpit_suffix)
                 for cockpit_suffix in
                    ["_cockpit.obj",
                     "_cockpit_inn.obj",
                     "_cockpit_out.obj"]
                ]
            ) # type: bool
    ISPANEL = ISCOCKPIT # type: bool
    #scene.render.engine = 'BLENDER_GAME' # Only for testing purposes

    for search_obj in sorted(list(filter(lambda obj: obj.type == "MESH", search_objs)), key=lambda x: x.name):
        """
        This tests that:
            - Every Object ends with a Material, even if it is the 249_default Material
            - Blender's auto generated Materials are removed and replaced with the 249_default
            - Meshs are split according to their TexFace groups (including None or Collision Only), not Materials
            - Meshes are split only as much as needed
            - The relationship between a face and its Material's specularity and Diffuse/Emissive RGB* is preserved,
            even when splitting a mesh
            - Materials and material slots are created as little as possible and never deleted
            - During a split, the minimal amount of Materials are preserved

        * Why? Though deprecated, we shouldn't delete data. We should, in fact copy first instead of create and assign,
        but that is UX, not spec correctness.

        # Spec implications for algorithm
        In more detail this results in:
        """
        print("Converting materials for", search_obj.name)
        # If we end the conversion without any users of this, we'll delete it
        default_material=bpy.data.materials.new(xplane_249_constants.DEFAULT_MATERIAL_NAME)

        """
        def give_face_default(ob: bpy.types.Object):
            for face in search_obj.polygons:
                mat = face.material_index
        """

        # Faces without a 2.49 material are given a default (#1, 2, 10, 12, 21)
        # Auto-generated materials are replaced with Material_249_converter_default (#2, 12)
        # Unused materials aren't deleted (#19)

        # A mesh with >0 faces and 0 TF groups is unsplit
        # A mesh with >0 faces and 1 TF group is unsplit
        # A mesh with >1 faces and 0 TF groups is unsplit
        # A mesh with >1 faces and 1 TF groups is unsplit
        all_tf_modes = _get_tf_modes_from_ctypes(search_obj)
        new_objs = []
        if len(all_tf_modes) > 2:
            # The number of new meshes after a split should match its # of TF groups
            pre_split_obj_count = len(scene.objects) # TODO: Should use scene instead of bpy.data.objects?

            ##############################
            # The heart of this function #
            ##############################
            #--Begining of Operation-----------------------

            i = 0
            def copy_obj(obj):
                nonlocal i
                new_obj = search_obj.copy()
                scene.objects.link(new_obj)
                new_mesh = search_obj.data.copy()

                new_obj.name += ["SHADOW", "TILE", "INVISIBLE"][i]
                i += 1
                new_obj.data = new_mesh
                return new_obj

            modes_to_faces_col = {tf_modes: (faces_idx, copy_obj(search_obj)) for tf_modes, faces_idx in all_tf_modes.items()}
            #print("Deleting " + search_obj.name)
            #bpy.data.meshes.remove(search_obj.data, do_unlink=True)
            #bpy.data.objects.remove(search_obj, do_unlink=True) # What about other work ahead of us to convert?
            #TODO: Better name? Select? Keep_only? trim?
            def remove_faces(face_ids: List[int], obj: bpy.types.Object):
                # Remove faces
                bm = bmesh.new()
                bm.from_mesh(new_obj.data)
                faces_to_keep = [face for face in bm.faces if face.index in face_ids]
                faces_to_remove = [face for face in bm.faces if face.index not in face_ids]
                slot_idxs_to_remove = sorted({face.material_index for face in faces_to_remove}
                                              - {face.material_index for face  in faces_to_keep},
                                              reverse=True)
                print("Faces To Keep:  ", face_ids)
                print("Faces To Remove:", [f.index for f in faces_to_remove])
                bmesh.ops.delete(bm, geom=faces_to_remove, context=5) #AKA DEL_ONLYFACES from bmesh_operator_api.h
                #TODO: TODO: TODO:
                #TODO: First draft doesn't split by materials.
                #TODO: TODO: TODO:
                bm.to_mesh(new_obj.data)
                bm.free()

                # Remove unused or empty material_slots
                scene.objects.active = new_obj
                print("slots to remove (reversed)", (slot_idxs_to_remove))

                #TODO: Are we sure we never remove all slots?
                #TODO: What about null materials,
                # We go through in reverse
                for slot_idx in (slot_idxs_to_remove):
                    #TODO: Make this remove material slots as well, but that
                    scene.objects.active.active_material_index = slot_idx
                    bpy.ops.object.material_slot_remove()


            def convert_material(tf_modes, new_obj):
                current_material = new_obj.material_slots[0].material
                new_material = _convert_material(scene, root_object, new_obj, ISCOCKPIT, tf_modes, current_material)
                new_obj.material_slots[0].material = new_material
                #_convert_material(scene, root_object, new_obj, ISCOCKPIT, tf_modes, mat)
#TW            test_creation_helpers.set_material(new_obj, mat.name)


            for tf_modes, (faceids, new_obj) in modes_to_faces_col.items():
                print("New Obj: ", new_obj.name)
                print("New Mesh:", new_obj.data.name)
                print("Group:" , tf_modes)
                remove_faces(faceids, new_obj)
                convert_material(tf_modes, new_obj)

            #--End of Split Operation----------------------

            intended_count = pre_split_obj_count - 1 + len(all_tf_modes)
            #assert intended_count == len(scene.objects),\
            #        "After split, object count should be TF groups - deleted original ({}), is {}".format(intended_count, len(scene.objects))

            #for new_obj in new_objects:
                #pass
                #test_creation_helpers.set_material(
        else:
            new_objs = [search_obj]

        # The relationship between a face and its material is preserved when there is no split**
        # The relationship between a face and its material is preserved when splitting
        # After split, number of Materials should only include what is needed
        #for new_object in new_objs:
            #if new_object.
#TE
#TI
#LI
#IN            """
              #mat = bpy.data.materials.new(new_obj.name + "_converted")
#DY            _convert_material(scene, root_object, new_obj, ISCOCKPIT, tf_modes, mat)
#TW            test_creation_helpers.set_material(new_obj, mat.name)
              #new_obj.active_material_index = 0
#SH            """

    if not bpy.data.materials[xplane_249_constants.DEFAULT_MATERIAL_NAME].users:
        bpy.data.materials.remove(bpy.data.materials[xplane_249_constants.DEFAULT_MATERIAL_NAME])