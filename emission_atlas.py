bl_info = {
    "name": "Emission Atlas Generator ",
    "blender": (4, 1, 1),
    "category": "Material",
    "author": "Bryce Bible",
    "version": (1, 3),
    "description": "Converts simple emission materials into a texture atlas, with revert/unpack functionality.",
}

import bpy
import bmesh

# -----------------------------------------------------------------------------
# GLOBAL STORAGE for "Revert" only (original materials).
# Key = object name, Value = list of the original material references.
# -----------------------------------------------------------------------------
ORIGINAL_MATERIALS = {}

# -----------------------------------------------------------------------------
# UTILITY FUNCTIONS
# -----------------------------------------------------------------------------
def get_simple_emission_materials():
    """
    Identify materials that have a single Emission node
    with a constant color (RGB).
    """
    emission_materials = {}
    for mat in bpy.data.materials:
        if mat.use_nodes:
            for node in mat.node_tree.nodes:
                if node.type == 'EMISSION':
                    color = node.inputs["Color"].default_value[:3]
                    emission_materials[mat.name] = color
                    break
    return emission_materials


def create_texture_atlas(material_colors, atlas_width=1024, atlas_height=256):
    """
    Generate a single-row texture atlas from the given material_colors dict:
      - Each material gets a column in the texture.
      - atlas_width x atlas_height image.
      - Store the number of columns in a custom property on the image for "unpack."
    """
    mat_list = list(material_colors.keys())
    mat_count = len(mat_list)
    if mat_count == 0:
        return None
    
    # Size of each column
    column_width = atlas_width // mat_count
    
    # Create a new blank image
    img = bpy.data.images.new("Emission_Atlas", width=atlas_width, height=atlas_height)
    
    # Prepare a pixel buffer [R, G, B, A, ...]
    pixels = [0.0] * (atlas_width * atlas_height * 4)
    
    for i, mat_name in enumerate(mat_list):
        color = material_colors[mat_name]
        # The start (in pixels) of this material's column
        x_start = i * column_width
        
        # Fill that column with the material color
        for x in range(column_width):
            for y in range(atlas_height):
                px_index = ((y * atlas_width) + (x_start + x)) * 4
                pixels[px_index + 0] = color[0]  # R
                pixels[px_index + 1] = color[1]  # G
                pixels[px_index + 2] = color[2]  # B
                pixels[px_index + 3] = 1.0       # A
    
    img.pixels = pixels
    img.filepath_raw = "//Emission_Atlas.png"
    img.file_format = 'PNG'
    img.save()
    
    # Store the number of columns as metadata so we can "unpack" later
    img["atlas_columns"] = mat_count
    
    return img


def create_atlas_material(texture):
    """
    Create a new material that uses the given image as an Emission texture.
    """
    mat = bpy.data.materials.new(name="AtlasMaterial")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    # Remove default nodes
    for node in nodes:
        nodes.remove(node)

    # Create texture node
    tex_node = nodes.new(type="ShaderNodeTexImage")
    tex_node.image = texture
    tex_node.location = (-300, 0)

    # Create emission node
    emission = nodes.new(type="ShaderNodeEmission")
    emission.location = (0, 0)
    links.new(tex_node.outputs["Color"], emission.inputs["Color"])

    # Create output
    output = nodes.new(type="ShaderNodeOutputMaterial")
    output.location = (300, 0)
    links.new(emission.outputs["Emission"], output.inputs["Surface"])

    return mat


def remap_uvs(obj, mat_index_map, atlas_width=1024, atlas_height=256):
    """
    Update UVs so that all faces using material i sample the i-th column in the atlas.
    - For single-color usage, we just pick the center of that column in U, and 0.5 in V.
    """
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)

    uv_layer = bm.loops.layers.uv.verify()

    mat_count = len(mat_index_map)
    if mat_count == 0:
        return
    
    column_width = atlas_width / mat_count  # in pixels
    for face in bm.faces:
        if face.material_index < len(obj.material_slots):
            mat = obj.material_slots[face.material_index].material
            if mat and mat.name in mat_index_map:
                i = mat_index_map[mat.name]
                
                # Convert i to UV range. For single color, pick the column center:
                u_min = (i * column_width) / atlas_width
                u_max = ((i + 1) * column_width) / atlas_width
                u_center = (u_min + u_max) * 0.5
                v_center = 0.5  # halfway up the texture

                # Assign all loops in this face the same UV
                for loop in face.loops:
                    loop[uv_layer].uv = (u_center, v_center)
    
    bm.to_mesh(mesh)
    bm.free()


def create_single_color_emission_material(name, color):
    """
    Create a brand-new material with a single Emission node set to 'color'.
    """
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    
    emission_node = nodes.new("ShaderNodeEmission")
    emission_node.inputs["Color"].default_value = (color[0], color[1], color[2], 1.0)
    emission_node.inputs["Strength"].default_value = 1.0
    
    output_node = nodes.new("ShaderNodeOutputMaterial")
    links.new(emission_node.outputs["Emission"], output_node.inputs["Surface"])
    
    return mat


# -----------------------------------------------------------------------------
# OPERATORS
# -----------------------------------------------------------------------------
class ConvertToEmissionAtlas(bpy.types.Operator):
    """
    Converts all simple emission materials in the selected objects
    into a single texture atlas material, replacing the original materials.
    """
    bl_idname = "object.convert_to_emission_atlas"
    bl_label = "Create Atlas"
    bl_description = "Converts simple emission materials to a single atlas and reassigns them."
    
    def execute(self, context):
        # 1. Gather all simple emission materials
        materials = get_simple_emission_materials()
        if not materials:
            self.report({'WARNING'}, "No simple emission materials found.")
            return {'CANCELLED'}
        
        # 2. Create a dictionary that maps each material to a unique index
        mat_index_map = {}
        for idx, mat_name in enumerate(materials.keys()):
            mat_index_map[mat_name] = idx
        
        # 3. Create the atlas texture
        atlas = create_texture_atlas(materials)
        if not atlas:
            self.report({'WARNING'}, "Failed to create atlas.")
            return {'CANCELLED'}
        
        # 4. Create a single new material using the atlas
        atlas_mat = create_atlas_material(atlas)
        
        # 5. Store original materials for revert
        global ORIGINAL_MATERIALS
        ORIGINAL_MATERIALS.clear()  # Reset each time we run
        
        # 6. For each selected mesh object, store old mats, then remap UVs, assign atlas
        for obj in context.selected_objects:
            if obj.type == "MESH":
                # Store original materials
                ORIGINAL_MATERIALS[obj.name] = [ms.material for ms in obj.material_slots]
                
                # Update UVs
                remap_uvs(obj, mat_index_map, atlas_width=atlas.size[0], atlas_height=atlas.size[1])
                
                # Replace all materials with the new atlas
                obj.data.materials.clear()
                obj.data.materials.append(atlas_mat)
        
        self.report({'INFO'}, "Emission Texture Atlas Generated Successfully!")
        return {'FINISHED'}


class RevertEmissionAtlas(bpy.types.Operator):
    """
    Revert selected objects to their original materials (only if still in memory).
    """
    bl_idname = "object.revert_emission_atlas"
    bl_label = "Revert Atlas"
    bl_description = "Reverts selected objects to their original materials if possible."
    
    def execute(self, context):
        global ORIGINAL_MATERIALS
        
        if not ORIGINAL_MATERIALS:
            self.report({'WARNING'}, "No stored original materials to revert.")
            return {'CANCELLED'}
        
        for obj in context.selected_objects:
            if obj.name in ORIGINAL_MATERIALS:
                mat_list = ORIGINAL_MATERIALS[obj.name]
                if obj.type == 'MESH':
                    # Clear current materials
                    obj.data.materials.clear()
                    # Re-add the originals (if they still exist)
                    for mat in mat_list:
                        if mat and mat.name in bpy.data.materials:
                            obj.data.materials.append(bpy.data.materials[mat.name])
        
        self.report({'INFO'}, "Reverted to original materials.")
        return {'FINISHED'}


class UnpackEmissionAtlas(bpy.types.Operator):
    """
    Reads the existing atlas image, detects how many columns (colors) it has,
    creates new single-color emission materials, and reassigns faces accordingly.
    This does NOT require the original materials to be stored.
    """
    bl_idname = "object.unpack_emission_atlas"
    bl_label = "Unpack Atlas"
    bl_description = "Creates new single-color materials from the atlas and reassigns them to faces."
    
    def execute(self, context):
        # We'll do this for each selected mesh object that has our "AtlasMaterial" or an atlas image.
        # 1. Identify the atlas image from the first material slot that references it.
        #    We'll assume all selected objects share the same atlas for simplicity.
        
        # A dictionary to store "which atlas image" -> "list of new materials"
        # so we don't keep re-creating them if multiple objects share the same atlas.
        created_material_sets = {}
        
        for obj in context.selected_objects:
            if obj.type != "MESH":
                continue
            
            # Try to find the atlas image in the object's material slots
            atlas_image = None
            atlas_mat_slot_idx = None
            for slot_idx, slot in enumerate(obj.material_slots):
                mat = slot.material
                if mat and mat.use_nodes:
                    for node in mat.node_tree.nodes:
                        if node.type == 'TEX_IMAGE' and node.image and "atlas_columns" in node.image:
                            atlas_image = node.image
                            atlas_mat_slot_idx = slot_idx
                            break
                if atlas_image:
                    break
            
            if not atlas_image:
                # This object doesn't seem to have the atlas, skip
                continue
            
            atlas_width = atlas_image.size[0]
            atlas_height = atlas_image.size[1]
            columns = int(atlas_image.get("atlas_columns", 1))
            if columns < 1:
                columns = 1
            
            # 2. If we haven't already created new materials for this atlas, do so now
            if atlas_image.name not in created_material_sets:
                # Sample the pixel data from the image
                pixels = list(atlas_image.pixels)
                column_width = atlas_width // columns
                
                new_mats = []
                for i in range(columns):
                    center_x = int((i + 0.5) * column_width)
                    # Just sample halfway up the image
                    center_y = atlas_height // 2
                    
                    px_index = ((center_y * atlas_width) + center_x) * 4
                    r = pixels[px_index + 0]
                    g = pixels[px_index + 1]
                    b = pixels[px_index + 2]
                    
                    # Create a new single-color emission material
                    mat_name = f"UnpackedAtlasColor_{i}"
                    # If we already made a mat with this name, just reuse it
                    if mat_name in bpy.data.materials:
                        new_mat = bpy.data.materials[mat_name]
                    else:
                        new_mat = create_single_color_emission_material(mat_name, (r, g, b))
                    
                    new_mats.append(new_mat)
                
                created_material_sets[atlas_image.name] = new_mats
            
            # 3. Assign the newly created single-color materials to this object
            new_materials = created_material_sets[atlas_image.name]
            # Clear existing material slots
            obj.data.materials.clear()
            for nm in new_materials:
                obj.data.materials.append(nm)
            
            # 4. BMesh pass: for each face, figure out which column it's sampling
            bm = bmesh.new()
            bm.from_mesh(obj.data)
            uv_layer = bm.loops.layers.uv.verify()
            
            column_width_float = float(atlas_width) / columns
            
            for face in bm.faces:
                if len(face.loops) == 0:
                    continue
                
                # We'll just look at the first loop's UV
                uv = face.loops[0][uv_layer].uv
                # Convert to pixel coordinates
                x_pix = uv.x * atlas_width
                # clamp
                if x_pix < 0:
                    x_pix = 0
                elif x_pix >= atlas_width:
                    x_pix = atlas_width - 1
                
                # figure out which column
                col_index = int(x_pix // column_width_float)
                if col_index < 0:
                    col_index = 0
                elif col_index >= columns:
                    col_index = columns - 1
                
                face.material_index = col_index
            
            bm.to_mesh(obj.data)
            bm.free()
        
        self.report({'INFO'}, "Unpacked atlas into new single-color materials.")
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# PANEL IN THE N-MENU
# -----------------------------------------------------------------------------
class VIEW3D_PT_EmissionAtlas(bpy.types.Panel):
    """Creates a Panel in the 3D View N-panel for Emission Atlas tools."""
    bl_label = "Emission Atlas"
    bl_idname = "VIEW3D_PT_emission_atlas"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Emission Atlas"  # A new tab in the N-panel
    
    def draw(self, context):
        layout = self.layout
        layout.label(text="Atlas Creation & Revert", icon='MATERIAL')
        layout.operator("object.convert_to_emission_atlas", text="Create Atlas")
        layout.operator("object.revert_emission_atlas", text="Revert Atlas")
        
        layout.separator()
        layout.label(text="Unpack Tools", icon='NODETREE')
        layout.operator("object.unpack_emission_atlas", text="Unpack Atlas")


# -----------------------------------------------------------------------------
# REGISTRATION
# -----------------------------------------------------------------------------
classes = (
    ConvertToEmissionAtlas,
    RevertEmissionAtlas,
    UnpackEmissionAtlas,
    VIEW3D_PT_EmissionAtlas,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

# If running directly from the Scripting tab, this ensures no multiple registrations:
if __name__ == "__main__":
    try:
        unregister()
    except:
        pass
    register()
