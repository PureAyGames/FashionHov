"""Build the installable FashionHov extension: dist/fashionhov-<version>.zip

    python build.py

The zip installs in Blender 5.x by dragging it into the Blender window
(or Edit > Preferences > Get Extensions > Install from Disk).
"""
import pathlib
import re
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent
SRC = ROOT / "fashionhov"
version = re.search(r'^version = "([^"]+)"', (SRC / "blender_manifest.toml").read_text(), re.M).group(1)
out = ROOT / "dist" / f"fashionhov-{version}.zip"
out.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(SRC.rglob("*")):
        if f.is_file() and "__pycache__" not in f.parts and f.suffix != ".pyc":
            z.write(f, f.relative_to(SRC).as_posix())     # manifest at the zip root
print(out)
