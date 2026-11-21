"""Check the real release archive, GUI subsystem, assets, and source freshness."""
from hashlib import sha256
from pathlib import Path
from types import CodeType
import sys

from PyInstaller.archive.readers import CArchiveReader
import pefile

ROOT = Path(__file__).resolve().parents[1]


def signature(code):
    if isinstance(code, CodeType):
        return (code.co_code, tuple(signature(item) for item in code.co_consts),code.co_names,
                code.co_varnames,code.co_argcount,code.co_kwonlyargcount,code.co_posonlyargcount,
                code.co_freevars,code.co_cellvars,code.co_flags)
    return code


def main():
    path = ROOT/'dist'/'LunaGrammar.exe'
    pe = pefile.PE(str(path))
    assert pe.FILE_HEADER.Machine == 0x8664
    assert pe.OPTIONAL_HEADER.Subsystem == 2
    archive = CArchiveReader(str(path))
    names = set(archive.toc)
    assert any('Poppins-Regular.ttf' in name for name in names)
    assert any(name.endswith('luna.ico') for name in names)
    assert any('OFL' in name or 'LICENSE' in name for name in names)
    assert not any(name.endswith('settings.json') or name.endswith('.env') for name in names)
    prior = CArchiveReader(str(ROOT/'round5-baseline'/'LunaGrammar.exe'))
    for name in prior.toc:
        if name.replace('\\','/').startswith('assets/'):
            assert name in names and archive.extract(name) == prior.extract(name), f'Changed asset: {name}'
    pyz_name = next(name for name in names if name.endswith('.pyz'))
    pyz = archive.open_embedded_archive(pyz_name)
    for name in ('win32','config','grammar_engine','correction_modes','shortcut_state','windows_hotkey',
                 'text_selection','clipboard_manager','diagnostics','input_monitor','pill_art',
                 'overlay','settings_window','undo_manager'):
        code = pyz.extract(name)
        source = compile((ROOT/(name+'.py')).read_bytes(),name+'.py','exec')
        assert signature(code) == signature(source), f'Stale bundled source: {name}'
    print('PASS: x64 GUI executable, external preferences, bundled assets/font license, and all application modules match current source.')
    print('Bytes:',path.stat().st_size)
    print('SHA256:',sha256(path.read_bytes()).hexdigest().upper())


if __name__ == '__main__':
    main()
