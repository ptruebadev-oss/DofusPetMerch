# PyInstaller spec: build with  .venv\Scripts\pyinstaller DofusPetMerch.spec --noconfirm
# Output: dist\DofusPetMerch.exe — a single self-contained file (no _internal folder needed).
# On each start it unpacks itself to a temporary folder, so it opens a bit slower than onedir.
from PyInstaller.utils.hooks import collect_submodules

hidden = collect_submodules("winrt")

a = Analysis(
    ["run.py"],
    pathex=["src"],
    datas=[("assets/icon.ico", "assets"), ("src/dofuspetmerch/sheets/apps_script.js", "dofuspetmerch/sheets")],
    hiddenimports=hidden,
    excludes=["matplotlib", "PyQt5", "PySide6", "IPython"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DofusPetMerch",
    console=False,
    icon="assets/icon.ico",
    runtime_tmpdir=None,
)
