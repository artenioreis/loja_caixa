# -*- mode: python ; coding: utf-8 -*-
# tray_app.spec — Build do Sistema de Caixa NSG com bandeja do Windows

import os

block_cipher = None

# Pasta raiz do projeto
project_dir = os.path.abspath('.')

a = Analysis(
    ['tray_app.py'],
    pathex=[project_dir],
    binaries=[],
    datas=[
        # Templates HTML
        ('templates',       'templates'),
        # Arquivos estáticos (CSS, JS, imagens)
        ('static',          'static'),
        # Modelos e banco
        ('models.py',       '.'),
        ('database.py',     '.'),
        ('app.py',          '.'),
    ],
    hiddenimports=[
        # Flask e extensões
        'flask',
        'flask_sqlalchemy',
        'flask_login',
        'werkzeug',
        'werkzeug.security',
        'werkzeug.utils',
        # SQLAlchemy
        'sqlalchemy',
        'sqlalchemy.dialects.sqlite',
        'sqlalchemy.orm',
        'sqlalchemy.event',
        'sqlalchemy.engine',
        # Pystray e Pillow
        'pystray',
        'PIL',
        'PIL.Image',
        # Pandas / openpyxl
        'pandas',
        'openpyxl',
        # Outros
        'jinja2',
        'click',
        'itsdangerous',
        'email_validator',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CaixaNSG',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # SEM janela de console (roda silencioso)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(project_dir, 'static', 'images', 'tray_icon.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='CaixaNSG',
)
