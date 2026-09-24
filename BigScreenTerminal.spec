# -*- mode: python ; coding: utf-8 -*-
import os
import sys

# DLL 扫描不能继承其他工具的 PATH（例如 Poppler 自带的 icuuc.dll）。
# Qt 的 ICU 依赖应解析到 Windows 系统库，第三方同名库的导出函数不兼容。
# PyInstaller 的 Qt hook 会另外添加 Qt wheel 的 DLL 目录。
windows_dir = os.environ.get('SystemRoot', r'C:\Windows')
os.environ['PATH'] = os.pathsep.join([
    os.path.join(windows_dir, 'System32'), windows_dir,
    sys.base_prefix, os.path.join(sys.base_prefix, 'Scripts'),
])

datas = []


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BigScreenTerminal',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='version.txt',
    icon=['icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='BigScreenTerminal',
)
