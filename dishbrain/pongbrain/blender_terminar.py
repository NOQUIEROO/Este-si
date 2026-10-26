# PongBrain v3: cierra el modelo, color crema, sombras horneadas (oclusión) y exporta para la web.
import bpy, bmesh, sys, math
from mathutils import Vector
src, dst_blend, dst_gltf = sys.argv[-3], sys.argv[-2], sys.argv[-1]
bpy.ops.wm.open_mainfile(filepath=src, load_ui=False, use_scripts=False)
S = bpy.context.scene; S.frame_set(1)
VL = bpy.context.view_layer
D = bpy.data

# ---------- 1. huecos: la ventana a la placa queda entera bajo la botonera (no asoma entre módulo y pantalla)
w = D.objects['ventana motora']
for v in w.data.vertices:
    if v.co.y > -0.06: v.co.y = -0.0556

# ---------- 2. fuera lo que la web dibuja sola (placa, cultivo, señales) y lo que no se ve
drop = {'dish-placa-plato', 'electrodo bajo la pelota', 'señal viajando', 'fondo'}
for o in list(D.objects):
    base = o.name.split('.')[0]
    if base in drop or base.startswith('neurona') or o.type in ('CURVE',) and o.users_collection and o.users_collection[0].name in ('simulacion', 'mundo neuronas'):
        D.objects.remove(o, do_unlink=True)
for o in D.objects:
    if o.animation_data: o.animation_data_clear()

# ---------- 3. materiales: crema cálido, sin nodos procedurales que no viajan a la web
def principled(m): return m.node_tree.nodes.get('Principled BSDF') if m and m.use_nodes else None
def clean(m):
    nt = m.node_tree; b = principled(m)
    for n in list(nt.nodes):
        if n.type not in ('BSDF_PRINCIPLED', 'OUTPUT_MATERIAL'): nt.nodes.remove(n)
    if b:
        for s in ('Normal', 'Roughness', 'Base Color'):
            for l in list(b.inputs[s].links): nt.links.remove(l)
CREAM = (0.80, 0.70, 0.52)
for m in D.materials:
    if not principled(m): continue
    clean(m); b = principled(m)
    if m.name == 'crema chasis': b.inputs['Base Color'].default_value = (*CREAM, 1); b.inputs['Roughness'].default_value = 0.55
    if m.name == 'serigrafia clara': b.inputs['Base Color'].default_value = (0.86, 0.80, 0.66, 1)
    if m.name == 'paleta blanca': b.inputs['Base Color'].default_value = (0.88, 0.82, 0.68, 1)
    if m.name == 'tomate modulo': b.inputs['Coat Weight'].default_value = 0.0
    if m.name == 'cobalto modulo': b.inputs['Coat Weight'].default_value = 0.0

# ---------- 4. piso de estudio (recibe la sombra horneada del aparato)
FZ = -0.0178
me = D.meshes.new('piso'); bm = bmesh.new()
bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=0.35); bm.to_mesh(me); bm.free()
floor = D.objects.new('piso', me); S.collection.objects.link(floor); floor.location.z = FZ
fm = D.materials.new('piso estudio'); fm.use_nodes = True
principled(fm).inputs['Base Color'].default_value = (0.74, 0.70, 0.62, 1); principled(fm).inputs['Roughness'].default_value = 0.9
me.materials.append(fm)
me.uv_layers.new(name='UVMap')
for loop in me.loops:
    co = me.vertices[loop.vertex_index].co; me.uv_layers[0].data[loop.index].uv = (co.x / 0.7 + 0.5, co.y / 0.7 + 0.5)

# ---------- 5. todo a malla con los modificadores aplicados (booleanos, biseles), para poder hornear
vis = [o for o in D.objects if o.type in ('MESH', 'FONT') and not o.hide_render and not o.hide_get()]
dg = bpy.context.evaluated_depsgraph_get()
for o in vis:
    if o is floor: continue
    ev = o.evaluated_get(dg)
    nm = D.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=dg)
    if o.type == 'FONT':
        mo = D.objects.new(o.name, nm); mo.matrix_world = o.matrix_world.copy()
        for c in o.users_collection: c.objects.link(mo)
        if o.parent: mo.parent = o.parent; mo.matrix_parent_inverse = o.matrix_parent_inverse.copy()
        mats = [s.material for s in o.material_slots]; D.objects.remove(o, do_unlink=True)
        for mt in mats:
            if mt and mt.name not in [x.name for x in nm.materials if x]: nm.materials.append(mt)
    else:
        o.modifiers.clear(); o.data = nm
# los cortadores ya no hacen falta
for o in list(D.objects):
    if o.type == 'MESH' and (o.hide_render or o.hide_get()): D.objects.remove(o, do_unlink=True)

# ---------- 6. horneado de oclusión (sombra de contacto) en las piezas grandes
S.render.engine = 'CYCLES'; S.cycles.device = 'CPU'; S.cycles.samples = 96
S.world.light_settings.distance = 0.012
BAKE = {'chasis': 1024, 'bandeja inferior': 512, 'marco pozo': 1024, 'modulo motor': 1024, 'modulo datos': 1024,
        'tecla SUBE': 512, 'tecla BAJA': 512, 'marco pantalla': 512, 'tirador tapa': 256, 'tirador modulo': 256,
        'marco lcd': 256, 'carcasa tira de luz': 256, 'fondo ranura': 256, 'riel': 256, 'riel.001': 256,
        'riel modulo': 256, 'riel modulo.001': 256, 'corredera condicion': 128, 'paleta neuronas': 128, 'paleta adversaria': 128, 'pelota': 64}
def glTF_out():
    g = D.node_groups.get('glTF Material Output')
    if g: return g
    g = D.node_groups.new('glTF Material Output', 'ShaderNodeTree')
    g.interface.new_socket('Occlusion', in_out='INPUT', socket_type='NodeSocketFloat')
    return g
def bake(o, size, name):
    img = D.images.new('ao ' + name, size, size, alpha=False); img.generated_color = (1, 1, 1, 1)
    # material propio por objeto (el horneado es de esta pieza)
    for i, s in enumerate(o.material_slots):
        if s.material: o.material_slots[i].material = s.material.copy()
    nodes = []
    if not any(s.material for s in o.material_slots): o.data.materials.append(D.materials['crema chasis'].copy())
    for s in o.material_slots:
        if not s.material: continue
        nt = s.material.node_tree; n = nt.nodes.new('ShaderNodeTexImage'); n.image = img; n.name = 'ao'
        for x in nt.nodes: x.select = False
        n.select = True; nt.nodes.active = n; nodes.append((nt, n))
    for x in D.objects: x.select_set(False)
    o.select_set(True); VL.objects.active = o
    bpy.ops.object.bake(type='AO', margin=4, use_clear=True)
    img.pack()
    for nt, n in nodes:
        g = nt.nodes.new('ShaderNodeGroup'); g.node_tree = glTF_out()
        sep = nt.nodes.new('ShaderNodeSeparateColor'); nt.links.new(n.outputs['Color'], sep.inputs['Color'])
        nt.links.new(sep.outputs['Red'], g.inputs['Occlusion'])
    return img
for name, size in BAKE.items():
    o = D.objects.get(name)
    if not o: print('falta', name); continue
    if not o.data.uv_layers:
        for x in D.objects: x.select_set(False)
        o.select_set(True); VL.objects.active = o
        bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.uv.smart_project(angle_limit=math.radians(60), island_margin=0.01)
        bpy.ops.object.mode_set(mode='OBJECT')
    bake(o, size, name); print('horneado', name, flush=True)
# el piso: sombra más amplia
S.world.light_settings.distance = 0.05; S.cycles.samples = 160
bake(floor, 1024, 'piso'); print('horneado piso', flush=True)

bpy.ops.wm.save_as_mainfile(filepath=dst_blend)
for o in D.objects:
    if o.type in ('LIGHT', 'CAMERA'): o.hide_set(True)
bpy.ops.export_scene.gltf(filepath=dst_gltf, export_format='GLTF_EMBEDDED', use_visible=True, export_apply=True,
                          export_lights=False, export_cameras=False, export_yup=True, export_image_format='JPEG', export_jpeg_quality=82)
print('ok')
