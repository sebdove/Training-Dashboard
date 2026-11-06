# PyInstaller build file for the downloadable app.
# Build with:  pyinstaller t100.spec   (output in dist/)
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [("web", "web"), ("data/race.example.json", "data"), ("data/phases.example.json", "data")]
binaries = []
hiddenimports = collect_submodules("garminconnect")
for pkg in ("curl_cffi", "ua_generator"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

a = Analysis(
    ["server/launcher.py"],
    pathex=["server"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["app", "version"],
    excludes=["tkinter", "matplotlib", "pandas", "IPython"],
)
pyz = PYZ(a.pure)
icon = "web/icons/icon.ico" if sys.platform == "win32" else ("web/icons/icon.icns" if sys.platform == "darwin" else None)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="Training-Dashboard",
    console=True,  # the window shows the Garmin sign-in prompt and stays open while the dashboard runs
    icon=icon,
    upx=False,
)
