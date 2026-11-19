# PyInstaller spec: builds dist/PlayTranslate/PlayTranslate.exe (one folder, starts fast,
# fewer antivirus false alarms than a single-file exe).
# Build from the repository root:  pyinstaller packaging/playtranslate.spec --noconfirm
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

root = Path(SPECPATH).parent
datas = [(str(root / "playtranslate" / "server" / "static"), "playtranslate/server/static")]
datas += collect_data_files("rapidocr")  # config.yaml + the ONNX models
binaries = collect_dynamic_libs("onnxruntime")
hidden = collect_submodules("winrt") + collect_submodules("rapidocr")

a = Analysis(
    [str(root / "playtranslate" / "__main__.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=["tkinter", "matplotlib", "PySide6.QtWebEngineCore", "PySide6.Qt3DCore", "argostranslate"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PlayTranslate",
    console=False,
    icon=str(root / "packaging" / "icon.ico"),
    version=str(root / "packaging" / "version_info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="PlayTranslate")
