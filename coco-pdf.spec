# PyInstaller spec: one-folder build (starts faster than one-file), packaged afterwards by Inno Setup.
# Build: pyinstaller coco-pdf.spec --noconfirm

# Pulled in by optional imports or Qt plugins but never used by the app.
UNUSED = ("opengl32sw.dll", "Qt6Quick", "Qt6Qml", "Qt6Pdf", "Qt6Network", "Qt6OpenGL", "qpdf.dll", "Qt6VirtualKeyboard")

a = Analysis(
    ["coco_pdf/__main__.py"],
    datas=[("assets/coco-pdf.ico", "assets"), ("assets/logo.png", "assets")],
    excludes=["tkinter", "numpy", "PIL", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick"],
)
a.binaries = [b for b in a.binaries if not any(name in b[0] for name in UNUSED)]
a.datas = [d for d in a.datas if "translations" not in d[0] or d[0].endswith(("_fr.qm", "_en.qm"))]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CocoPDF",
    icon="assets/coco-pdf.ico",
    console=False,
    version="version_info.txt",
)
coll = COLLECT(exe, a.binaries, a.datas, name="CocoPDF")
