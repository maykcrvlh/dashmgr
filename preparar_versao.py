# -*- coding: utf-8 -*-
# dashmgr — gerenciador de dashboards para paredes de monitores
# Copyright (C) 2026 mayk.cloud e luniobr.com
# SPDX-License-Identifier: GPL-3.0-or-later
# Este programa é software livre: você pode redistribuí-lo e/ou modificá-lo sob os termos da
# GNU General Public License v3 (ou posterior). Ele é distribuído SEM NENHUMA GARANTIA. Veja LICENSE.
"""Usado pelo gerar_pacote.bat: lê APP_VERSAO do dashmgr.py e gera _build\\versao.txt + _build\\version_info.txt
(ficha de versão do .exe: botão direito > Propriedades > Detalhes)."""
import io
import os
import re

aqui = os.path.dirname(os.path.abspath(__file__))
fonte = io.open(os.path.join(aqui, "dashmgr.py"), encoding="utf-8").read()
versao = re.search(r'^APP_VERSAO = "([0-9]+(?:\.[0-9]+){0,3})"', fonte, re.M).group(1)
saida = os.path.join(aqui, "_build")          # arquivos gerados ficam fora da raiz do projeto
os.makedirs(saida, exist_ok=True)
partes = [int(x) for x in versao.split(".")] + [0, 0, 0]
tupla = tuple(partes[:4])

io.open(os.path.join(saida, "versao.txt"), "w", encoding="ascii").write(versao)
io.open(os.path.join(saida, "version_info.txt"), "w", encoding="utf-8").write(f"""# gerado por preparar_versao.py
VSVersionInfo(
  ffi=FixedFileInfo(filevers={tupla}, prodvers={tupla}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041604B0', [
      StringStruct('CompanyName', 'mayk.cloud / luniobr.com'),
      StringStruct('FileDescription', 'dashmgr - gerenciador de dashboards'),
      StringStruct('FileVersion', '{versao}'),
      StringStruct('InternalName', 'dashmgr'),
      StringStruct('LegalCopyright', 'Criado por mayk.cloud e luniobr.com'),
      StringStruct('OriginalFilename', 'dashmgr.exe'),
      StringStruct('ProductName', 'dashmgr'),
      StringStruct('ProductVersion', '{versao}')])]),
    VarFileInfo([VarStruct('Translation', [0x0416, 1200])])
  ]
)
""")
print(versao)
