"""FashionHov: pattern making, photo-to-pattern and fit simulation for Blender."""

import bpy

from . import (fabric, props, photo, trace, cloth, drape, avatar, sewing, arrange,
               fitmap, grading, features, pockets, tool, details, export, overlay, ui)

_classes = (photo.classes + trace.classes + cloth.classes + fabric.classes + drape.classes
            + avatar.classes + sewing.classes + arrange.classes + fitmap.classes
            + grading.classes + pockets.classes + tool.classes + details.classes + export.classes + ui.classes)
_modules = (fabric, props, avatar, sewing, arrange, grading, features, tool, details)


def register():
    for m in _modules:
        m.register()
    for c in _classes:
        bpy.utils.register_class(c)
    overlay.register()


def unregister():
    overlay.unregister()
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
    for m in reversed(_modules):
        m.unregister()
