# -*- coding: utf-8 -*-
# dashmgr — gerenciador de dashboards para paredes de monitores
# Copyright (C) 2026 mayk.cloud e luniobr.com
# SPDX-License-Identifier: GPL-3.0-or-later
# Este programa é software livre: você pode redistribuí-lo e/ou modificá-lo sob os termos da
# GNU General Public License v3 (ou posterior). Ele é distribuído SEM NENHUMA GARANTIA. Veja LICENSE.
"""Usado pelo gerar_pacote.bat.
  python empacotar.py payload        -> _build\\payload\\payload.zip (programa + extras, embutido no setup)
  python empacotar.py zip <nome>      -> <nome>.zip (ex.: dashmgr_instalador_v1.zip, o instalador pronto)
Tenta de novo quando o antivírus está com algum arquivo aberto."""
import io
import json
import os
import sys
import time
import zipfile

AQUI = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(AQUI, "_build")


def zipar(destino, entradas):
    """entradas: lista de (caminho_no_disco, nome_no_zip). Até 6 tentativas se algum arquivo estiver em uso."""
    for tentativa in range(1, 7):
        try:
            tmp = destino + ".tmp"
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
                for disco, nome in entradas:
                    if isinstance(disco, bytes):
                        z.writestr(nome, disco)
                    else:
                        z.write(disco, nome)
            os.replace(tmp, destino)
            return
        except (PermissionError, OSError) as e:
            print(f"   arquivo em uso ({e.__class__.__name__}), tentativa {tentativa} de 6...")
            time.sleep(6)
    sys.exit("Nao foi possivel compactar (arquivos em uso pelo antivirus?).")


def arquivos_de(pasta, prefixo=""):
    for raiz, _, nomes in os.walk(pasta):
        for n in nomes:
            disco = os.path.join(raiz, n)
            yield disco, prefixo + os.path.relpath(disco, pasta).replace(os.sep, "/")


def payload():
    prog = os.path.join(BUILD, "dist", "dashmgr")
    if not os.path.isfile(os.path.join(prog, "dashmgr.exe")):
        sys.exit("dist\\dashmgr\\dashmgr.exe nao encontrado (antivirus?)")
    entradas = list(arquivos_de(prog))
    for extra in ("dashmgr.ico", "LEIA-ME.txt", "desinstalar.bat", "definir_senha.ps1"):
        entradas.append((os.path.join(AQUI, extra), extra))
    entradas.append((os.path.join(BUILD, "versao.txt"), "versao.txt"))
    cfg = os.path.join(AQUI, "painel_config.json")
    if os.path.isfile(cfg):           # leva links/posições deste PC, sem caminhos locais
        c = json.load(io.open(cfg, encoding="utf-8-sig"))
        for k in ("chrome_path", "perfis_dir"):
            c.pop(k, None)
        entradas.append((json.dumps(c, ensure_ascii=False, indent=2).encode("utf-8"), "painel_config.json"))
    os.makedirs(os.path.join(BUILD, "payload"), exist_ok=True)
    zipar(os.path.join(BUILD, "payload", "payload.zip"), entradas)
    print(f"   payload: {len(entradas)} arquivos")


def zip_final(setup_nome):
    setup = os.path.join(BUILD, "dist", setup_nome)
    if not os.path.isfile(os.path.join(setup, setup_nome + ".exe")):
        sys.exit(f"dist\\{setup_nome}\\{setup_nome}.exe nao encontrado (antivirus?)")
    nome = os.path.join(AQUI, f"{setup_nome}.zip")
    zipar(nome, list(arquivos_de(setup, setup_nome + "/")))
    with zipfile.ZipFile(nome) as z:
        assert f"{setup_nome}/{setup_nome}.exe" in z.namelist() and z.testzip() is None
    print(f"   {os.path.basename(nome)}: {os.path.getsize(nome) / 1e6:.1f} MB")


if __name__ == "__main__":
    if sys.argv[1:2] == ["payload"]:
        payload()
    elif sys.argv[1:2] == ["zip"]:
        zip_final(sys.argv[2])
    else:
        sys.exit(__doc__)
