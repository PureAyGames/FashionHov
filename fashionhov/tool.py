"""One click-and-drag tool for every feature.

  Dart / Pleat / Hem / Zipper : hover a panel edge, click (and drag) to place.
  Buttons, rivets, snaps...   : click anywhere on a panel, drag to move.
  Existing items              : grab and drag them; X / Delete removes the one
                                under the cursor. Tab cycles the item type.
Panels re-derive instantly; cloth pieces rebuild when you let go.
"""

import math
import bpy
import blf
import gpu
from gpu_extras.batch import batch_for_shader
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Vector

from . import features as ft
from .core import derive as dv
from .core import geometry as geo
from .util import mouse_to_plane, panels, fmt_len

KINDS = [('DART', "Dart", "", 'MOD_TRIANGULATE', 0), ('PLEAT', "Pleat", "", 'MOD_SOLIDIFY', 1),
         ('HEM', "Hem", "", 'MOD_EDGESPLIT', 2), ('ZIPPER', "Zipper", "", 'ALIGN_JUSTIFY', 3),
         ('BUTTON_SHANK', "Jeans Button", "", 'RADIOBUT_ON', 4), ('BUTTON', "Button", "", 'RADIOBUT_OFF', 5),
         ('RIVET', "Rivet", "", 'DOT', 6), ('SNAP', "Snap", "", 'SNAP_FACE_CENTER', 7),
         ('GROMMET', "Grommet", "", 'MESH_CIRCLE', 8), ('BUTTONHOLE', "Buttonhole", "", 'REMOVE', 9)]
EDGE_KINDS = {'DART', 'PLEAT', 'HEM', 'ZIPPER'}
HOVER_PX = 16


class FHToolSettings(bpy.types.PropertyGroup):
    kind: bpy.props.EnumProperty(name="Add", items=KINDS)
    dart_width: bpy.props.FloatProperty(name="Dart Width", default=0.025, min=0.002, max=0.2,
                                        subtype='DISTANCE', unit='LENGTH')
    dart_length: bpy.props.FloatProperty(name="Dart Length", default=0.10, min=0.01, max=0.6,
                                         subtype='DISTANCE', unit='LENGTH')
    pleat_depth: bpy.props.FloatProperty(name="Pleat Depth", default=0.02, min=0.003, max=0.15,
                                         subtype='DISTANCE', unit='LENGTH')
    pleat_kind: bpy.props.EnumProperty(name="Pleat Type", items=[('KNIFE', "Knife", ""), ('BOX', "Box", ""),
                                                                  ('INVERTED', "Inverted", "")])
    hem_width: bpy.props.FloatProperty(name="Hem Width", default=0.02, min=0.003, max=0.15,
                                       subtype='DISTANCE', unit='LENGTH')
    zip_style: bpy.props.EnumProperty(name="Zip Style", items=ft.ZIP_STYLES)
    finish: bpy.props.EnumProperty(name="Finish", items=ft.FINISHES)


# ---------- hit testing ----------

def _px(context, xy, z=0.0):
    return location_3d_to_region_2d(context.region, context.region_data, Vector((xy[0], xy[1], z)))


def _seg_px_dist(m, a, b):
    if a is None or b is None:
        return 1e9, 0.0
    ab = b - a
    L2 = ab.length_squared
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, (m - a).dot(ab) / L2))
    return (m - (a + ab * t)).length, t


def hover_edge(context, mouse, only=None):
    """Nearest panel edge under the mouse: (panel, va, vb, t_on_base_edge, world_xy) or None."""
    best = None
    for panel in panels(context.scene):
        if panel.get("fh_graded_of") or not panel.visible_get() or (only and panel != only):
            continue
        d = ft.get_derived(panel)
        if not d:
            continue
        z = panel.matrix_world.translation.z
        sew = d.sew
        n = len(sew)
        for i in range(n):
            if i in d.jumps:
                continue
            a, b = sew[i].xy, sew[(i + 1) % n].xy
            dist, t = _seg_px_dist(mouse, _px(context, a, z), _px(context, b, z))
            if dist < HOVER_PX and (best is None or dist < best[0]):
                best = (dist, panel, i, dv.lerp(a, b, t))
    if not best:
        return None
    _, panel, i, xy = best
    d = ft.get_derived(panel)
    base = ft.base_outline(panel)
    ids = [v for v, _ in base]
    va = d.edge_of(i)
    vb = ids[(ids.index(va) + 1) % len(ids)]
    a, b = base[ids.index(va)][1], base[ids.index(vb)][1]
    q = d.unmap_point(xy)
    ab = (b[0] - a[0], b[1] - a[1])
    L2 = ab[0] ** 2 + ab[1] ** 2
    t = 0.0 if L2 == 0 else max(0.02, min(0.98, ((q[0] - a[0]) * ab[0] + (q[1] - a[1]) * ab[1]) / L2))
    return panel, va, vb, t, xy


def edge_marker(panel, va, vb, t):
    base = ft.base_outline(panel)
    ids = [v for v, _ in base]
    if va not in ids or vb not in ids:
        return None
    a, b = base[ids.index(va)][1], base[ids.index(vb)][1]
    d = ft.get_derived(panel)
    return d.map_point(dv.lerp(a, b, t)) if d else dv.lerp(a, b, t)


def items_world(panel):
    """[(kind, item, world_xy)] for everything grabbable on a panel."""
    f = panel.fh_features
    out = []
    for x in f.darts:
        p = edge_marker(panel, x.va, x.vb, x.t)
        if p:
            out.append(('DART', x, p))
    for x in f.pleats:
        p = edge_marker(panel, x.va, x.vb, x.t)
        if p:
            out.append(('PLEAT', x, p))
    d = ft.get_derived(panel)
    for x in f.hems:
        pts, _ = d.chain(x.va, x.vb) if d else ([], set())
        if len(pts) >= 2:
            out.append(('HEM', x, dv.point_at_arc(pts, dv.polyline_len(pts) / 2)[0]))
    for x in f.hardware:
        if x.kind == 'ZIPPER':
            path = ft.zipper_path(panel, x)
            if path:
                out.append(('ZIPPER', x, path[len(path) // 2]))
        else:
            out.append((x.kind, x, ft.hardware_world(panel, x)))
    return out


def hover_item(context, mouse):
    best = None
    for panel in panels(context.scene):
        if panel.get("fh_graded_of") or not panel.visible_get():
            continue
        z = panel.matrix_world.translation.z
        for kind, item, xy in items_world(panel):
            p = _px(context, xy, z)
            if p is None:
                continue
            dist = (p - mouse).length
            if dist < HOVER_PX and (best is None or dist < best[0]):
                best = (dist, panel, kind, item)
    return best[1:] if best else None


def panel_under(context, event):
    for panel in panels(context.scene):
        if panel.get("fh_graded_of") or not panel.visible_get():
            continue
        p = mouse_to_plane(context, event, panel.matrix_world.translation.z)
        d = ft.get_derived(panel)
        if p and d and geo.point_in_polygon((p.x, p.y), d.cut):
            return panel, (p.x, p.y)
    return None


def remove_item(panel, kind, item):
    f = panel.fh_features
    for coll in (f.darts, f.pleats, f.hems, f.hardware):
        for i, x in enumerate(coll):
            if x == item:
                coll.remove(i)
                ft.request_rebuild(panel)
                return True
    return False


# ---------- the tool ----------

class FH_OT_tool(bpy.types.Operator):
    """Click and drag darts, pleats, hems, zippers, buttons, rivets... onto your panels"""
    bl_idname = "fashionhov.tool"
    bl_label = "Add Details"
    bl_options = {'REGISTER', 'UNDO'}

    kind: bpy.props.EnumProperty(items=KINDS, options={'SKIP_SAVE'}, default='DART')

    @classmethod
    def poll(cls, context):
        return context.area and context.area.type == 'VIEW_3D' and context.mode == 'OBJECT'

    def invoke(self, context, event):
        context.scene.fh_tool.kind = self.kind
        self.mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        self.drag = None          # (panel, kind, item)
        self.hover = None
        self.touched = set()
        self._h = bpy.types.SpaceView3D.draw_handler_add(self._draw, (context,), 'WINDOW', 'POST_PIXEL')
        context.window_manager.modal_handler_add(self)
        self._status(context)
        return {'RUNNING_MODAL'}

    def _status(self, context):
        k = dict((a, b) for a, b, *_ in KINDS)[context.scene.fh_tool.kind]
        where = "click an edge" if context.scene.fh_tool.kind in EDGE_KINDS else "click on a panel"
        context.workspace.status_text_set(
            f"Adding: {k} ({where})  •  drag items to move  •  X: delete  •  Tab: next type  •  "
            "Middle mouse / wheel: navigate  •  Enter / Esc / Right-click: done")

    def _end(self, context):
        bpy.types.SpaceView3D.draw_handler_remove(self._h, 'WINDOW')
        context.workspace.status_text_set(None)
        for p in self.touched:
            o = bpy.data.objects.get(p)
            if o:
                ft.request_rebuild(o)
        context.area.tag_redraw()

    def modal(self, context, event):
        context.area.tag_redraw()
        ts = context.scene.fh_tool
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'TRACKPADPAN', 'TRACKPADZOOM'}:
            return {'PASS_THROUGH'}
        self.mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        if event.type == 'MOUSEMOVE':
            if self.drag:
                self._drag_to(context, event)
            else:
                self.hover = hover_item(context, self.mouse)
        elif event.type == 'TAB' and event.value == 'PRESS':
            ids = [k[0] for k in KINDS]
            ts.kind = ids[(ids.index(ts.kind) + (-1 if event.shift else 1)) % len(ids)]
            self._status(context)
        elif event.type in {'X', 'DEL'} and event.value == 'PRESS':
            h = hover_item(context, self.mouse)
            if h:
                remove_item(*h)
                self.touched.add(h[0].name)
                self.hover = None
        elif event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            h = hover_item(context, self.mouse)
            if h:
                self.drag = h
            else:
                self._add(context, event)
        elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            if self.drag:
                ft.request_rebuild(self.drag[0])
                self.touched.add(self.drag[0].name)
            self.drag = None
        elif event.type in {'RET', 'NUMPAD_ENTER', 'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            self._end(context)
            return {'FINISHED'}
        return {'RUNNING_MODAL'}

    def _add(self, context, event):
        ts = context.scene.fh_tool
        kind = ts.kind
        if kind in EDGE_KINDS:
            e = hover_edge(context, self.mouse)
            if not e:
                return
            panel, va, vb, t, xy = e
            f = panel.fh_features
            if kind == 'DART':
                x = f.darts.add()
                x.id, x.va, x.vb, x.t = ft.new_id(panel), va, vb, t
                x.width, x.length = ts.dart_width, ts.dart_length
            elif kind == 'PLEAT':
                x = f.pleats.add()
                x.id, x.va, x.vb, x.t = ft.new_id(panel), va, vb, t
                x.depth, x.kind = ts.pleat_depth, ts.pleat_kind
            elif kind == 'HEM':
                for i, h in enumerate(f.hems):
                    if h.va == va:
                        f.hems.remove(i)
                        ft.request_rebuild(panel)
                        return
                x = f.hems.add()
                x.va, x.vb, x.width = va, vb, ts.hem_width
                self._merge_hems(panel)
                ft.request_rebuild(panel)
                return
            else:  # ZIPPER: starts here; drag sets the length
                x = f.hardware.add()
                x.id, x.kind, x.va, x.vb = ft.new_id(panel), 'ZIPPER', va, vb
                base = ft.base_outline(panel)
                ids = [v for v, _ in base]
                a, b = base[ids.index(va)][1], base[ids.index(vb)][1]
                x.start = math.dist(a, b) * t
                x.style, x.finish = ts.zip_style, ts.finish
                self._extend_zip_chain(panel, x)
            self.drag = (panel, kind, x)
            self.touched.add(panel.name)
            ft.invalidate(panel)
        else:
            hit = panel_under(context, event)
            if not hit:
                return
            panel, xy = hit
            x = panel.fh_features.hardware.add()
            x.id, x.kind = ft.new_id(panel), kind
            x.size = ft.HW_SIZE[kind]
            x.finish = ts.finish
            ft.set_hardware_world(panel, x, xy)
            self.drag = (panel, kind, x)
            self.touched.add(panel.name)

    def _merge_hems(self, panel):
        """Neighbouring hemmed edges become one hem (so its topstitch is continuous)."""
        f = panel.fh_features
        changed = True
        while changed:
            changed = False
            for i, a in enumerate(f.hems):
                for j, b in enumerate(f.hems):
                    if i != j and a.vb == b.va and abs(a.width - b.width) < 1e-6 and a.fold == b.fold:
                        a.vb = b.vb
                        f.hems.remove(j)
                        changed = True
                        break
                if changed:
                    break

    def _extend_zip_chain(self, panel, z):
        """Let a zipper run over several edges: extend vb until the chain is long enough."""
        base = ft.base_outline(panel)
        ids = [v for v, _ in base]
        i = ids.index(z.va)
        total = 0.0
        k = i
        while True:
            a, b = base[k][1], base[(k + 1) % len(base)][1]
            total += math.dist(a, b)
            k = (k + 1) % len(base)
            if total >= z.start + z.length or k == i:
                break
        z.vb = ids[k]

    def _drag_to(self, context, event):
        panel, kind, item = self.drag
        if kind in ('DART', 'PLEAT'):
            e = hover_edge(context, self.mouse, only=panel)
            if e:
                _, item.va, item.vb, item.t, _ = e
        elif kind == 'ZIPPER':
            p = mouse_to_plane(context, event, panel.matrix_world.translation.z)
            if p is None:
                return
            d = ft.get_derived(panel)
            pts, _ = d.chain(item.va, item.vb)
            if len(pts) < 2:
                return
            # arc position of the mouse projected on the chain
            best, acc = None, 0.0
            for a, b in zip(pts, pts[1:]):
                L = math.dist(a, b)
                dist, t = _seg_px_dist(Vector((p.x, p.y)), Vector(a), Vector(b))
                if best is None or dist < best[0]:
                    best = (dist, acc + t * L)
                acc += L
            item.length = max(0.03, best[1] - item.start)
            self._extend_zip_chain(panel, item)
        elif kind in ('HEM',):
            return
        else:
            p = mouse_to_plane(context, event, panel.matrix_world.translation.z)
            if p:
                ft.set_hardware_world(panel, item, (p.x, p.y))
        ft.invalidate(panel)
        self.touched.add(panel.name)

    def _draw(self, context):
        ts = context.scene.fh_tool
        sh = gpu.shader.from_builtin('UNIFORM_COLOR')
        gpu.state.blend_set('ALPHA')
        label = None
        if self.hover and not self.drag:
            panel, kind, item = self.hover
            label = f"{kind.replace('_', ' ').title()}: drag to move, X to delete"
        elif not self.drag and ts.kind in EDGE_KINDS:
            e = hover_edge(context, self.mouse)
            if e:
                panel, va, vb, t, xy = e
                p = _px(context, xy, panel.matrix_world.translation.z)
                if p:
                    sh.uniform_float("color", (1, 0.6, 0.1, 1))
                    gpu.state.point_size_set(12)
                    batch_for_shader(sh, 'POINTS', {"pos": [tuple(p)]}).draw(sh)
                    gpu.state.point_size_set(1)
                label = {"DART": "Click: add dart", "PLEAT": "Click: add pleat", "HEM": "Click: hem this edge",
                         "ZIPPER": "Click and drag along the edge: zipper"}[ts.kind]
        elif self.drag and self.drag[1] == 'ZIPPER':
            label = f"Zip length {fmt_len(context, self.drag[2].length)}"
        elif not self.drag:
            label = f"Click on a panel: add {ts.kind.replace('_', ' ').lower()}"
        if label:
            blf.size(0, 13)
            blf.color(0, 1, 1, 1, 1)
            blf.position(0, self.mouse.x + 16, self.mouse.y - 18, 0)
            blf.draw(0, label)
        gpu.state.blend_set('NONE')


class FH_OT_feature_remove(bpy.types.Operator):
    """Remove this item"""
    bl_idname = "fashionhov.feature_remove"
    bl_label = "Remove"
    bl_options = {'REGISTER', 'UNDO'}

    coll: bpy.props.StringProperty()
    index: bpy.props.IntProperty()

    def execute(self, context):
        panel = context.active_object
        getattr(panel.fh_features, self.coll).remove(self.index)
        ft.request_rebuild(panel)
        return {'FINISHED'}


class FH_OT_hem_selected(bpy.types.Operator):
    """Hem the edges selected in Edit Mode"""
    bl_idname = "fashionhov.hem_selected"
    bl_label = "Hem Selected Edges"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        from .sewing import runs_in_panel
        n = 0
        for obj in context.objects_in_mode:
            if not obj.get("fh_panel"):
                continue
            for a, b in runs_in_panel(obj):
                if a == b:
                    continue
                h = obj.fh_features.hems.add()
                h.va, h.vb, h.width = a, b, context.scene.fh_tool.hem_width
                ft.request_rebuild(obj)
                n += 1
        self.report({'INFO'}, f"Added {n} hem(s)")
        return {'FINISHED'}


classes = (FH_OT_tool, FH_OT_feature_remove, FH_OT_hem_selected)


def register():
    bpy.utils.register_class(FHToolSettings)
    bpy.types.Scene.fh_tool = bpy.props.PointerProperty(type=FHToolSettings)


def unregister():
    del bpy.types.Scene.fh_tool
    bpy.utils.unregister_class(FHToolSettings)
