# -*- coding: utf-8 -*-
# dashmgr — gerenciador de dashboards para paredes de monitores
# Copyright (C) 2026 mayk.cloud e luniobr.com
# SPDX-License-Identifier: GPL-3.0-or-later
# Este programa é software livre: você pode redistribuí-lo e/ou modificá-lo sob os termos da
# GNU General Public License v3 (ou posterior). Ele é distribuído SEM NENHUMA GARANTIA. Veja LICENSE.
"""
dashmgr_instalador_v1 — instalador visual do dashmgr (criado por mayk.cloud e luniobr.com).

Etapas: boas-vindas → senha do painel web → opções → instalando → concluído.
O programa a instalar vem dentro do setup em payload.zip (montado pelo gerar_pacote.bat).
Precisa rodar como administrador (o .exe já pede sozinho).
"""
import ctypes
import io
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import zipfile

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import dashmgr as D            # mesma marca, cores, botões e hash de senha do programa

APP = D.APP_NOME
VERSAO = D.APP_VERSAO
DESTINO_PADRAO = r"C:\dashmgr"
PORTA_PADRAO = D.WEB_PORTA_PADRAO
NO_WINDOW = 0x08000000
ANTIGAS = [r"C:\TelasNOC", r"C:\PainelMultiTelas"]                # instalações anteriores (outros nomes)
EXES_ANTIGOS = ["dashmgr.exe", "TelasNOC.exe", "PainelMultiTelas.exe"]
INICIAR_TODOS = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"),
                             r"Microsoft\Windows\Start Menu\Programs\StartUp")
INICIAR_USUARIO = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup")
DESKTOP_PUBLICO = os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "Desktop")
ATALHOS_ANTIGOS = ["Telas NOC.lnk", "Painel Multi-Telas.lnk", "PainelMultiTelas.cmd"]
REGRAS_ANTIGAS = ["Telas NOC (Web)", "Painel Multi-Telas (Web)"]
CHAVE_DESINSTALAR = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\dashmgr"


def caminho_payload():
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "payload.zip")


def rodar(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, creationflags=NO_WINDOW, **kw)


def ps(comando):
    return rodar(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", comando])


def eh_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return True


def instalacao_existente():
    """(pasta, tem_config) da instalação encontrada, ou (None, False)."""
    for pasta in [DESTINO_PADRAO] + ANTIGAS:
        if os.path.isfile(os.path.join(pasta, "painel_config.json")):
            return pasta, True
    for pasta in [DESTINO_PADRAO] + ANTIGAS:
        if os.path.isdir(pasta):
            return pasta, False
    return None, False


def chrome_instalado():
    return bool(D.achar_chrome())


def ler_json(caminho):
    with open(caminho, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def criar_atalho(lnk, alvo, args="", pasta="", icone=""):
    q = lambda t: t.replace("'", "''")
    r = ps(f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{q(lnk)}');$s.TargetPath='{q(alvo)}';"
           f"$s.Arguments='{q(args)}';$s.WorkingDirectory='{q(pasta)}';"
           + (f"$s.IconLocation='{q(icone)}';" if icone else "") + "$s.WindowStyle=7;$s.Save()")
    if r.returncode != 0 or not os.path.isfile(lnk):
        raise RuntimeError("não foi possível criar o atalho " + os.path.basename(lnk))


# --------------------------------------------------------------------------- interface
class Setup(tk.Tk):
    ETAPAS = ["Boas-vindas", "Senha", "Opções", "Instalação", "Concluído"]

    def __init__(self):
        super().__init__()
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("mayk.cloud.dashmgr.setup")
        except Exception:
            pass
        self.title(f"Instalar {APP} v{VERSAO}")
        self.geometry("820x560")
        self.resizable(False, False)
        self.configure(bg=D.COR["bg"])
        D.aplicar_estilo(self)
        self.img_logo = tk.PhotoImage(data="".join(D.LOGO_OVERLAY))
        self.img_logo_peq = tk.PhotoImage(data="".join(D.LOGO_HEADER))
        self.iconphoto(True, tk.PhotoImage(data="".join(D.ICONE)))

        self.existente, self.tem_config = instalacao_existente()
        self.tem_senha = self._tem_senha()
        self.v_senha1, self.v_senha2 = tk.StringVar(), tk.StringVar()
        self.v_manter = tk.BooleanVar(value=self.tem_senha)
        self.v_mostrar = tk.BooleanVar(value=False)
        self.v_destino = tk.StringVar(value=DESTINO_PADRAO)
        self.v_iniciar = tk.BooleanVar(value=True)
        self.v_atalho = tk.BooleanVar(value=True)
        self.v_firewall = tk.BooleanVar(value=True)
        self.v_abrir = tk.BooleanVar(value=True)
        self.v_porta = tk.StringVar(value=str(self._porta_atual()))
        for var in (self.v_senha1, self.v_senha2):
            var.trace_add("write", lambda *_: self._forca())
        self.etapa = 0
        self.instalando = False
        self.enderecos = []

        self._montar()
        self.mostrar(0)
        self.protocol("WM_DELETE_WINDOW", self.cancelar)

    def _tem_senha(self):
        if not self.tem_config:
            return False
        try:
            w = ler_json(os.path.join(self.existente, "painel_config.json")).get("web", {})
            return bool(w.get("senha_hash") and w.get("salt"))
        except Exception:
            return False

    def _porta_atual(self):
        if self.tem_config:
            try:
                return int(ler_json(os.path.join(self.existente, "painel_config.json")).get("web", {}).get("porta") or PORTA_PADRAO)
            except Exception:
                pass
        return PORTA_PADRAO

    # ---- estrutura: faixa lateral + conteúdo + rodapé com botões
    def _montar(self):
        lado = tk.Frame(self, bg=D.COR["roxo"], width=230)
        lado.pack(side="left", fill="y")
        lado.pack_propagate(False)
        tk.Frame(lado, bg=D.COR["ciano"], width=4).pack(side="right", fill="y")
        tk.Label(lado, image=self.img_logo_peq, bg=D.COR["roxo"]).pack(pady=(28, 6), padx=18, anchor="w")
        tk.Label(lado, text=f"Instalador · v{VERSAO}", font=D.F_SUB, fg=D.COR["ciano_txt"],
                 bg=D.COR["roxo"]).pack(padx=20, anchor="w")
        tk.Frame(lado, bg=D.COR["roxo_claro"], height=1).pack(fill="x", padx=20, pady=22)
        self.lbl_etapas = []
        for i, nome in enumerate(self.ETAPAS):
            f = tk.Frame(lado, bg=D.COR["roxo"])
            f.pack(fill="x", padx=20, pady=5)
            n = tk.Label(f, text=str(i + 1), width=2, font=D.F_BTN, bg=D.COR["roxo_claro"], fg="#ffffff")
            n.pack(side="left")
            t = tk.Label(f, text=nome, font=D.F_TXT, bg=D.COR["roxo"], fg="#cfc8ea")
            t.pack(side="left", padx=10)
            self.lbl_etapas.append((n, t))
        tk.Label(lado, text=D.APP_CREDITOS, font=D.F_PEQ, fg="#a99fd6", bg=D.COR["roxo"],
                 wraplength=190, justify="left").pack(side="bottom", padx=20, pady=18, anchor="w")

        direita = tk.Frame(self, bg=D.COR["card"])
        direita.pack(side="left", fill="both", expand=True)
        self.conteudo = tk.Frame(direita, bg=D.COR["card"])
        self.conteudo.pack(fill="both", expand=True, padx=34, pady=(30, 10))
        rod = tk.Frame(direita, bg=D.COR["bg"], height=64)
        rod.pack(fill="x", side="bottom")
        rod.pack_propagate(False)
        self.b_avancar = D.Botao(rod, "Avançar  →", self.avancar, "primario", fonte=(D.FONTE, 10, "bold"), padx=22, pady=8)
        self.b_avancar.pack(side="right", padx=(8, 24), pady=14)
        self.b_voltar = D.Botao(rod, "←  Voltar", self.voltar, "fantasma", padx=16, pady=8)
        self.b_voltar.pack(side="right", pady=14)
        self.b_cancelar = D.Botao(rod, "Cancelar", self.cancelar, "fantasma", padx=14, pady=8)
        self.b_cancelar.pack(side="left", padx=24, pady=14)

    def _limpar(self):
        for w in self.conteudo.winfo_children():
            w.destroy()

    def _titulo(self, txt, sub=""):
        tk.Label(self.conteudo, text=txt, font=(D.FONTE, 17, "bold"), fg=D.COR["roxo"], bg=D.COR["card"],
                 anchor="w").pack(fill="x")
        if sub:
            tk.Label(self.conteudo, text=sub, font=D.F_TXT, fg=D.COR["mudo"], bg=D.COR["card"], anchor="w",
                     justify="left", wraplength=520).pack(fill="x", pady=(4, 16))

    def _botao_estado(self, b, ativo, texto=None):
        if texto:
            b.configure(text=texto)
        b._cmd_ativo = ativo
        b.configure(fg=b._cores[1] if ativo else D.COR["desligado"], cursor="hand2" if ativo else "arrow")
        if not hasattr(b, "_cmd_orig"):
            b._cmd_orig = b._cmd
            b._cmd = lambda bb=b: bb._cmd_orig() if getattr(bb, "_cmd_ativo", True) else None

    def mostrar(self, i):
        self.etapa = i
        for k, (n, t) in enumerate(self.lbl_etapas):
            atual, feito = k == i, k < i
            n.configure(bg=D.COR["ciano"] if atual else ("#7CFFB2" if feito else D.COR["roxo_claro"]),
                        fg=D.COR["roxo"] if (atual or feito) else "#ffffff", text="✓" if feito else str(k + 1))
            t.configure(fg="#ffffff" if atual else "#cfc8ea", font=(D.FONTE, 10, "bold") if atual else D.F_TXT)
        self._limpar()
        [self.tela_boas_vindas, self.tela_senha, self.tela_opcoes, self.tela_instalando, self.tela_fim][i]()
        self._botao_estado(self.b_voltar, i in (1, 2))
        self._botao_estado(self.b_cancelar, i < 3)
        self._botao_estado(self.b_avancar, i != 3,
                           {0: "Avançar  →", 1: "Avançar  →", 2: "Instalar", 3: "Instalando…", 4: "Concluir"}[i])

    # ---- etapa 1
    def tela_boas_vindas(self):
        faixa = tk.Frame(self.conteudo, bg=D.COR["roxo"])
        faixa.pack(fill="x", pady=(0, 18))
        tk.Frame(faixa, bg=D.COR["ciano"], height=3).pack(fill="x", side="bottom")
        tk.Label(faixa, image=self.img_logo, bg=D.COR["roxo"]).pack(padx=24, pady=16)
        self._titulo(f"Bem-vindo ao instalador do {APP} v{VERSAO}",
                     "O dashmgr abre cada dashboard no monitor certo, em tela cheia e já logado, e permite "
                     "controlar as telas pelo navegador (painel web).")
        if self.existente:
            tipo = "do dashmgr" if os.path.normcase(self.existente) == os.path.normcase(DESTINO_PADRAO) else "anterior"
            msg = (f"Encontramos uma instalação {tipo} em {self.existente}.\n"
                   + ("Links, posições e senha serão mantidos." if self.tem_config else "Ela será atualizada."))
            caixa = tk.Frame(self.conteudo, bg="#eef9fc", highlightthickness=1, highlightbackground=D.COR["ciano"])
            caixa.pack(fill="x", pady=(4, 0))
            tk.Label(caixa, text="↻  Atualização", font=D.F_BTN, fg=D.COR["roxo"], bg="#eef9fc").pack(anchor="w", padx=14, pady=(10, 0))
            tk.Label(caixa, text=msg, font=D.F_TXT, fg=D.COR["ink"], bg="#eef9fc", justify="left",
                     wraplength=490, anchor="w").pack(fill="x", padx=14, pady=(2, 10))
        if not chrome_instalado():
            tk.Label(self.conteudo, text="⚠  Google Chrome não encontrado: o instalador vai tentar instalá-lo.",
                     font=D.F_TXT, fg="#8a5a00", bg=D.COR["card"]).pack(anchor="w", pady=(14, 0))
        if not eh_admin():
            tk.Label(self.conteudo, text="⚠  Abra o instalador como administrador.",
                     font=D.F_TXT, fg=D.COR["perigo"], bg=D.COR["card"]).pack(anchor="w", pady=(14, 0))

    # ---- etapa 2
    def tela_senha(self):
        self._titulo("Senha de acesso ao painel web",
                     "Essa senha protege o painel web, onde é possível mudar as telas e acessar os sistemas "
                     "remotamente. Use pelo menos 6 caracteres.")
        if self.tem_senha:
            ttk.Checkbutton(self.conteudo, text="Manter a senha atual", variable=self.v_manter,
                            style="Card.TCheckbutton", command=self._atualizar_senha_ui).pack(anchor="w", pady=(0, 10))
        self.f_senha = tk.Frame(self.conteudo, bg=D.COR["card"])
        self.f_senha.pack(fill="x")
        for rot, var in (("Nova senha", self.v_senha1), ("Repita a senha", self.v_senha2)):
            tk.Label(self.f_senha, text=rot, font=D.F_PEQ, fg=D.COR["mudo"], bg=D.COR["card"]).pack(anchor="w", pady=(6, 2))
            e = ttk.Entry(self.f_senha, textvariable=var, show="•", width=40, font=(D.FONTE, 11))
            e.pack(anchor="w")
        self.e_senhas = [w for w in self.f_senha.winfo_children() if isinstance(w, ttk.Entry)]
        ttk.Checkbutton(self.f_senha, text="Mostrar senha", variable=self.v_mostrar, style="Card.TCheckbutton",
                        command=lambda: [e.configure(show="" if self.v_mostrar.get() else "•") for e in self.e_senhas]
                        ).pack(anchor="w", pady=(8, 0))
        self.barra = tk.Canvas(self.f_senha, width=300, height=6, bg=D.COR["bg"], highlightthickness=0)
        self.barra.pack(anchor="w", pady=(12, 2))
        self.lbl_forca = tk.Label(self.f_senha, font=D.F_PEQ, fg=D.COR["mudo"], bg=D.COR["card"])
        self.lbl_forca.pack(anchor="w")
        self._forca()
        self._atualizar_senha_ui()
        if not self.v_manter.get():
            self.after(50, lambda: self.e_senhas[0].focus_set())

    def _atualizar_senha_ui(self):
        estado = "disabled" if self.v_manter.get() else "normal"
        for e in getattr(self, "e_senhas", []):
            e.configure(state=estado)

    def _forca(self):
        if not getattr(self, "barra", None) or not self.barra.winfo_exists():
            return
        s1, s2 = self.v_senha1.get(), self.v_senha2.get()
        pts = sum([len(s1) >= 6, len(s1) >= 10, any(c.isdigit() for c in s1),
                   any(c.isupper() for c in s1) and any(c.islower() for c in s1), any(not c.isalnum() for c in s1)])
        cores = ["#d9d5e8", "#c0392b", "#e67e22", "#e6b422", "#33BCD5", "#2ecc71"]
        nomes = ["", "fraca", "fraca", "média", "boa", "forte"]
        self.barra.delete("all")
        self.barra.create_rectangle(0, 0, 300 * pts / 5, 6, fill=cores[pts], outline="")
        txt = f"Força: {nomes[pts]}" if s1 else ""
        if s2 and s1 != s2:
            txt += ("  ·  " if txt else "") + "as senhas não conferem"
        self.lbl_forca.configure(text=txt, fg=D.COR["perigo"] if (s2 and s1 != s2) else D.COR["mudo"])

    # ---- etapa 3
    def tela_opcoes(self):
        self._titulo("Opções de instalação", "Pode deixar como está; tudo pode ser mudado depois no programa.")
        tk.Label(self.conteudo, text="Pasta de instalação", font=D.F_PEQ, fg=D.COR["mudo"], bg=D.COR["card"]).pack(anchor="w")
        lp = tk.Frame(self.conteudo, bg=D.COR["card"])
        lp.pack(fill="x", pady=(2, 12))
        ttk.Entry(lp, textvariable=self.v_destino, width=44).pack(side="left")
        D.Botao(lp, "Procurar…", lambda: self.v_destino.set(
            (filedialog.askdirectory(initialdir=self.v_destino.get()) or self.v_destino.get()).replace("/", "\\")),
            "fantasma", padx=8, pady=3).pack(side="left", padx=8)
        for txt, var in (("Iniciar o dashmgr junto com o Windows (abre as telas 20 s após o logon)", self.v_iniciar),
                         ("Criar atalho na Área de Trabalho", self.v_atalho),
                         ("Liberar o painel web no firewall (só redes Privada e Domínio)", self.v_firewall),
                         ("Abrir o dashmgr ao terminar", self.v_abrir)):
            ttk.Checkbutton(self.conteudo, text=txt, variable=var, style="Card.TCheckbutton").pack(anchor="w", pady=3)
        lp2 = tk.Frame(self.conteudo, bg=D.COR["card"])
        lp2.pack(fill="x", pady=(12, 0))
        tk.Label(lp2, text="Porta do painel web", font=D.F_PEQ, fg=D.COR["mudo"], bg=D.COR["card"]).pack(side="left")
        ttk.Entry(lp2, textvariable=self.v_porta, width=8).pack(side="left", padx=8)

    # ---- etapa 4
    def tela_instalando(self):
        self._titulo("Instalando…", "Isso leva menos de um minuto.")
        self.pb = ttk.Progressbar(self.conteudo, length=520, mode="determinate", maximum=100)
        estilo = ttk.Style(self)
        estilo.configure("Lunio.Horizontal.TProgressbar", troughcolor=D.COR["bg"], background=D.COR["ciano"],
                         bordercolor=D.COR["bg"], lightcolor=D.COR["ciano"], darkcolor=D.COR["ciano"])
        self.pb.configure(style="Lunio.Horizontal.TProgressbar")
        self.pb.pack(anchor="w", pady=(0, 14))
        self.log = tk.Text(self.conteudo, height=14, width=66, font=(D.FONTE, 9), bg=D.COR["bg"], fg=D.COR["ink"],
                           relief="flat", highlightthickness=0, padx=10, pady=8, state="disabled")
        self.log.pack(anchor="w", fill="both", expand=True)
        self.log.tag_configure("ok", foreground="#1e8449")
        self.log.tag_configure("aviso", foreground="#9a6700")
        self.log.tag_configure("erro", foreground=D.COR["perigo"])

    def escrever(self, txt, tag=None, prog=None):
        def f():
            self.log.configure(state="normal")
            self.log.insert("end", txt + "\n", tag or ())
            self.log.see("end")
            self.log.configure(state="disabled")
            if prog is not None:
                self.pb["value"] = prog
        self.after(0, f)

    def perguntar(self, titulo, texto):
        """Pergunta Sim/Não a partir da thread de instalação."""
        r, ev = {}, threading.Event()
        self.after(0, lambda: (r.setdefault("v", messagebox.askyesno(titulo, texto, parent=self)), ev.set()))
        ev.wait()
        return r["v"]

    # ---- etapa 5
    def tela_fim(self):
        tk.Label(self.conteudo, text="✓", font=(D.FONTE, 40, "bold"), fg="#2ecc71", bg=D.COR["card"]).pack(anchor="w")
        self._titulo(f"{APP} v{VERSAO} instalado!", "Tudo pronto. Acesse o painel web de outro computador da rede:")
        for e in self.enderecos or ["(o endereço aparece no topo da janela do dashmgr)"]:
            tk.Label(self.conteudo, text=e, font=(D.FONTE, 12, "bold"), fg=D.COR["roxo"], bg=D.COR["card"]).pack(anchor="w", pady=1)
        tk.Label(self.conteudo, text="Próximo passo: no dashmgr, clique em “Login” em um link de cada sistema, faça o "
                 "login uma vez e depois clique em “↻ Recarregar telas”.", font=D.F_TXT, fg=D.COR["mudo"],
                 bg=D.COR["card"], justify="left", wraplength=520, anchor="w").pack(fill="x", pady=(18, 0))

    # ---- navegação
    def voltar(self):
        if self.etapa in (1, 2):
            self.mostrar(self.etapa - 1)

    def cancelar(self):
        if self.instalando:
            return
        if self.etapa == 4 or messagebox.askyesno(APP, "Cancelar a instalação?", parent=self):
            self.destroy()

    def avancar(self):
        if self.etapa == 0:
            if not eh_admin():
                messagebox.showerror(APP, "Feche e abra o instalador com 'Executar como administrador'.", parent=self)
                return
            self.mostrar(1)
        elif self.etapa == 1:
            if not self.v_manter.get():
                s1, s2 = self.v_senha1.get(), self.v_senha2.get()
                if len(s1) < 6:
                    messagebox.showwarning(APP, "A senha precisa ter pelo menos 6 caracteres.", parent=self)
                    return
                if s1 != s2:
                    messagebox.showwarning(APP, "As senhas não conferem.", parent=self)
                    return
            self.mostrar(2)
        elif self.etapa == 2:
            try:
                porta = int(self.v_porta.get())
                assert 1 <= porta <= 65535
            except Exception:
                messagebox.showwarning(APP, "Porta inválida.", parent=self)
                return
            destino = self.v_destino.get().strip().rstrip("\\") or DESTINO_PADRAO
            self.v_destino.set(destino)
            self.mostrar(3)
            self.instalando = True
            threading.Thread(target=self._instalar, args=(destino, porta), daemon=True).start()
        elif self.etapa == 4:
            if self.v_abrir.get():
                abrir_sem_admin(os.path.join(self.v_destino.get(), "dashmgr.exe"))
            self.destroy()

    # ---- instalação (thread)
    def _instalar(self, destino, porta):
        exe = os.path.join(destino, "dashmgr.exe")
        try:
            self.escrever("• Encerrando versões anteriores…", prog=5)
            for nome in EXES_ANTIGOS:
                rodar(["taskkill", "/F", "/IM", nome])
            time.sleep(1.5)

            self.escrever("• Copiando os arquivos do programa…", prog=15)
            os.makedirs(destino, exist_ok=True)
            with zipfile.ZipFile(caminho_payload()) as z:
                nomes = z.namelist()
                for i, n in enumerate(nomes):
                    if n.endswith("/") or n == "painel_config.json":
                        continue
                    alvo = os.path.join(destino, *n.split("/"))
                    os.makedirs(os.path.dirname(alvo), exist_ok=True)
                    with z.open(n) as src, open(alvo, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    if i % 40 == 0:
                        self.escrever_prog(15 + 40 * i / max(1, len(nomes)))
                cfg_pacote = json.loads(z.read("painel_config.json")) if "painel_config.json" in nomes else None
            time.sleep(2)
            if not os.path.isfile(exe):
                self._antivirus(destino, exe)
            self.escrever("  arquivos copiados", "ok", prog=55)

            self.escrever("• Configuração e senha…", prog=60)
            cfg_destino = os.path.join(destino, "painel_config.json")
            if os.path.isfile(cfg_destino):
                cfg = ler_json(cfg_destino)
                self.escrever("  configuração existente mantida", "ok")
            else:
                cfg = None
                for antiga in ANTIGAS:
                    p = os.path.join(antiga, "painel_config.json")
                    if os.path.isfile(p):
                        cfg = ler_json(p)
                        self.escrever(f"  configuração migrada de {antiga}", "ok")
                        break
                if cfg is None:
                    cfg = cfg_pacote or {}
                    if cfg_pacote:
                        self.escrever("  links do pacote copiados", "ok")
            w = cfg.setdefault("web", {})
            w["porta"] = porta
            w.setdefault("ativo", True)
            if not self.v_manter.get():
                salt = secrets.token_hex(16)
                w["salt"], w["senha_hash"] = salt, D.hash_senha(self.v_senha1.get(), salt)
                self.after(0, lambda: (self.v_senha1.set(""), self.v_senha2.set("")))
                self.escrever("  nova senha do painel web definida (só o hash é gravado)", "ok")
            tmp = cfg_destino + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            os.replace(tmp, cfg_destino)
            rodar(["icacls", destino, "/grant", "*S-1-5-32-545:(OI)(CI)M", "/T", "/Q"])   # usuários gravam a config

            self.escrever("• Google Chrome…", prog=68)
            if chrome_instalado():
                self.escrever("  encontrado", "ok")
            else:
                self.escrever("  não encontrado, instalando pelo winget (pode demorar)…", "aviso")
                r = rodar(["winget", "install", "-e", "--id", "Google.Chrome", "--silent",
                           "--accept-package-agreements", "--accept-source-agreements"])
                self.escrever("  instalado" if chrome_instalado() else "  instale o Chrome manualmente antes de usar",
                              "ok" if chrome_instalado() else "aviso")

            self.escrever("• Firewall…", prog=76)
            for regra in REGRAS_ANTIGAS + ["dashmgr (Web)"]:
                rodar(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={regra}"])
            if self.v_firewall.get():
                r = rodar(["netsh", "advfirewall", "firewall", "add", "rule", "name=dashmgr (Web)", "dir=in",
                           "action=allow", "protocol=TCP", f"localport={porta}", "profile=private,domain", f"program={exe}"])
                self.escrever(f"  porta {porta} liberada (Privada/Domínio)" if r.returncode == 0 else "  não foi possível criar a regra",
                              "ok" if r.returncode == 0 else "aviso")
                cat = ps("(Get-NetConnectionProfile | Where-Object IPv4Connectivity -ne 'Disconnected' | "
                         "Select-Object -First 1).NetworkCategory").stdout.strip()
                if cat.lower() == "public" and self.perguntar(APP, "A rede deste PC está marcada como PÚBLICA e o firewall vai "
                                                                  "bloquear o painel web.\n\nMudar a rede para PRIVADA agora?"):
                    ps("Get-NetConnectionProfile | Where-Object IPv4Connectivity -ne 'Disconnected' | "
                       "Set-NetConnectionProfile -NetworkCategory Private")
                    self.escrever("  rede alterada para Privada", "ok")
            else:
                self.escrever("  pulado", "aviso")

            self.escrever("• Atalhos e início automático…", prog=84)
            for pasta in (INICIAR_TODOS, INICIAR_USUARIO, DESKTOP_PUBLICO):
                for nome in ATALHOS_ANTIGOS + ["dashmgr.lnk"]:
                    try:
                        os.remove(os.path.join(pasta, nome))
                    except OSError:
                        pass
            ico = os.path.join(destino, "dashmgr.ico")
            if self.v_iniciar.get():
                criar_atalho(os.path.join(INICIAR_TODOS, "dashmgr.lnk"), exe, "--auto --espera=20", destino, ico)
                self.escrever("  inicia com o Windows (todos os usuários)", "ok")
            if self.v_atalho.get():
                criar_atalho(os.path.join(DESKTOP_PUBLICO, "dashmgr.lnk"), exe, "", destino, ico)
                self.escrever("  atalho na Área de Trabalho", "ok")

            self.escrever("• Registrando em Aplicativos instalados…", prog=92)
            self._registrar(destino)
            for antiga in ANTIGAS:
                if os.path.isdir(antiga) and os.path.normcase(antiga) != os.path.normcase(destino):
                    self.escrever(f"  a pasta antiga {antiga} pode ser apagada", "aviso")

            self.enderecos = [f"http://{ip}:{porta}" for ip in ips_locais()]
            self.escrever("✓ Instalação concluída.", "ok", prog=100)
            time.sleep(0.8)
            self.after(0, self._fim_ok)
        except Exception as e:
            self.escrever(f"✗ Falhou: {e}", "erro")
            self.after(0, self._fim_erro)

    def escrever_prog(self, v):
        self.after(0, lambda: self.pb.configure(value=v))

    def _antivirus(self, destino, exe):
        self.escrever("  o antivírus removeu o dashmgr.exe", "aviso")
        if not self.perguntar(APP, "O antivírus removeu o dashmgr.exe (falso positivo comum).\n\n"
                                   f"Adicionar {destino} como exceção no Windows Defender e copiar de novo?"):
            raise RuntimeError("o antivírus bloqueou o programa")
        ps(f"Add-MpPreference -ExclusionPath '{destino}'")
        with zipfile.ZipFile(caminho_payload()) as z:
            with z.open("dashmgr.exe") as src, open(exe, "wb") as dst:
                shutil.copyfileobj(src, dst)
        time.sleep(2)
        if not os.path.isfile(exe):
            raise RuntimeError("o antivírus continua removendo o programa; peça a exceção ao responsável")
        self.escrever("  exceção adicionada", "ok")

    def _registrar(self, destino):
        try:
            import winreg
            with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, CHAVE_DESINSTALAR, 0,
                                    winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY) as k:
                for nome, valor in (("DisplayName", "dashmgr"), ("DisplayVersion", VERSAO),
                                    ("Publisher", "mayk.cloud / luniobr.com"),
                                    ("DisplayIcon", os.path.join(destino, "dashmgr.ico")),
                                    ("InstallLocation", destino), ("URLInfoAbout", "https://luniobr.com"),
                                    ("UninstallString", f'"{os.path.join(destino, "desinstalar.bat")}"')):
                    winreg.SetValueEx(k, nome, 0, winreg.REG_SZ, valor)
                winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
                winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
            self.escrever("  registrado", "ok")
        except Exception as e:
            self.escrever(f"  não foi possível registrar ({e})", "aviso")

    def _fim_ok(self):
        self.instalando = False
        self.mostrar(4)

    def _fim_erro(self):
        self.instalando = False
        self.b_avancar.configure(text="Fechar")
        self._botao_estado(self.b_avancar, True)
        self.b_avancar._cmd_orig = self.destroy


def ips_locais():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except Exception:
        pass
    return sorted(i for i in ips if not i.startswith(("127.", "169.254."))) or ["localhost"]


def abrir_sem_admin(exe):
    """Abre o programa com o usuário comum (via Explorer), não como administrador."""
    try:
        subprocess.Popen(["explorer.exe", exe])
    except Exception:
        pass


if __name__ == "__main__":
    Setup().mainloop()
