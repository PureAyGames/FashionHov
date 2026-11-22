"""FashionHov: pattern making, photo-to-pattern and fit simulation for Blender."""

import bpy

from . import props, photo, trace, cloth, overlay, ui

_classes = photo.classes + trace.classes + cloth.classes + ui.classes


def register():
    props.register()
    for c in _classes:
        bpy.utils.register_class(c)
    overlay.register()


def unregister():
    overlay.unregister()
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
    props.unregister()
