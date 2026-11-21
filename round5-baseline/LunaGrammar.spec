# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import ssl

root = Path(SPECPATH)
data = [(str(root / "assets"), "assets")]
# Some Windows Python distributions patch ssl.py to load a certificate
# distrust list alongside the module. Carry the trust policy into the bundle.
distrust_list = Path(ssl.__file__).with_name("codex-rejected-cas.pem")
if distrust_list.is_file():
    data.append((str(distrust_list), "."))
analysis = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=[],
    datas=data,
    hiddenimports=["comtypes.client.dynamic", "PIL._imagingft"],
)
archive = PYZ(analysis.pure)
exe = EXE(
    archive, analysis.scripts, analysis.binaries, analysis.datas, [],
    name="LunaGrammar",
    icon=str(root / "assets" / "luna.ico"),
    console=False,
    upx=False,
)
