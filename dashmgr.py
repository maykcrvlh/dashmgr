# -*- coding: utf-8 -*-
# dashmgr — gerenciador de dashboards para paredes de monitores
# Copyright (C) 2026 mayk.cloud e luniobr.com
# SPDX-License-Identifier: GPL-3.0-or-later
# Este programa é software livre: você pode redistribuí-lo e/ou modificá-lo sob os termos da
# GNU General Public License v3 (ou posterior). Ele é distribuído SEM NENHUMA GARANTIA. Veja LICENSE.
"""
dashmgr — gerenciador de dashboards: abre um link do Chrome em cada monitor (tela cheia).
Criado por mayk.cloud e luniobr.com.

- Detecta todos os monitores do Windows.
- Cada link escolhe em qual tela abre.
- Cada link usa um perfil próprio do Chrome -> o login fica salvo.
- Configuração salva em painel_config.json (mesma pasta do programa).

Uso:
  dashmgr.py           -> abre a interface
  dashmgr.py --auto    -> abre todos os links e encerra (para iniciar com o Windows)
  dashmgr.py --fechar  -> fecha todas as janelas do painel
  dashmgr.py --web     -> abre minimizado (só para servir o painel web)

Painel web: http://IP-DO-PC:888 (porta e senha em Configurações). Para HTTPS, coloque
cert.pem e key.pem na pasta do programa.

Para sair do kiosk de uma tela: botão "Fechar" na linha, ou Ctrl+Alt+Q com o
mouse sobre a tela (com o programa aberto), ou clicar na tela e Alt+F4.

Requer: Windows + Python 3.8+ (somente biblioteca padrão).
"""
import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from ctypes import wintypes

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

APP_NOME = "dashmgr"
APP_CREDITOS = "criado por mayk.cloud e luniobr.com"
APP_VERSAO = "1"
MARCADOR_PERFIL = "PainelMultiTelas_Perfis"   # usado para achar/fechar só as janelas do painel
CREATE_NO_WINDOW = 0x08000000

# --------------------------------------------------------------------------- caminhos
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "painel_config.json")
PERFIS_PADRAO = os.path.join(os.environ.get("LOCALAPPDATA", BASE_DIR), "PainelMultiTelas", MARCADOR_PERFIL)
STARTUP_DIR = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup")
STARTUP_CMD = os.path.join(STARTUP_DIR, "dashmgr.lnk")
# o instalador usa a pasta Inicializar de TODOS os usuários (PC dedicado aos monitores)
STARTUP_CMD_TODOS = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"),
                                 r"Microsoft\Windows\Start Menu\Programs\StartUp", "dashmgr.lnk")
STARTUP_ANTIGOS = [os.path.join(STARTUP_DIR, "PainelMultiTelas.cmd"),          # nomes antigos
                   os.path.join(STARTUP_DIR, "Painel Multi-Telas.lnk"),
                   os.path.join(STARTUP_DIR, "Telas NOC.lnk")]   # versões anteriores


def inicia_com_windows():
    return any(os.path.isfile(a) for a in [STARTUP_CMD, STARTUP_CMD_TODOS] + STARTUP_ANTIGOS)

# --------------------------------------------------------------------------- Win32
user32 = ctypes.windll.user32
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # coordenadas físicas reais em cada monitor
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("DeviceName", wintypes.WCHAR * 32),
                ("DeviceString", wintypes.WCHAR * 128), ("StateFlags", wintypes.DWORD),
                ("DeviceID", wintypes.WCHAR * 128), ("DeviceKey", wintypes.WCHAR * 128)]


def hwid_monitor(device):
    """ID de hardware do monitor ligado à saída (não muda quando o Windows renumera as telas)."""
    try:
        dd = DISPLAY_DEVICEW()
        dd.cb = ctypes.sizeof(DISPLAY_DEVICEW)
        if user32.EnumDisplayDevicesW(device, 0, ctypes.byref(dd), 1):  # EDD_GET_DEVICE_INTERFACE_NAME
            return dd.DeviceID or ""
    except Exception:
        pass
    return ""


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
                ("szDevice", wintypes.WCHAR * 32)]


MonitorEnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                     ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.MonitorFromWindow.restype = wintypes.HMONITOR
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]


def listar_monitores():
    """Retorna lista de monitores ordenada da esquerda p/ direita, de cima p/ baixo."""
    mons = []

    def cb(hmon, hdc, lprc, lparam):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        user32.GetMonitorInfoW(hmon, ctypes.byref(info))
        r = info.rcMonitor
        escala = 1.0
        try:
            dx, dy = wintypes.UINT(), wintypes.UINT()
            if ctypes.windll.shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dx), ctypes.byref(dy)) == 0 and dx.value:
                escala = dx.value / 96.0
        except Exception:
            pass
        mons.append({
            "device": info.szDevice,
            "x": r.left, "y": r.top,
            "w": r.right - r.left, "h": r.bottom - r.top,
            "primario": bool(info.dwFlags & 1),
            "hwid": hwid_monitor(info.szDevice),
            "escala": escala,
        })
        return True

    proc = MonitorEnumProc(cb)
    user32.EnumDisplayMonitors(None, None, proc, 0)

    # agrupa em "linhas" (monitores com topo parecido) e ordena por X dentro da linha
    mons.sort(key=lambda m: m["y"])
    linhas = []
    for m in mons:
        if linhas and abs(m["y"] - linhas[-1][0]["y"]) < m["h"] // 2:
            linhas[-1].append(m)
        else:
            linhas.append([m])
    ordenados = []
    for linha in linhas:
        ordenados.extend(sorted(linha, key=lambda m: m["x"]))
    for i, m in enumerate(ordenados, 1):
        m["num"] = i
    return ordenados


def resolver_monitor(item, monitores):
    """Acha a tela vinculada ao link: 1º pelo ID de hardware, 2º pela posição na área de
    trabalho, 3º pelo nome DISPLAYn (que é o que o Windows costuma renumerar)."""
    hw = item.get("monitor_hwid")
    if hw:
        for m in monitores:
            if m.get("hwid") == hw:
                return m
    pos = item.get("monitor_pos")
    if pos:
        for m in monitores:
            if [m["x"], m["y"]] == list(pos):
                return m
    for m in monitores:
        if m["device"] == item.get("monitor"):
            return m
    return None


def janelas_do_pid(pid):
    """Janelas visíveis de nível superior do Chrome pertencentes ao PID."""
    achadas = []
    classe = ctypes.create_unicode_buffer(64)

    def cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid:
            user32.GetClassNameW(hwnd, classe, 64)
            if classe.value.startswith("Chrome_WidgetWin"):
                achadas.append(hwnd)
        return True

    proc = EnumWindowsProc(cb)
    user32.EnumWindows(proc, 0)
    return achadas


def garantir_posicao(pid, mon, timeout=15):
    """Se o Chrome abriu na tela errada (DPI/escala diferente), move a janela para a tela certa."""
    fim = time.time() + timeout
    while time.time() < fim:
        hwnds = janelas_do_pid(pid)
        if hwnds:
            time.sleep(1.0)  # deixa o kiosk terminar de entrar em tela cheia
            for hwnd in janelas_do_pid(pid):
                r = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(r))
                cx, cy = (r.left + r.right) // 2, (r.top + r.bottom) // 2
                dentro = mon["x"] <= cx < mon["x"] + mon["w"] and mon["y"] <= cy < mon["y"] + mon["h"]
                if not dentro:
                    SWP_NOZORDER, SWP_SHOWWINDOW = 0x0004, 0x0040
                    user32.SetWindowPos(hwnd, 0, mon["x"], mon["y"], mon["w"], mon["h"],
                                        SWP_NOZORDER | SWP_SHOWWINDOW)
            return
        time.sleep(0.3)


# --------------------------------------------------------------------------- Chrome
def achar_chrome():
    candidatos = [
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), r"Google\Chrome\Application\chrome.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), r"Google\Chrome\Application\chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Google\Chrome\Application\chrome.exe"),
    ]
    try:
        import winreg
        for raiz in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(raiz, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe") as k:
                    candidatos.insert(0, winreg.QueryValue(k, None))
            except OSError:
                pass
    except ImportError:
        pass
    for c in candidatos:
        if c and os.path.isfile(c):
            return c
    return ""


def marcar_saida_limpa(perfil_dir):
    """Evita a barra 'O Chrome não foi encerrado corretamente' depois de fechar à força."""
    pref = os.path.join(perfil_dir, "Default", "Preferences")
    if not os.path.isfile(pref):
        return
    try:
        with open(pref, "r", encoding="utf-8") as f:
            dados = json.load(f)
        dados.setdefault("profile", {})["exit_type"] = "Normal"
        dados["profile"]["exited_cleanly"] = True
        with open(pref, "w", encoding="utf-8") as f:
            json.dump(dados, f)
    except Exception:
        pass


def pids_do_painel(filtro=MARCADOR_PERFIL):
    """PIDs dos chrome.exe cujo comando contém o filtro (perfil do painel)."""
    filtro = filtro.replace("'", "''")
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
          f"Where-Object {{ $_.CommandLine -like '*{filtro}*' }} | "
          "ForEach-Object { $_.ProcessId }")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                       capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    return {int(x) for x in r.stdout.split() if x.strip().isdigit()}


def fechar_pids(pids, espera=8.0):
    """Fecha com WM_CLOSE (o Chrome salva cookies/login) e força o encerramento se não sair."""
    if not pids:
        return
    WM_CLOSE = 0x0010
    for pid in pids:
        for hwnd in janelas_do_pid(pid):
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    fim = time.time() + espera
    while time.time() < fim and any(janelas_do_pid(p) for p in pids):
        time.sleep(0.3)
    time.sleep(0.5)
    for pid in pids:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True,
                       creationflags=CREATE_NO_WINDOW)


def fechar_paineis(cfg=None):
    """Fecha somente os Chrome abertos com perfis do painel (não mexe no Chrome normal do usuário)."""
    if cfg is not None:
        try:
            salvar_cookies(cfg)
        except Exception:
            pass
    fechar_pids(pids_do_painel())
    if cfg is not None:
        _janelas_salvar(cfg, {})


# --------------------------------------------------------------------------- Chrome compartilhado (login único)
# Todos os links (exceto os marcados "Login separado") abrem como janelas de UM único Chrome com um
# perfil compartilhado. O programa controla esse Chrome pelo protocolo de depuração (CDP), escutando
# só em 127.0.0.1, para criar cada janela, colocá-la no monitor certo e deixá-la em tela cheia.
import base64
import http.client
import socket as _socket
import urllib.parse

PERFIL_COMPARTILHADO = "_compartilhado"
CDP_PORTA_PADRAO = 9333
_TRAVA_CDP = threading.RLock()


class CDPErro(Exception):
    pass


class _WS:
    """Cliente WebSocket mínimo (RFC 6455) — suficiente para o CDP local."""

    def __init__(self, url, timeout=15):
        u = urllib.parse.urlparse(url)
        self.s = _socket.create_connection((u.hostname, u.port), timeout=timeout)
        chave = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\n"
                        f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {chave}\r\n"
                        "Sec-WebSocket-Version: 13\r\n\r\n").encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            d = self.s.recv(4096)
            if not d:
                raise CDPErro("Chrome fechou a conexão")
            resp += d
        if b" 101 " not in resp.split(b"\r\n", 1)[0]:
            raise CDPErro("Chrome recusou a conexão: " + resp[:120].decode("latin-1"))
        self.buf = resp.split(b"\r\n\r\n", 1)[1]

    def enviar(self, texto):
        dados = texto.encode("utf-8")
        n = len(dados)
        cab = bytearray([0x81])
        if n < 126:
            cab.append(0x80 | n)
        elif n < 65536:
            cab.append(0x80 | 126)
            cab += n.to_bytes(2, "big")
        else:
            cab.append(0x80 | 127)
            cab += n.to_bytes(8, "big")
        mascara = os.urandom(4)
        cab += mascara
        self.s.sendall(bytes(cab) + bytes(b ^ mascara[i % 4] for i, b in enumerate(dados)))

    def _ler(self, n):
        while len(self.buf) < n:
            d = self.s.recv(65536)
            if not d:
                raise CDPErro("Chrome fechou a conexão")
            self.buf += d
        r, self.buf = self.buf[:n], self.buf[n:]
        return r

    def receber(self):
        msg = b""
        while True:
            b1, b2 = self._ler(2)
            op, n = b1 & 0x0F, b2 & 0x7F
            if n == 126:
                n = int.from_bytes(self._ler(2), "big")
            elif n == 127:
                n = int.from_bytes(self._ler(8), "big")
            if b2 & 0x80:
                m = self._ler(4)
                dados = bytes(x ^ m[i % 4] for i, x in enumerate(self._ler(n)))
            else:
                dados = self._ler(n)
            if op == 8:
                raise CDPErro("Chrome encerrou a conexão")
            if op in (9, 10):          # ping/pong
                continue
            msg += dados
            if b1 & 0x80:
                return msg.decode("utf-8", "replace")

    def fechar(self):
        try:
            self.s.close()
        except Exception:
            pass


class CDP:
    def __init__(self, ws_url):
        self.ws = _WS(ws_url)
        self.n = 0

    def call(self, metodo, **params):
        self.n += 1
        i = self.n
        self.ws.enviar(json.dumps({"id": i, "method": metodo, "params": params}))
        fim = time.time() + 20
        while time.time() < fim:
            r = json.loads(self.ws.receber())
            if r.get("id") == i:
                if "error" in r:
                    raise CDPErro(f"{metodo}: {r['error'].get('message')}")
                return r.get("result", {})
        raise CDPErro(f"{metodo}: sem resposta do Chrome")

    def fechar(self):
        self.ws.fechar()


def caminho_chrome(cfg):
    chrome = cfg.get("chrome_path") or ""
    if not os.path.isfile(chrome):          # config trazida de outro PC: procura o Chrome deste
        chrome = achar_chrome()
    if not chrome or not os.path.isfile(chrome):
        raise FileNotFoundError("chrome.exe não encontrado. Ajuste o caminho em Configurações.")
    return chrome


def perfil_compartilhado(cfg):
    return os.path.join(cfg.get("perfis_dir") or PERFIS_PADRAO, PERFIL_COMPARTILHADO)


def _porta_cdp(cfg):
    try:
        return int(cfg.get("cdp_porta", CDP_PORTA_PADRAO))
    except (TypeError, ValueError):
        return CDP_PORTA_PADRAO


def _cdp_get(porta, caminho):
    c = http.client.HTTPConnection("127.0.0.1", porta, timeout=2)   # direto, sem proxy do sistema
    try:
        c.request("GET", caminho)
        return json.loads(c.getresponse().read().decode("utf-8"))
    finally:
        c.close()


# ---- registro link -> janela (targetId) do Chrome compartilhado
def _arq_janelas(cfg):
    return os.path.join(cfg.get("perfis_dir") or PERFIS_PADRAO, "_janelas.json")


def _janelas(cfg):
    try:
        with open(_arq_janelas(cfg), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _ent(v):
    """Entrada do registro: {"t": targetId, "h": hwnd, "p": porta, "sep": bool, "m": device}."""
    if isinstance(v, dict):
        return v
    return {"t": v} if v else {}


def _janelas_salvar(cfg, dados):
    try:
        os.makedirs(os.path.dirname(_arq_janelas(cfg)), exist_ok=True)
        with open(_arq_janelas(cfg), "w", encoding="utf-8") as f:
            json.dump(dados, f)
    except Exception:
        pass


def navegador_compartilhado(cfg, mon=None):
    """Garante o Chrome compartilhado rodando com o CDP ativo. Retorna (url_ws, abas_iniciais)."""
    porta = _porta_cdp(cfg)
    try:
        return _cdp_get(porta, "/json/version")["webSocketDebuggerUrl"], []
    except Exception:
        pass
    perfil = perfil_compartilhado(cfg)
    fechar_pids(pids_do_painel(perfil))      # um Chrome desse perfil aberto sem o CDP: reinicia
    _janelas_salvar(cfg, {})
    os.makedirs(perfil, exist_ok=True)
    marcar_saida_limpa(perfil)
    limpar_abas_antigas(perfil)
    args = [caminho_chrome(cfg), f"--user-data-dir={perfil}",
            f"--remote-debugging-port={porta}",
            "--no-first-run", "--no-default-browser-check", "--disable-session-crashed-bubble",
            "--disable-features=Translate", "--new-window"]
    if mon:
        args += [f"--window-position={mon['x'] + 40},{mon['y'] + 40}", "--window-size=800,600"]
    args.append("about:blank")
    subprocess.Popen(args)
    fim = time.time() + 30
    while time.time() < fim:
        try:
            ws = _cdp_get(porta, "/json/version")["webSocketDebuggerUrl"]
            time.sleep(0.5)
            try:
                _restaurar_cookies(cfg, ws)
            except Exception:
                pass
            iniciais = [t["id"] for t in _cdp_get(porta, "/json/list") if t.get("type") == "page"]
            return ws, iniciais
        except Exception:
            time.sleep(0.3)
    raise CDPErro("O Chrome compartilhado não respondeu. Verifique se a porta "
                  f"{porta} está livre (Configurações → cdp_porta).")



# ---- guarda dos cookies de sessão (o login sobrevive ao fechar/reiniciar o Chrome e o PC)
class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(dados, proteger):
    """Criptografa/descriptografa com a DPAPI do Windows (só o mesmo usuário deste PC consegue abrir)."""
    if sys.platform != "win32":
        return dados
    buf = ctypes.create_string_buffer(dados, len(dados))
    entrada = _BLOB(len(dados), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    saida = _BLOB()
    f = ctypes.windll.crypt32.CryptProtectData if proteger else ctypes.windll.crypt32.CryptUnprotectData
    if not f(ctypes.byref(entrada), None, None, None, None, 0x1, ctypes.byref(saida)):
        raise OSError("DPAPI falhou")
    try:
        return ctypes.string_at(saida.pbData, saida.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(saida.pbData)


def _arq_sessao(cfg):
    return os.path.join(cfg.get("perfis_dir") or PERFIS_PADRAO, "_sessao.bin")


def salvar_cookies(cfg):
    """Guarda os cookies de sessão do Chrome compartilhado (o Chrome apagaria ao fechar)."""
    try:
        ws = _cdp_get(_porta_cdp(cfg), "/json/version")["webSocketDebuggerUrl"]
    except Exception:
        return -1
    try:
        with _TRAVA_CDP:
            c = CDP(ws)
            try:
                todos = c.call("Storage.getCookies").get("cookies", [])
            finally:
                c.fechar()
        sessao = [x for x in todos if x.get("session")]
        arq = _arq_sessao(cfg)
        tmp = arq + ".tmp"
        with open(tmp, "wb") as f:
            f.write(_dpapi(json.dumps(sessao).encode("utf-8"), True))
        os.replace(tmp, arq)
        return len(sessao)
    except Exception:
        return -1


def _restaurar_cookies(cfg, ws):
    arq = _arq_sessao(cfg)
    if not os.path.isfile(arq):
        return 0
    try:
        with open(arq, "rb") as f:
            sessao = json.loads(_dpapi(f.read(), False).decode("utf-8"))
    except Exception:
        return 0
    campos = ("name", "value", "domain", "path", "secure", "httpOnly", "sameSite", "priority",
              "sourceScheme", "sourcePort")
    params = [{k: x[k] for k in campos if k in x} for x in sessao if x.get("name") and x.get("domain")]
    if not params:
        return 0
    c = CDP(ws)
    try:
        try:
            c.call("Storage.setCookies", cookies=params)
            return len(params)
        except CDPErro:                       # algum cookie inválido: tenta um a um
            n = 0
            for prm in params:
                try:
                    c.call("Storage.setCookies", cookies=[prm])
                    n += 1
                except CDPErro:
                    pass
            return n
    finally:
        c.fechar()


def iniciar_guarda_cookies(obter_cfg, intervalo=60):
    def loop():
        while True:
            time.sleep(intervalo)
            try:
                salvar_cookies(obter_cfg())
            except Exception:
                pass
    threading.Thread(target=loop, daemon=True).start()


def _hwnds_de(pids):
    hs = set()
    for pid in pids:
        hs.update(janelas_do_pid(pid))
    return hs


def abrir_compartilhado(cfg, item, mon, kiosk=None, extras=()):
    usar_tela_cheia = item.get("kiosk", True) if kiosk is None else kiosk
    with _TRAVA_CDP:
        ws, iniciais = navegador_compartilhado(cfg, mon)
        cdp = CDP(ws)
        try:
            reg = _janelas(cfg)
            antigo = _ent(reg.pop(item["id"], None)).get("t")
            if antigo:
                try:
                    cdp.call("Target.closeTarget", targetId=antigo)
                except CDPErro:
                    pass
            pids = pids_do_painel(perfil_compartilhado(cfg))
            antes = _hwnds_de(pids)
            alvo = cdp.call("Target.createTarget", url=item["url"], newWindow=True)["targetId"]
            janela = cdp.call("Browser.getWindowForTarget", targetId=alvo)["windowId"]
            # 1) posiciona (em DIP) no centro do monitor de destino
            esc = float(mon.get("escala") or 1.0)
            w, h = int(mon["w"] * 0.7 / esc), int(mon["h"] * 0.7 / esc)
            cx, cy = (mon["x"] + mon["w"] / 2) / esc, (mon["y"] + mon["h"] / 2) / esc
            cdp.call("Browser.setWindowBounds", windowId=janela, bounds={"windowState": "normal"})
            cdp.call("Browser.setWindowBounds", windowId=janela,
                     bounds={"left": int(cx - w / 2), "top": int(cy - h / 2), "width": w, "height": h})
            # 2) correção em pixels físicos pelo Windows (cobre monitores com escalas diferentes)
            fim = time.time() + 4
            novos = set()
            while time.time() < fim and not novos:
                novos = _hwnds_de(pids) - antes
                if not novos:
                    time.sleep(0.25)
            for hwnd in novos:
                pw, ph = int(mon["w"] * 0.7), int(mon["h"] * 0.7)
                user32.SetWindowPos(hwnd, 0, mon["x"] + (mon["w"] - pw) // 2, mon["y"] + (mon["h"] - ph) // 2,
                                    pw, ph, 0x0004 | 0x0040)
            time.sleep(0.3)
            # 3) tela cheia (sem barra/abas) ou janela maximizada
            cdp.call("Browser.setWindowBounds", windowId=janela,
                     bounds={"windowState": "fullscreen" if usar_tela_cheia else ("normal" if extras else "maximized")})
            for url in extras:                       # ex.: aba de configurações no modo Login
                cdp.call("Target.createTarget", url=url)
            for t in iniciais:                       # fecha a aba about:blank inicial
                try:
                    cdp.call("Target.closeTarget", targetId=t)
                except CDPErro:
                    pass
            reg = _janelas(cfg)
            reg[item["id"]] = {"t": alvo, "h": int(next(iter(novos), 0) or 0), "m": mon["device"]}
            _janelas_salvar(cfg, reg)
            return alvo
        finally:
            cdp.fechar()


def fechar_compartilhado(cfg, link_id):
    with _TRAVA_CDP:
        reg = _janelas(cfg)
        alvo = _ent(reg.pop(link_id, None)).get("t")
        _janelas_salvar(cfg, reg)
        if not alvo:
            return False
        try:
            ws = _cdp_get(_porta_cdp(cfg), "/json/version")["webSocketDebuggerUrl"]
        except Exception:
            return False
        cdp = CDP(ws)
        try:
            cdp.call("Target.closeTarget", targetId=alvo)
            return True
        except CDPErro:
            return False
        finally:
            cdp.fechar()


def recarregar_telas(cfg):
    """Recarrega todas as janelas do painel (útil depois de fazer login)."""
    try:
        alvos = [t for t in _cdp_get(_porta_cdp(cfg), "/json/list") if t.get("type") == "page"]
    except Exception:
        alvos = []
    for e in _janelas(cfg).values():
        e = _ent(e)
        if e.get("sep") and e.get("p"):
            try:
                alvos += [t for t in _cdp_get(e["p"], "/json/list") if t.get("type") == "page"]
            except Exception:
                pass
    n = 0
    for t in alvos:
        if not t.get("webSocketDebuggerUrl") or t.get("url", "").startswith("chrome://"):
            continue
        try:
            c = CDP(t["webSocketDebuggerUrl"])
            try:
                c.call("Page.reload", ignoreCache=False)
                n += 1
            finally:
                c.fechar()
        except Exception:
            pass
    return n


# ---- alterações aplicadas na hora (sem reiniciar as outras telas)
def _paginas(porta):
    try:
        return [t for t in _cdp_get(porta, "/json/list") if t.get("type") == "page"]
    except Exception:
        return []


def _pagina_do_link(cfg, link_id):
    """(url_ws_da_pagina) da janela aberta de um link, ou None."""
    e = _ent(_janelas(cfg).get(link_id))
    if not e:
        return None
    if e.get("sep"):
        pgs = [t for t in _paginas(e.get("p") or 0) if not t.get("url", "").startswith("chrome://")]
        return pgs[0].get("webSocketDebuggerUrl") if pgs else None
    alvo = e.get("t")
    for t in _paginas(_porta_cdp(cfg)):
        if t.get("id") == alvo:
            return t.get("webSocketDebuggerUrl")
    return None


def recarregar_link(cfg, link_id):
    ws = _pagina_do_link(cfg, link_id)
    if not ws:
        return False
    try:
        c = CDP(ws)
        try:
            c.call("Page.reload", ignoreCache=False)
            return True
        finally:
            c.fechar()
    except Exception:
        return False


def navegar_link(cfg, link_id, url):
    ws = _pagina_do_link(cfg, link_id)
    if not ws:
        return False
    try:
        c = CDP(ws)
        try:
            c.call("Page.navigate", url=url)
            return True
        finally:
            c.fechar()
    except Exception:
        return False


def mover_compartilhado(cfg, link_id, mon, tela_cheia=True):
    """Leva a janela de um link (Chrome compartilhado) para outro monitor, sem recarregar a página."""
    with _TRAVA_CDP:
        reg = _janelas(cfg)
        e = _ent(reg.get(link_id))
        if not e.get("t"):
            return False
        try:
            ws = _cdp_get(_porta_cdp(cfg), "/json/version")["webSocketDebuggerUrl"]
        except Exception:
            return False
        c = CDP(ws)
        try:
            janela = c.call("Browser.getWindowForTarget", targetId=e["t"])["windowId"]
            esc = float(mon.get("escala") or 1.0)
            w, h = int(mon["w"] * 0.7 / esc), int(mon["h"] * 0.7 / esc)
            cx, cy = (mon["x"] + mon["w"] / 2) / esc, (mon["y"] + mon["h"] / 2) / esc
            c.call("Browser.setWindowBounds", windowId=janela, bounds={"windowState": "normal"})
            time.sleep(0.3)
            c.call("Browser.setWindowBounds", windowId=janela,
                   bounds={"left": int(cx - w / 2), "top": int(cy - h / 2), "width": w, "height": h})
            hwnd = int(e.get("h") or 0)
            if hwnd and user32.IsWindow(hwnd):
                pw, ph = int(mon["w"] * 0.7), int(mon["h"] * 0.7)
                user32.SetWindowPos(hwnd, 0, mon["x"] + (mon["w"] - pw) // 2, mon["y"] + (mon["h"] - ph) // 2,
                                    pw, ph, 0x0004 | 0x0040)
            time.sleep(0.3)
            c.call("Browser.setWindowBounds", windowId=janela,
                   bounds={"windowState": "fullscreen" if tela_cheia else "maximized"})
            e["m"] = mon["device"]
            reg[link_id] = e
            _janelas_salvar(cfg, reg)
            return True
        except CDPErro:
            return False
        finally:
            c.fechar()


def aplicar_mudancas(antigo, novo, log=lambda m: None):
    """Compara a configuração anterior com a nova e mexe SÓ nas telas afetadas."""
    mons = listar_monitores()
    reg = _janelas(novo)
    if not reg:                       # painel não está aberto: nada para aplicar agora
        return
    velhos = {x["id"]: x for x in antigo.get("links", [])}
    novos_ids = {x["id"] for x in novo.get("links", [])}
    for lid in list(reg):             # links removidos
        if lid not in novos_ids:
            fechar_perfil(antigo, lid)
            log("Tela removida fechada.")
    for it in novo.get("links", []):
        lid, v = it["id"], velhos.get(it["id"], {})
        aberto = lid in _janelas(novo)
        nome = it.get("nome") or it.get("url")
        try:
            if aberto and (not it.get("ativo", True) or not it.get("url")):
                fechar_perfil(novo, lid)
                log(f"'{nome}' fechado (desativado).")
                continue
            if not aberto:
                if it.get("ativo", True) and it.get("url") and (not v or not v.get("ativo", True) or not v.get("url")):
                    m = resolver_monitor(it, mons)
                    if m:
                        abrir_link(novo, it, m)
                        log(f"'{nome}' aberto na Tela {m['num']}.")
                continue
            m = resolver_monitor(it, mons)
            m_velho = resolver_monitor(v, mons) if v else None
            if not m:
                continue
            reabrir = (bool(it.get("perfil_separado")) != bool(v.get("perfil_separado"))
                       or bool(it.get("kiosk", True)) != bool(v.get("kiosk", True))
                       or (it.get("perfil_separado") and (m_velho is None or m["device"] != m_velho["device"])))
            if reabrir:
                fechar_perfil(v or novo, lid)
                abrir_link(novo, it, m)
                log(f"'{nome}' reaberto na Tela {m['num']}.")
                continue
            if m_velho is None or m["device"] != m_velho["device"]:
                if not mover_compartilhado(novo, lid, m, it.get("kiosk", True)):
                    fechar_perfil(novo, lid)
                    abrir_link(novo, it, m)
                log(f"'{nome}' movido para a Tela {m['num']}.")
            if it.get("url") != v.get("url"):
                if not navegar_link(novo, lid, it["url"]):
                    fechar_perfil(novo, lid)
                    abrir_link(novo, it, m)
                log(f"'{nome}': nova URL aplicada.")
        except Exception as e:
            log(f"[ERRO] {nome}: {e}")


_TRAVA_APLICAR = threading.Lock()


def aplicar_mudancas_async(antigo, novo, log=lambda m: None):
    a, n = json.loads(json.dumps(antigo)), json.loads(json.dumps(novo))

    def tarefa():
        with _TRAVA_APLICAR:
            aplicar_mudancas(a, n, log)
    threading.Thread(target=tarefa, daemon=True).start()


# ---- auto refresh por link
REFRESH_MIN_S = 5


def iniciar_auto_refresh(obter_cfg):
    ultimo = {}          # link_id -> (marca_da_janela, instante do último refresh)

    def loop():
        while True:
            time.sleep(1)
            try:
                cfg = obter_cfg()
                reg = _janelas(cfg)
                agora = time.time()
                for it in cfg.get("links", []):
                    lid = it.get("id")
                    if not it.get("auto_refresh") or lid not in reg:
                        ultimo.pop(lid, None)
                        continue
                    try:
                        intervalo = max(REFRESH_MIN_S, int(it.get("refresh_s") or 300))
                    except (TypeError, ValueError):
                        intervalo = 300
                    marca = json.dumps(reg[lid], sort_keys=True)
                    m0, t0 = ultimo.get(lid, (None, agora))
                    if m0 != marca:                 # janela nova: começa a contar agora
                        ultimo[lid] = (marca, agora)
                        continue
                    if agora - t0 >= intervalo:
                        recarregar_link(cfg, lid)
                        ultimo[lid] = (marca, agora)
            except Exception:
                pass
    threading.Thread(target=loop, daemon=True).start()


# ---- acesso remoto a UMA tela (imagem ao vivo + mouse/teclado), sem RDP e sem mexer nas outras
class SessaoCDP:
    """Conexão CDP persistente com leitor em thread (necessária para receber os quadros da tela)."""

    def __init__(self, ws_url, ao_evento):
        self.ws = _WS(ws_url)
        self.ws.s.settimeout(None)
        self.ao_evento = ao_evento
        self.pend = {}
        self.n = 0
        self.trava = threading.Lock()
        self.viva = True
        threading.Thread(target=self._ler, daemon=True).start()

    def _ler(self):
        try:
            while self.viva:
                m = json.loads(self.ws.receber())
                if "id" in m:
                    item = self.pend.pop(m["id"], None)
                    if item:
                        item[1] = m
                        item[0].set()
                else:
                    try:
                        self.ao_evento(m)
                    except Exception:
                        pass
        except Exception:
            pass
        self.viva = False
        for item in list(self.pend.values()):
            item[0].set()

    def _enviar(self, metodo, params, esperar):
        with self.trava:
            self.n += 1
            i = self.n
            item = [threading.Event(), None]
            if esperar:
                self.pend[i] = item
            self.ws.enviar(json.dumps({"id": i, "method": metodo, "params": params}))
        if not esperar:
            return None
        if not item[0].wait(10) or not item[1]:
            raise CDPErro(f"{metodo}: sem resposta")
        if "error" in item[1]:
            raise CDPErro(f"{metodo}: {item[1]['error'].get('message')}")
        return item[1].get("result", {})

    def call(self, metodo, **params):
        return self._enviar(metodo, params, True)

    def notificar(self, metodo, **params):
        if self.viva:
            self._enviar(metodo, params, False)

    def fechar(self):
        self.viva = False
        self.ws.fechar()


class AcessoRemoto:
    def __init__(self, cfg, link_id):
        ws = _pagina_do_link(cfg, link_id)
        if not ws:
            raise ValueError("Essa tela não está aberta. Abra o painel (ou clique em Abrir) antes de acessar.")
        self.link_id = link_id
        self.cond = threading.Condition()
        self.quadro, self.meta, self.seq = None, {}, 0
        self.ultimo_uso = time.time()
        self.s = SessaoCDP(ws, self._evento)
        self.s.call("Page.enable")
        self.s.call("Page.startScreencast", format="jpeg", quality=65, maxWidth=1920, maxHeight=1080,
                    everyNthFrame=1)

    @property
    def viva(self):
        return self.s.viva

    def _evento(self, m):
        if m.get("method") == "Page.screencastFrame":
            p = m["params"]
            self.s.notificar("Page.screencastFrameAck", sessionId=p["sessionId"])
            with self.cond:
                self.quadro = base64.b64decode(p["data"])
                self.meta = p.get("metadata", {})
                self.seq += 1
                self.cond.notify_all()
        elif m.get("method") in ("Inspector.detached", "Target.targetDestroyed"):
            self.s.viva = False

    def _foto(self):
        """Página parada não gera quadros novos: tira uma foto para começar."""
        r = self.s.call("Page.captureScreenshot", format="jpeg", quality=65)
        lm = self.s.call("Page.getLayoutMetrics")
        vp = lm.get("cssVisualViewport") or lm.get("visualViewport") or {}
        with self.cond:
            self.quadro = base64.b64decode(r["data"])
            self.meta = {"deviceWidth": vp.get("clientWidth"), "deviceHeight": vp.get("clientHeight")}
            self.seq += 1
            self.cond.notify_all()

    def quadro_apos(self, seq, espera=8.0):
        self.ultimo_uso = time.time()
        with self.cond:
            if self.quadro is None:
                self.cond.wait(1.5)
        if self.quadro is None:
            self._foto()
        with self.cond:
            if self.seq <= seq and self.viva:
                self.cond.wait_for(lambda: self.seq > seq or not self.viva, espera)
            self.ultimo_uso = time.time()
            return self.seq, self.quadro, dict(self.meta)

    def entrada(self, eventos):
        self.ultimo_uso = time.time()
        botoes = {"left": 1, "right": 2, "middle": 4}
        for ev in eventos[:200]:
            t = ev.get("t")
            mods = int(ev.get("mods") or 0)
            if t in ("move", "down", "up", "wheel"):
                x, y = float(ev.get("x", 0)), float(ev.get("y", 0))
                btn = ev.get("btn") or "left"
                if t == "move":
                    self.s.notificar("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y, modifiers=mods,
                                     button=btn if ev.get("b") else "none", buttons=int(ev.get("b") or 0))
                elif t in ("down", "up"):
                    self.s.notificar("Input.dispatchMouseEvent", type="mousePressed" if t == "down" else "mouseReleased",
                                     x=x, y=y, button=btn, buttons=botoes.get(btn, 1) if t == "down" else 0,
                                     clickCount=int(ev.get("n") or 1), modifiers=mods)
                else:
                    self.s.notificar("Input.dispatchMouseEvent", type="mouseWheel", x=x, y=y, modifiers=mods,
                                     deltaX=float(ev.get("dx", 0)), deltaY=float(ev.get("dy", 0)))
            elif t == "key":
                base = {"key": str(ev.get("key", ""))[:32], "code": str(ev.get("code", ""))[:32],
                        "windowsVirtualKeyCode": int(ev.get("kc") or 0), "modifiers": mods}
                texto = str(ev.get("text") or "")[:8]
                if ev.get("tipo") == "up":
                    self.s.notificar("Input.dispatchKeyEvent", type="keyUp", **base)
                elif texto and not (mods & 0b011):          # sem Ctrl/Alt: tecla que digita
                    self.s.notificar("Input.dispatchKeyEvent", type="keyDown", text=texto, unmodifiedText=texto, **base)
                else:
                    self.s.notificar("Input.dispatchKeyEvent", type="rawKeyDown", **base)
            elif t == "texto":
                self.s.notificar("Input.insertText", text=str(ev.get("v") or "")[:5000])
            elif t == "recarregar":
                self.s.notificar("Page.reload", ignoreCache=False)

    def fechar(self):
        try:
            self.s.notificar("Page.stopScreencast")
        except Exception:
            pass
        self.s.fechar()


class GerenciadorRemoto:
    OCIOSO_S = 25

    def __init__(self):
        self.sessoes = {}
        self.trava = threading.Lock()
        threading.Thread(target=self._limpar, daemon=True).start()

    def obter(self, cfg, link_id, criar=True):
        with self.trava:
            s = self.sessoes.get(link_id)
            if s and not s.viva:
                s.fechar()
                s = None
                self.sessoes.pop(link_id, None)
            if not s and criar:
                s = AcessoRemoto(cfg, link_id)
                self.sessoes[link_id] = s
            return s

    def encerrar(self, link_id):
        with self.trava:
            s = self.sessoes.pop(link_id, None)
        if s:
            s.fechar()

    def _limpar(self):
        while True:
            time.sleep(5)
            agora = time.time()
            with self.trava:
                velhas = [k for k, s in self.sessoes.items() if not s.viva or agora - s.ultimo_uso > self.OCIOSO_S]
                fora = [self.sessoes.pop(k) for k in velhas]
            for s in fora:
                try:
                    s.fechar()
                except Exception:
                    pass


REMOTO = GerenciadorRemoto()


def _item_do_link(cfg, link_id):
    return next((x for x in cfg.get("links", []) if x.get("id") == link_id), {})


def fechar_perfil(cfg, link_id):
    """Fecha apenas a janela do painel de um link específico."""
    if not _item_do_link(cfg, link_id).get("perfil_separado"):
        fechar_compartilhado(cfg, link_id)
        return
    alvo = os.path.join(cfg.get("perfis_dir") or PERFIS_PADRAO, link_id)
    fechar_pids(pids_do_painel(alvo))
    with _TRAVA_CDP:
        reg = _janelas(cfg)
        reg.pop(link_id, None)
        _janelas_salvar(cfg, reg)


def fechar_tela_sob_mouse():
    """Atalho global: fecha a janela do painel que está sob o cursor do mouse."""
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    user32.WindowFromPoint.restype = wintypes.HWND
    hwnd = user32.WindowFromPoint(pt)
    if not hwnd:
        return False
    raiz = user32.GetAncestor(hwnd, 2)  # GA_ROOT
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(raiz, ctypes.byref(pid))
    if pid.value in pids_do_painel():
        user32.PostMessageW(raiz, 0x0010, 0, 0)  # WM_CLOSE
        return True
    return False


def iniciar_atalho_global(callback):
    """Registra Ctrl+Alt+Q (global) numa thread própria."""
    def loop():
        MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, VK_Q, WM_HOTKEY = 0x1, 0x2, 0x4000, 0x51, 0x0312
        if not user32.RegisterHotKey(None, 1, MOD_ALT | MOD_CONTROL | MOD_NOREPEAT, VK_Q):
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                try:
                    callback()
                except Exception:
                    pass
    threading.Thread(target=loop, daemon=True).start()


def limpar_abas_antigas(perfil_dir):
    """Com 'Continuar de onde parou' o Chrome reabriria as abas antigas; apagamos só a lista de abas
    (pasta Sessions). Os cookies/login ficam intactos."""
    import shutil
    base = os.path.join(perfil_dir, "Default")
    shutil.rmtree(os.path.join(base, "Sessions"), ignore_errors=True)
    for nome in ("Current Session", "Current Tabs", "Last Session", "Last Tabs"):
        try:
            os.remove(os.path.join(base, nome))
        except OSError:
            pass


def abrir_link(cfg, item, mon, kiosk=None, extras=()):
    """Login compartilhado (padrão) ou perfil próprio quando o link está marcado 'Login separado'."""
    if not item.get("perfil_separado"):
        return abrir_compartilhado(cfg, item, mon, kiosk=kiosk, extras=extras)
    return abrir_separado(cfg, item, mon, kiosk=kiosk, extras=extras)


def abrir_separado(cfg, item, mon, kiosk=None, extras=()):
    chrome = caminho_chrome(cfg)
    perfil = os.path.join(cfg.get("perfis_dir") or PERFIS_PADRAO, item["id"])
    os.makedirs(perfil, exist_ok=True)
    marcar_saida_limpa(perfil)
    usar_kiosk = item.get("kiosk", True) if kiosk is None else kiosk
    if not extras:
        limpar_abas_antigas(perfil)
    args = [
        chrome,
        f"--user-data-dir={perfil}",
        f"--window-position={mon['x']},{mon['y']}",
        f"--window-size={mon['w']},{mon['h']}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        "--disable-features=Translate",
        "--new-window",
    ]
    if usar_kiosk:
        args.append("--kiosk")
    porta = _porta_livre()
    if porta:
        args.append(f"--remote-debugging-port={porta}")
    args.append(item["url"])
    args.extend(extras)
    p = subprocess.Popen(args)
    with _TRAVA_CDP:
        reg = _janelas(cfg)
        reg[item["id"]] = {"sep": True, "p": porta, "m": mon["device"]}
        _janelas_salvar(cfg, reg)
    garantir_posicao(p.pid, mon)
    return p


def _porta_livre():
    try:
        sk = _socket.socket()
        sk.bind(("127.0.0.1", 0))
        porta = sk.getsockname()[1]
        sk.close()
        return porta
    except Exception:
        return 0


def abrir_todos(cfg, monitores, log=print):
    with _TRAVA_APLICAR:          # não roda junto com uma aplicação de mudanças
        _abrir_todos(cfg, monitores, log)


def _abrir_todos(cfg, monitores, log=print):
    fechar_paineis(cfg)
    for item in cfg["links"]:
        if not item.get("ativo", True) or not item.get("url"):
            continue
        mon = resolver_monitor(item, monitores)
        if not mon:
            log(f"[!] '{item.get('nome') or item['url']}': tela {item.get('monitor')} não encontrada — pulado")
            continue
        log(f"Abrindo '{item.get('nome') or item['url']}' na Tela {mon['num']}...")
        try:
            abrir_link(cfg, item, mon)
        except Exception as e:
            log(f"[ERRO] {e}")
            return
        time.sleep(float(cfg.get("atraso_s", 1.5)))
    log("Concluído.")


# --------------------------------------------------------------------------- config
_TRAVA_CFG = threading.RLock()


def carregar_config(monitores):
    with _TRAVA_CFG:
        if os.path.isfile(CONFIG_PATH):
            erro = None
            for _ in range(5):          # tolera leitura no meio de uma gravação
                try:
                    with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
                        cfg = json.load(f)
                    mudou = False
                    if "links" not in cfg:      # config criada pelo instalador (só senha/porta)
                        cfg["links"] = [{"id": uuid.uuid4().hex[:8], "nome": f"Painel {m['num']}", "url": "",
                                         "monitor": m["device"], "kiosk": True, "ativo": True} for m in monitores]
                        mudou = True
                    if _aplicar_senha_pendente(cfg):
                        mudou = True
                    if mudou:
                        salvar_config(cfg)
                    cfg_web(cfg)
                    return cfg
                except Exception as e:
                    erro = e
                    time.sleep(0.1)
            raise RuntimeError(f"painel_config.json inválido: {erro}")
        # primeira execução: um link vazio por monitor detectado (já grava, para os IDs ficarem fixos)
        cfg = {
            "chrome_path": achar_chrome(),
            "perfis_dir": PERFIS_PADRAO,
            "atraso_s": 1.5,
            "links": [{"id": uuid.uuid4().hex[:8], "nome": f"Painel {m['num']}", "url": "",
                       "monitor": m["device"], "kiosk": True, "ativo": True} for m in monitores],
        }
        _aplicar_senha_pendente(cfg)
        cfg_web(cfg)
        salvar_config(cfg)
        return cfg


def salvar_config(cfg):
    with _TRAVA_CFG:
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)


def comando_inicializacao():
    """(programa, argumentos) para o atalho de inicialização. Espera 20 s para a rede/monitores subirem."""
    if getattr(sys, "frozen", False):
        return sys.executable, "--auto --espera=20"
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.isfile(pyw):
        pyw = sys.executable
    return pyw, f'"{os.path.abspath(__file__)}" --auto --espera=20'


def criar_atalho(lnk, alvo, args, icone=""):
    """Cria um atalho .lnk (sem janela de console) via WScript.Shell."""
    q = lambda t: t.replace("'", "''")
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{q(lnk)}');"
          f"$s.TargetPath='{q(alvo)}';$s.Arguments='{q(args)}';"
          f"$s.WorkingDirectory='{q(BASE_DIR)}';$s.WindowStyle=7;"
          + (f"$s.IconLocation='{q(icone)}';" if icone else "") + "$s.Save()")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                       capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    if r.returncode != 0 or not os.path.isfile(lnk):
        raise RuntimeError("Não foi possível criar o atalho: " + (r.stderr or r.stdout).strip()[:300])


# --------------------------------------------------------------------------- marca dashmgr (PNG em base64)
LOGO_HEADER = (
    "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"
)
LOGO_OVERLAY = (
    "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"
)
LOGO_COR = (
    "iVBORw0KGgoAAAANSUhEUgAAAHwAAAAaCAYAAAB1szj5AAAWYUlEQVR42u1aZ5hV1dV+197nnFtn7p1emBlqQEUEBQtqgLFjLKCC"
    "MXYUY48aFY3f54CNIJpoiCZqhCjGyKCAVBO6AqL0JtIHmcr0uf2Uvb4fd2aYURRJ+fWxnmeeOWfftffZ57x7tXdvAphQAsIEMECM"
    "Y0kJCwBiKICVANAXjNHCAY7RdeBA3XvX9EwEvHnCk1ooSfYUEL1Iyt4sZA8IZcvm8A11o7M2gFmASHXqz0wYDwIgMAxALRijycEJ"
    "OS6hTnelLJEFQi0YO8YzJkzo/NHB9H2LouDhUg93G5ChdH8OGe4ulkt0VR6ju+VCdylEETMVkNSykSJARnJ5kA1QyAIrbqRMI02V"
    "t0xsHBn4Ddazjnlw0BeELBCGQX1nAZyQf0k0lJRoGX3GZNf/omvlUS2m4yIYTU7O4wf7ykB6Pwnu5uhadyHR09FlV9tFBSJVd5Mf"
    "IC+gaUBCASJqsWJVBeYDQsVWiCY+IJRzgDlxUFdWtVN1sNL0udzsGljGuibATAAcDOoM8NChJdrGG8f2iPv9A4Qh+xuh8JrQ7XkL"
    "TkB4nIDrJz1aGvN5Rrg/ShwmONvYUasE2Z+z1bw99q1FkPtk2Sl6Su4GGTRcigBhA6zMMCQqQOpTjkcO2DF1QLisg0q3y22nuUoe"
    "PFjX9MTFzT80ibTF+wICICIIEDFGleopfzvUNYHAaSTEeSz0sz8H+pHHSJEMsARMU7YACJyA8DgB1wzjUpj2KsH2Bkdo5wtNPgGP"
    "zw07AO9ss0LA3mQLrHFCoUXYFMqTqYZLNIZKbKdpNjmR+lR8UPfVhAnm0eIEd47BAgAN3ABxbirEGRWbPbnBYHD46d3LLMsxdB0w"
    "BDXqU+uv13JS37RsLVUQgLjZwqy2M6s3EIp9iZbGdbY3eId0+35zAr5/AXDFzLqyl4RH+59pA0v/2+GfCN04SzOMn5o2DRSGeFq6"
    "PcN0p+45EDhmW0urSoq2dYK4VEnsAA28ErRhEFkAMKqU5cxRUCAARIqZBQbCISKrtiEyN5DqvYTLyvJp2oFQWvFPELOU1B00k22/"
    "abVEP3OJxM7Qjdl7vjPpaQ1xgMUJ+P4FMWbEIp4PIi9iOWuuRVXdvNsa+g9dXqJ1Unp1ocv31tac3KcOXNb1T8xdX2y6DCUs8MZ6"
    "PZnItRkxawCwfXfZKdv27CkEgPXrWWdm0fYbADQ0RSZHoonappbIYt60KZhWui8QXMYcnBd58dvzO+mFrzJyds08G5MmpQAElLAw"
    "pjU8bXxg8vG8JxFB05JTeHzck5fW1NRUbtm+c2NGRqZs+72j7o8ds02klACA1//85v01NTWVnyxe9vbxjvefyLuPpau1dygmm9e2"
    "jFYB/6QvE+N2G/NvG0HxtFuduFOWWxN5p3xsUY3nN3vJ0ADWoDCBFEqZmIGZM1mOGgUmInvtlt0FfXp13ZGIm7WbN+89dcAAOtz6"
    "NLVtT3lhQU7mTCkQrT1cdVq3bt2qAMA/9+tMHQCzYpSwKOgLl9xRxnHOmRWyI3HkuAbl3Xu+bl734VX1PWmdM61eyB8Jt5QSSikw"
    "c/t9SkqqLzs7O4+h60KIdlCEkFDKATO33ov2awBwHOd7x2zTyUhLC2RnZ+dlZdRkSSnBzFBKQQgBImofA0IAREfinmprlwArgMR3"
    "25g7vhigWtuIkvpovVac1BeyQ3AlQDnQoNDuHTVNE5xBgOnpTYcS+fAGxunpQENN8+dg3qo9W06sAUwOdVi9DMABgLrmyEO6kA9E"
    "IonPwMrq0TN/bX1j5P2WptD8lICnt667fqsUv5nq94xPFgAsRxMpshUzAAUAE0iVAzHvJ+E/6pX6Tz2bcQFi4Sj50t+RwcAcAF1I"
    "SYd/JOBtH1jTNNi2DQCwbctmZli2lQCSgCaBsTvptoPzLav+9pgd9SxH2cwMZlZt7UIIKKXa+zNzEqyjSRvI7Hy3rfOLHQHecTrr"
    "f18/ImiwGW1vyk3R6Wq3VcOmSjNrm3a5fKEZjvD2gVRRELH9wgHoBgCtdeWMHs/Ll6/PPOW0XoPchusFBkKxSPjG3NzMtQBwsKq+"
    "b4rX9Vy3bjlPxU2FuoaW4sK8tBXMLMePH8+jkxhzW4UvKOlu0qfvTg3r4k6re8ttzWOy1uEPQNaad39O/bvvyY9P6lP9pgxrHnFM"
    "d8vMGHvXL/tfN2rU3dnZeT9paW6qfPfdv75s6IY7acEkiJJWLKXEvffef/bIkdfcGczI6NlYV7d36rS3X2psbIredtutY+rqW1qe"
    "HPfwq83NzfyLG2/qc8stN9+Xl9+1fyQSOrxm1acfTp48+cOammpHk0IjIsRNM3755Vd0ueeeux/MyS/q21BXs/+tt9565aMPS/cD"
    "gH7VfYP1wcMutrds+IJDTbXisjFPACC1+L3J9idvrpNXPzREnD/yHhKay1m3aKoz4/l5bMbbLVa/8t4ztCHX3638aV3RVLXDmfXq"
    "S1qv0/uj34Az1dIFH1lfzttpPPD6k6SY7H9OfVs7b9SV6DPoahjvxCKev8YmAoBrbe0FnoORydqnlfdi0qoU30tlF7p+V3YBSpa7"
    "ASDrhQOXFbzP3Pvt5uEAUFZe/5hpWonmUHR/XUPzrR1iuVzeIWY3h6JzDlU3PwQA05azu5WtQ2vNjZRZX2UEljGntsZwT+mmLsaK"
    "sOOZUzkIJSzATD33TC3MDa/mAp7ST7waesj4m83HcuVvT33313wUqappqDVt5urDDY2ZWVlS0zTMmj1v0tF0K6rrq5mZbYfZ4/HQ"
    "7XeM7Xc0vbJDlXtTUlLovff+/igzc/XhplrT+a7e7Xfe3R8A/M/MeyllM7NvkWLfambfF8y+Fcy+xczuKZsX+VYx+9Yye5Yy+9cy"
    "ux57/zEAICHhGff+OP8qZt9nzP7Pmf0bmf1LmFPnW+zfwux+8K27RE5Xw7+a2b+cOWV2OOb/ktm/ilm05lwCAJTLPwRF3keNLnmv"
    "ubvnn+F4cxfL9K5LfZ6CngDAEoIF4KhWh6qhiZkP1dc2DM9MD7zDzCSS1uUUE9nUmlIEUrwjCnMDrxCA24spjgnfZc2SZp78F9sx"
    "pwousV8VZIzDBFIg4lDslOEctSvL8cAOoTteWD9MvN1zz31njbn95peiCVZf797/RcmE56549tmJV+89cGhrdnZaplKApmlGc1OT"
    "c+/9Dw4eOeKKx2Mmqy3bvl759PhnLn9x8sujyysPH8jJTs+JxCyzpra+wuPx0NixY592HMdc8Mni13r37u259tpR3bds3b74L2++"
    "cY9pmiw0qQNAMJia2djQfHjqtOmPLF+5enrcVEhYyn7q6ZLZmiZghhsr0GiZgFL20gUvJt6YNFLVNVSx6ZjytP6XOVu2LUz88Zkr"
    "sO+rpdzkmPpFN7wogtlSDBndU151w29VGHC2bvrYfGVcsTll4ginoa7CkWRSo2UiEWmBUkwhy+SWRFQFfG576bLX4n95/loNigFS"
    "SQBN84Aq16opbMVIcZRJ1bLlZBPsdv/JOhCVyZjdLTfjLQBvAcADry500fgVFPjVNDdyexGK+kHbvc+j2dKV2qUbWQlLb6pvcGsy"
    "TRq6roJWxVdfAVbHXJPRCuL48awvqb/HyU9b7F4fqxGK9JYGW7P3r74YI6DoNcc4FtF65133vKiUsmuqyrcVDz3/vOrqKgcA/vKX"
    "Py9a+dnqjYUFBafalhUOBtO0m26+5X+UUvbeXbtWDhty3iVNTY0KAKZNmzp/xcpPd2ZkZHSVQmit7LKQUhoZGRldevc5KX3p0sUH"
    "Z8368JK25wqCBADLjIevHXnlyatWfdYAAIsWLWm5+NIL78vNzu6el5MlD8UTcZdXN3j/7lWJ8VePg3JAiWjEuGvCP9Eci5q/u2W0"
    "2rc5ojYv+dzzu5X1kKxQ2CegD/n5bayUzd98vTz+6JCRiIUZAOSa2cs9Ly7ZxympmSCSrY7fEAEY5j9mPJ6Y+PPJrfMDoIQDANbZ"
    "gXcShXpevL+3R+znPdfFP5jRNfbR+kDkiZO3AQBpUKwDLBwNAPKmHr6zcLZZ3mV6uPbDjGGVeT3PqfT2u67cl3n6IU/Y+EZknbzH"
    "Se+1symi7Yhavo2ar8sa8vg+M4X+zwr48kEdePnODpoiF2cuifs3d1Gpzh/tVPWqym0+yx5x6RcAwDYr/mGPjvz8LmcKIbQZpR9O"
    "rK6uctxuD9xuN7755htrxozS56UAIrF4U3Z2tjszM6uXEEJ7973pzzc1NSqPJ6n79c6vYvPnz39Za03kY7EYv/LK7x4HgHPOPGPE"
    "/HlzK/aXVbQs/OQfL1108aXZHZ+/Z+/+NatWfdZgGAYAYOmyJR9IAhyllNA0AismDVCHv9kE5QBSAx/+ppwEwNFoiOur4pAauKUu"
    "goQCCxLkD/pUMLOrcAnNWjPndcTCDLcP0F1wdq1rMXdvmic8AJRyuO2DEuAsnf5esgZ3Q+uY3KV+VHujN8WfomylCHA5CgnNBWmP"
    "OdxQNzp7Bns0Yg1Qgm0AMFVsoR6nA4iHHWlaDCMlxkIkuKlO2HGbNFcgzjZHnXjMELawKJAWE5EqZcbtRPOkQc1gpjbQCQBxcv35"
    "x1em+55qvFr8UUW1hthmBXZUWrCPGlebXzMpaxkcQTiGhStlx5nZm5mZmQMAlnWEDMzOzs4DAClIOo6jHJV8n+zMzOykrtWeeadn"
    "ZHQBAEc5VmogIEpn/H3f1q1bvL+8666rhwy78Nb+/U+9bPill/z6wgsu/PVJfXq7Y9FYEwAkLDNMRFBKtZZ41Pr9SXQur4RMomID"
    "UtOYWgOslNTaJphaPaCZsEQiEWLbUbJb//NsYA7ikeS4bi/pOd1PZ7ND5U+tybtjtZYnFjRWR2KnDnESO3Y2xRM2pBF3YgnS4WHB"
    "qpXtsqEAWMlQDdZ950Q1731CMzRyCR1KEmyScKcYAkpXQtfYjO+smxAYcazyiTsYuQ54BXAGa8rNBbq0HdagIceJ0hYAyyBER77n"
    "qLJ18+aPLrpo2B3XXXvNs/Pmzpkz9+PZ5QBwzbWjul937TXPWA7g8XozKirK43t271rdoyiv9y233vryggXzl65cubwOAG67bUzf"
    "Sy+55FcJG5BS81hmkuzJz8vzPfzwQx8A+OC8885P/3jewn1pAZ9/WHFxn1A4EgIAjYRoq9OTZdqR0ujobw9wx5XQdsmKiZViIQVH"
    "mmNqy5IPMbT4Xv3MSx7EHZPWmP+YulB4UnT9hv95nHKLBsACIEh8Hy+jkaL2weMO1/tYBUlqboedVJnm9tYdqnzOurP3JpSwcFQZ"
    "SwFomgRKWRrhukNgtZyIHcRjpJhssoXNjrRAugmpHOWYdSjZbiC/L6N3B8ddC8YKEEqZ2d4jOu57a+MPGbbpZBqGYcdiTlwXTku3"
    "XVPHrp3561iyBrX5WDv3zz//zJPDLige60/1Bz8o/ejQhnXrZhBBnHvuWaMcBuJxO86KlWmaPOWVl0uGX3LB2GB6Rpe58z+p2rBx"
    "/d/dhitl8DkDRzhI6lqWFXF7POLjufNeuOrKK8at/HTN9IWLFrxdWFjUU9d1QwihHTx4sPrMQYOEbdtxy3Gszh5HKdu247at2hug"
    "7Di3WR8AYlak7DgrJ94ReFZ2nGwS8Ph1a+6UFfJnYzdovboN1G95fBaNfBTkEpB+gGtNkzyGgTa3adtxInQibDQwA6wkSljTRIOu"
    "lKwGO1WQVE2IVlqHem9FKyGCPx8ACyhWZhSjyakG1iH5929JuPTlcKp6hMFgEHEtsDfrjj1PicyMXHK4gImyanrdmIqXHwFaYBE1"
    "yGMduFi5ckX9nXeM6Ttlyh9Wp6b4g+efd9b1AFDXEGqqqKgs69+vzwAhUtzp6ely0aKFVY89/sSwZ599Zkmq39CKh5x7MwDUHG6o"
    "OVBWtv6cs874mcjILDRNk7dt27F2+PDhGDrk3JuHtuoBwKw58yYuX7bs8K8e/FUfTdPcwUCwqON83G6PV9M0d5o/ScTA7Q9QiuYm"
    "TzD/CM/tcnOq5pbhjK4kRPINpU4i4PGyByC3362iIY4/WjzYdceEX9Kgnz2hedO7OKGGitjf337Iddqw63HuoOvYMU0iQRTQ3KQD"
    "kLpsX1TGa7GIxs7E6P3+5zp9sVGlHv38YSfpAe9A1rXBZnOsJh3VK6n3SZ+oOmuzLlDuCEgSEJCAIwEWYCIACoIFQxHAICaCrdr4"
    "PAekRDJMKQVAMTPgpWzjAjocGp/4IrHRlZ9yuYqp5XEnut0cNGU3iifYndzSy/WPkcs/ybrf9b3sSxu71aNHT2PEyJEDi4q69mps"
    "qK8pLZ3xqW07NHjw4KJINGrPnzdvn2kmwMzo1+8075VXXXl2VnZOYe3hmkOlM0pXJxIJLi4u7hGNxey5H8/ZZ5omTj/9DN9FF100"
    "IDevS/dYLNry5RdrN86d+3E5AJz/0yEZ3bt3y6yrqw8vWrigoo0A6tv3VM/AgQOLEpaNBXNn7w4X9gvoPfvkcFVlk71xSQ0AiPxe"
    "Lup3bjcRj9v22nn7OBED+YOknX1Fb0UEtWnpPq6vtAGA/GkC8ZCijDydaystlhKeqft3yu75vROvPjHMnjtllTb0+pMBx7HXL9nL"
    "DVUOiEDuPyUiYGcx2+YSGO5zWOAUJvSSHlcKNAAJ04KGcicUnxmgilc4rceXmsdVAAKQBBlKS+5Rk0yGI8Voz6naYrMUSc+iuENY"
    "YbQ6GADCCnGs8XK1Br20vLSJKo5cuHUQANtMtDjgr6Xk7UjEN7CuFyvNfZ15v/6DgbwjpXks+bG6xzPmf0NE0clu+eAbU2TByZda"
    "75Zczbs+34203BTjhv+dLPsPvgkWELv7VK86uCN2VAZS+0N4iUz3XYhwQinQN8zOTiLeDFhbDOXsiNRUlWHCqeG2DoGS5UG9S042"
    "hWIKLiABgKVJpDEbNpHp0RVHazXmJPdpmiZckMoVSFOJRAKkGcy2eYSL1wxmQwq7xQnHHhhY2T6zR9ZnpqZ36cFe78kmy/4ktQEg"
    "6gNCPnwGVEv4S/PhlLN/DEBtGyRtobOtnZk78eBH000u1s6639Zr2yBh5vbffmhs27ZbN0/arMA5ktCJVqtp70tJvpwE4NgQfc4K"
    "GM8v3EUZaTkQAMyk4VHrtfX6I+das3//OYQ8kiAqpz2OE0q2+/0FuYVG+d6KhgnntBw9hW49QPgjDzoGFoY+UbqryI45Nrukhqb4"
    "2vj1qWOOuXyZW9n0739GoGRTMJZemO+LNVc0PtGz+f/XCcRkgk1ZRbp+029uxakX3G4Es09yzFi9OrhlkT3n9cnO2rnlEOJ7N2fo"
    "O7elKnmGbcUKAMMUxicTqU6gzJwpgFE42hm4wLRNQc7tWwefLpUJKDfg1CaqEiPd+UedQSlLYCYwapTq8BwCMzB6psApo5Jz7Hvi"
    "lOp/Zve8zXq/DeyPkIxJc1IAgKMhcoIFQoqYsgvP/gWCwdeQYMUAOSBmsHLqaq8x9y75LAC/0LxJ4Orr6oDJd4aOa8b/xnxPyPEd"
    "l0huYjKAPywyUnoNeR+6XkwWlCIWzEyCCORyBVkBpJLJmmLABqASAEyzkRUTkgWYgoBAwl5i7yu7CeP7Wsdy5yfkP3Cm7bi0SyFA"
    "5ARm1d9HPs8INjnGOos2YoeUAltWM4GIqDX7dhhwiCWI2JDu5MENAhwmUnDY77rWU5T7eYzo9yhlidE44bb/i/J/oGTm0RuI/vMA"
    "AAAASUVORK5CYII="
)
ICONE = (
    "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"
)


# --------------------------------------------------------------------------- painel web (acesso remoto)
import hashlib
import hmac
import secrets
import socket
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WEB_PORTA_PADRAO = 888
# senhas guardadas só como hash PBKDF2-SHA256 (200 mil iterações) — nunca em texto
WEB_SALT_PADRAO = ""     # sem senha padrão: o painel web só aceita login depois que a senha é definida
WEB_HASH_PADRAO = ""     # (pelo instalador ou em Configurações > Painel web)
WEB_SESSAO_HORAS = 8
WEB_MAX_FALHAS = 5
WEB_BLOQUEIO_S = 300


def hash_senha(senha, salt_hex):
    return hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), bytes.fromhex(salt_hex), 200_000).hex()


def definir_senha_web(cfg, senha):
    salt = secrets.token_hex(16)
    cfg.setdefault("web", {}).update({"salt": salt, "senha_hash": hash_senha(senha, salt)})


SENHA_PENDENTE = os.path.join(BASE_DIR, "senha_web.json")   # gravado pelo instalador (só o hash)


def _aplicar_senha_pendente(cfg):
    """Aplica a senha definida no instalador e apaga o arquivo. Retorna True se aplicou."""
    if not os.path.isfile(SENHA_PENDENTE):
        return False
    try:
        with open(SENHA_PENDENTE, "r", encoding="utf-8-sig") as f:
            d = json.load(f)
        salt, h = str(d.get("salt", "")), str(d.get("senha_hash", ""))
        bytes.fromhex(salt)
        assert len(bytes.fromhex(h)) == 32 and len(salt) >= 16
    except Exception:
        return False
    w = cfg.setdefault("web", {})
    mudou = (w.get("salt"), w.get("senha_hash")) != (salt, h)
    w.update({"salt": salt, "senha_hash": h})
    try:
        os.remove(SENHA_PENDENTE)
    except OSError:
        pass
    return mudou


def cfg_web(cfg):
    w = cfg.setdefault("web", {})
    w.setdefault("ativo", True)
    w.setdefault("porta", WEB_PORTA_PADRAO)
    w.setdefault("salt", WEB_SALT_PADRAO)
    w.setdefault("senha_hash", WEB_HASH_PADRAO)
    return w


def enderecos_locais(porta, https=False):
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except Exception:
        pass
    try:  # IP da rota padrão
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    ips.discard("127.0.0.1")
    esquema = "https" if https else "http"
    return [f"{esquema}://{ip}:{porta}" for ip in sorted(ips)] or [f"{esquema}://localhost:{porta}"]


def versao_config():
    """Versão da configuração = hash do conteúdo (gravar o mesmo conteúdo não gera "conflito")."""
    try:
        with _TRAVA_CFG, open(CONFIG_PATH, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except OSError:
        return "0"


class PainelWeb:
    """Servidor HTTP embutido: mesma configuração (painel_config.json) e mesmas ações do programa."""

    def __init__(self, ao_mudar=None, ao_identificar=None):
        self.ao_mudar = ao_mudar or (lambda: None)
        self.ao_identificar = ao_identificar or (lambda device: None)
        self.sessoes = {}         # token -> expira_em
        self.falhas = {}          # ip -> [qtd, bloqueado_ate]
        self.trava = threading.Lock()
        self.ultimo_log = ""
        self.httpd = None
        self.https = False
        self.porta = None

    # ---- ciclo de vida
    def iniciar(self, porta):
        self.parar()
        servidor = self

        class Handler(ManipuladorWeb):
            painel = servidor
        self.httpd = ThreadingHTTPServer(("0.0.0.0", int(porta)), Handler)
        self.httpd.daemon_threads = True
        cert, chave = os.path.join(BASE_DIR, "cert.pem"), os.path.join(BASE_DIR, "key.pem")
        self.https = os.path.isfile(cert) and os.path.isfile(chave)
        if self.https:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(cert, chave)
            self.httpd.socket = ctx.wrap_socket(self.httpd.socket, server_side=True)
        self.porta = int(porta)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def parar(self):
        if self.httpd:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:
                pass
            self.httpd = None

    def enderecos(self):
        return enderecos_locais(self.porta, self.https) if self.porta else []

    # ---- autenticação
    def login(self, ip, senha, navegador=""):
        agora = time.time()
        with self.trava:
            qtd, ate = self.falhas.get(ip, [0, 0])
            if ate > agora:
                return None, f"Muitas tentativas. Tente de novo em {int(ate - agora) + 1} s."
            w = cfg_web(carregar_config(listar_monitores()))
            if not w.get("senha_hash") or not w.get("salt"):
                return None, ("A senha do painel web ainda não foi definida. No PC das telas, abra o "
                              "dashmgr > Configurações > Painel web.")
            ok = hmac.compare_digest(hash_senha(senha or "", w["salt"]), w["senha_hash"])
            if not ok:
                qtd += 1
                self.falhas[ip] = [0, agora + WEB_BLOQUEIO_S] if qtd >= WEB_MAX_FALHAS else [qtd, 0]
                return None, "Senha incorreta."
            self.falhas.pop(ip, None)
            token = secrets.token_urlsafe(32)
            self.sessoes[token] = {"exp": agora + WEB_SESSAO_HORAS * 3600, "ip": ip,
                                   "ua": (navegador or "")[:300], "inicio": agora, "ultimo": agora}
            return token, None

    def sessao_valida(self, token):
        with self.trava:
            sess = self.sessoes.get(token or "")
            agora = time.time()
            if not sess or sess["exp"] < agora:
                self.sessoes.pop(token or "", None)
                return False
            sess["exp"] = agora + WEB_SESSAO_HORAS * 3600       # renova
            sess["ultimo"] = agora
            return True

    def logout(self, token):
        with self.trava:
            self.sessoes.pop(token or "", None)

    @staticmethod
    def id_sessao(token):
        return hashlib.sha256((token or "").encode()).hexdigest()[:12]

    def listar_sessoes(self, token_atual=None):
        agora = time.time()
        with self.trava:
            for t in [t for t, s_ in self.sessoes.items() if s_["exp"] < agora]:
                self.sessoes.pop(t, None)
            return sorted(({"id": self.id_sessao(t), "ip": s_["ip"], "navegador": resumo_navegador(s_["ua"]),
                            "inicio": s_["inicio"], "ultimo": s_["ultimo"], "atual": t == token_atual}
                           for t, s_ in self.sessoes.items()), key=lambda x: -x["ultimo"])

    def derrubar(self, sid=None, exceto=None):
        """Derruba uma sessão (sid) ou todas (sid=None), menos a do token 'exceto'. Retorna quantas caíram."""
        with self.trava:
            alvo = [t for t in self.sessoes if t != exceto and (sid is None or self.id_sessao(t) == sid)]
            for t in alvo:
                self.sessoes.pop(t, None)
        return len(alvo)

    # ---- dados
    def log(self, msg):
        self.ultimo_log = msg

    def estado(self):
        mons = listar_monitores()
        cfg = carregar_config(mons)
        links = []
        for it in cfg["links"]:
            m = resolver_monitor(it, mons)
            links.append({"id": it["id"], "nome": it.get("nome", ""), "url": it.get("url", ""),
                          "kiosk": it.get("kiosk", True), "ativo": it.get("ativo", True),
                          "perfil_separado": bool(it.get("perfil_separado", False)),
                          "auto_refresh": bool(it.get("auto_refresh", False)),
                          "refresh_s": int(it.get("refresh_s") or 300),
                          "monitor": m["device"] if m else it.get("monitor")})
        return {"monitores": [{k: m[k] for k in ("device", "num", "x", "y", "w", "h", "primario")} for m in mons],
                "links": links, "versao": versao_config(), "log": self.ultimo_log,
                "pc": socket.gethostname(), "enderecos": self.enderecos(), "versao_app": APP_VERSAO}

    def salvar(self, versao_cliente, novos):
        with self.trava:
            if versao_cliente and versao_cliente != versao_config():
                raise ConflitoWeb("Outra pessoa salvou antes de você. Recarregue para ver a versão atual.")
            mons = listar_monitores()
            cfg = carregar_config(mons)
            cfg_antigo = json.loads(json.dumps(cfg))
            antigos = {it["id"]: it for it in cfg["links"]}
            saida = []
            for n in novos:
                lid = str(n.get("id") or "") or uuid.uuid4().hex[:8]
                if not all(c.isalnum() for c in lid):
                    lid = uuid.uuid4().hex[:8]
                it = dict(antigos.get(lid, {}))
                it.update({"id": lid, "nome": str(n.get("nome", ""))[:120], "url": str(n.get("url", "")).strip()[:2000],
                           "kiosk": bool(n.get("kiosk", True)), "ativo": bool(n.get("ativo", True)),
                           "perfil_separado": bool(n.get("perfil_separado", False)),
                           "auto_refresh": bool(n.get("auto_refresh", False)),
                           "refresh_s": _segundos(n.get("refresh_s"))})
                m = next((mm for mm in mons if mm["device"] == n.get("monitor")), None)
                if m:
                    it.update({"monitor": m["device"], "monitor_hwid": m.get("hwid", ""), "monitor_pos": [m["x"], m["y"]]})
                saida.append(it)
            cfg["links"] = saida
            salvar_config(cfg)
        aplicar_mudancas_async(cfg_antigo, cfg, self.log)
        self.ao_mudar()
        return versao_config()

    def link(self, lid):
        mons = listar_monitores()
        cfg = carregar_config(mons)
        it = next((x for x in cfg["links"] if x["id"] == lid), None)
        if not it:
            raise ValueError("Link não encontrado. Salve antes de testar.")
        return cfg, mons, it


def _segundos(v):
    try:
        return max(REFRESH_MIN_S, min(86400, int(float(v))))
    except (TypeError, ValueError):
        return 300


def resumo_navegador(ua):
    ua = ua or ""
    nav = ("Edge" if "Edg/" in ua else "Opera" if "OPR/" in ua else "Chrome" if "Chrome/" in ua
           else "Firefox" if "Firefox/" in ua else "Safari" if "Safari/" in ua else "Navegador")
    so = ("Android" if "Android" in ua else "iPhone" if "iPhone" in ua else "iPad" if "iPad" in ua
          else "Windows" if "Windows" in ua else "macOS" if "Mac OS" in ua else "Linux" if "Linux" in ua else "")
    return f"{nav} · {so}" if so else nav


class ConflitoWeb(Exception):
    pass


class ManipuladorWeb(BaseHTTPRequestHandler):
    painel = None                      # definido na subclasse criada em PainelWeb.iniciar
    server_version = "dashmgr"
    sys_version = ""

    def log_message(self, fmt, *args):   # silencioso (pythonw não tem console)
        pass

    # ---- utilitários
    def _token(self):
        for parte in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = parte.strip().partition("=")
            if k == "pmt_sid":
                return v
        return ""

    def _json(self, codigo, dados, cookie=None):
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self._cabecalhos_seguranca()
        self.end_headers()
        self.wfile.write(corpo)

    def _cabecalhos_seguranca(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")

    def _corpo(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 1_000_000:
            raise ValueError("Requisição muito grande.")
        bruto = self.rfile.read(n) if n else b"{}"
        return json.loads(bruto.decode("utf-8") or "{}")

    def _autorizado(self):
        return self.painel.sessao_valida(self._token())

    # ---- GET
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            corpo = pagina_web().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; img-src 'self' data: blob:; style-src 'unsafe-inline'; "
                             "script-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
            self._cabecalhos_seguranca()
            self.end_headers()
            self.wfile.write(corpo)
        elif self.path == "/api/estado":
            if not self._autorizado():
                return self._json(401, {"erro": "Não autenticado."})
            self._json(200, self.painel.estado())
        elif self.path == "/api/sessoes":
            if not self._autorizado():
                return self._json(401, {"erro": "Não autenticado."})
            self._json(200, {"sessoes": self.painel.listar_sessoes(self._token())})
        elif self.path.startswith("/api/remoto/quadro?"):
            if not self._autorizado():
                return self._json(401, {"erro": "Não autenticado."})
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            lid = (q.get("id") or [""])[0]
            try:
                seq = int((q.get("seq") or ["0"])[0])
            except ValueError:
                seq = 0
            sess = REMOTO.obter(None, lid, criar=False)
            if not sess:
                return self._json(410, {"erro": "Sessão remota encerrada. Abra o acesso de novo."})
            try:
                n, img, meta = sess.quadro_apos(seq)
            except Exception as e:
                return self._json(410, {"erro": f"Tela indisponível: {e}"})
            if not sess.viva and (img is None or n <= seq):
                return self._json(410, {"erro": "A tela foi fechada ou reaberta. Abra o acesso de novo."})
            if img is None or n <= seq:
                self.send_response(204)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(img)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Seq", str(n))
            self.send_header("X-W", str(meta.get("deviceWidth") or 0))
            self.send_header("X-H", str(meta.get("deviceHeight") or 0))
            self._cabecalhos_seguranca()
            self.end_headers()
            self.wfile.write(img)
        else:
            self._json(404, {"erro": "Não encontrado."})

    # ---- POST
    def do_POST(self):
        if self.headers.get("X-Painel") != "1":                 # bloqueia CSRF de outros sites
            return self._json(403, {"erro": "Requisição recusada."})
        try:
            dados = self._corpo()
        except Exception as e:
            return self._json(400, {"erro": str(e) or "JSON inválido."})
        p = self.painel
        rota = self.path

        if rota == "/api/login":
            time.sleep(0.4)                                      # atrasa força bruta
            token, erro = p.login(self.client_address[0], dados.get("senha", ""), self.headers.get("User-Agent", ""))
            if erro:
                return self._json(429 if "tentativas" in erro else 401, {"erro": erro})
            seguro = "; Secure" if p.https else ""
            return self._json(200, {"ok": True},
                              cookie=f"pmt_sid={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={WEB_SESSAO_HORAS * 3600}{seguro}")
        if rota == "/api/logout":
            p.logout(self._token())
            return self._json(200, {"ok": True}, cookie="pmt_sid=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")

        if not self._autorizado():
            return self._json(401, {"erro": "Não autenticado."})
        try:
            if rota == "/api/salvar":
                v = p.salvar(dados.get("versao"), dados.get("links") or [])
                return self._json(200, {"ok": True, "versao": v})

            if rota == "/api/abrir_todos":
                mons = listar_monitores()
                cfg = carregar_config(mons)
                threading.Thread(target=abrir_todos, args=(cfg, mons, p.log), daemon=True).start()
                return self._json(200, {"msg": "Abrindo todos os links nas telas…"})

            if rota == "/api/fechar_todos":
                cfg = carregar_config(listar_monitores())
                threading.Thread(target=lambda: (fechar_paineis(cfg), p.log("Painéis fechados.")), daemon=True).start()
                return self._json(200, {"msg": "Fechando todos os painéis…"})

            if rota == "/api/abrir":
                cfg, mons, it = p.link(str(dados.get("id")))
                m = resolver_monitor(it, mons)
                if not m or not it.get("url"):
                    raise ValueError("Preencha a URL e escolha a tela.")
                login = bool(dados.get("login"))

                def tarefa():
                    try:
                        fechar_perfil(cfg, it["id"])
                        abrir_link(cfg, it, m, kiosk=False if login else None,
                                   extras=("chrome://settings/onStartup",) if login else ())
                        p.log(f"Aberto na Tela {m['num']}: {it['url']}")
                    except Exception as e:
                        p.log(f"[ERRO] {e}")
                threading.Thread(target=tarefa, daemon=True).start()
                return self._json(200, {"msg": ("Janela de login aberta" if login else "Abrindo") + f" na Tela {m['num']}…"})

            if rota == "/api/fechar":
                cfg, mons, it = p.link(str(dados.get("id")))
                threading.Thread(target=lambda: (fechar_perfil(cfg, it["id"]),
                                                 p.log(f"'{it.get('nome') or it['url']}' fechado.")), daemon=True).start()
                return self._json(200, {"msg": f"Fechando '{it.get('nome') or it.get('url')}'…"})

            if rota == "/api/sessoes/derrubar":
                atual = self._token()
                if dados.get("todas"):
                    n = p.derrubar(None, exceto=atual)
                else:
                    sid = str(dados.get("id") or "")
                    if sid == p.id_sessao(atual):
                        return self._json(400, {"erro": "Para sair da sua própria sessão use o botão Sair."})
                    n = p.derrubar(sid, exceto=atual)
                p.log(f"👥 {n} sessão(ões) do painel web derrubada(s) por {self.client_address[0]}")
                return self._json(200, {"msg": f"{n} sessão(ões) derrubada(s).", "derrubadas": n})

            if rota == "/api/remoto/iniciar":
                cfg, mons, it = p.link(str(dados.get("id")))
                m = resolver_monitor(it, mons)
                REMOTO.encerrar(it["id"])                       # sempre começa uma sessão nova
                REMOTO.obter(cfg, it["id"])
                nome = it.get("nome") or it.get("url")
                p.log(f"🖥 Acesso remoto a '{nome}' (Tela {m['num'] if m else '?'}) por {self.client_address[0]}")
                return self._json(200, {"nome": nome, "tela": m["num"] if m else None})

            if rota == "/api/remoto/entrada":
                sess = REMOTO.obter(None, str(dados.get("id")), criar=False)
                if not sess:
                    return self._json(410, {"erro": "Sessão remota encerrada."})
                sess.entrada(dados.get("eventos") or [])
                return self._json(200, {"ok": True})

            if rota == "/api/remoto/encerrar":
                REMOTO.encerrar(str(dados.get("id")))
                return self._json(200, {"ok": True})

            if rota == "/api/recarregar":
                cfg = carregar_config(listar_monitores())
                threading.Thread(target=lambda: p.log(f"↻ {recarregar_telas(cfg)} tela(s) recarregada(s)."),
                                 daemon=True).start()
                return self._json(200, {"msg": "Recarregando as telas…"})

            if rota == "/api/identificar":
                p.ao_identificar(dados.get("device"))
                return self._json(200, {"msg": "Números exibidos nas telas por 4 s."})
        except ConflitoWeb as e:
            return self._json(409, {"erro": str(e)})
        except Exception as e:
            return self._json(400, {"erro": str(e)})
        return self._json(404, {"erro": "Não encontrado."})


def pagina_web():
    return (PAGINA_WEB.replace("__LOGO_GRANDE__", "".join(LOGO_OVERLAY))
            .replace("__LOGO__", "".join(LOGO_HEADER))
            .replace("__ICONE__", "".join(ICONE))
            .replace("__VERSAO__", APP_VERSAO))


PAGINA_WEB = r'''<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>dashmgr</title>
<link rel="icon" href="data:image/png;base64,__ICONE__">
<style>
:root{
  --roxo:#392776; --roxo-esc:#2a1c5a; --roxo-claro:#5b4a9e;
  --ciano:#33BCD5; --ciano-esc:#239fb6; --ciano-txt:#6FD2E4;
  --bg:#f0eff6; --card:#fff; --borda:#D9D5E8; --ink:#16122b; --mudo:#5A5470;
  --desl:#b9b4cc; --perigo:#c0392b; --perigo-bg:#fbeaea;
}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.4 "Segoe UI",system-ui,-apple-system,Roboto,Arial,sans-serif}
button{font:inherit;cursor:pointer}
input,select{font:inherit;color:var(--ink)}
.oculto{display:none!important}

/* login */
#tela-login{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:16px;
  background:radial-gradient(1200px 600px at 20% 0%,#4b3592 0,var(--roxo) 45%,var(--roxo-esc) 100%)}
.login-card{width:100%;max-width:380px;background:var(--card);border-radius:14px;overflow:hidden;box-shadow:0 20px 60px rgba(10,6,30,.45)}
.login-topo{background:var(--roxo);padding:28px 24px 22px;text-align:center;border-bottom:4px solid var(--ciano)}
.login-topo img{height:60px}
.login-topo div{color:var(--ciano-txt);font-size:12px;margin-top:10px;letter-spacing:.04em}
.login-corpo{padding:24px}
.login-corpo h1{margin:0 0 4px;font-size:18px;color:var(--roxo)}
.login-corpo p{margin:0 0 18px;color:var(--mudo);font-size:13px}
.campo{width:100%;padding:11px 12px;border:1px solid var(--borda);border-radius:8px;background:#fff;outline:none}
.campo:focus{border-color:var(--ciano);box-shadow:0 0 0 3px rgba(51,188,213,.18)}
#erro-login{color:var(--perigo);font-size:12px;min-height:18px;margin:8px 0 4px}
.btn{border:1px solid var(--borda);background:#fff;color:var(--roxo);font-weight:700;font-size:13px;
  padding:8px 14px;border-radius:8px;display:inline-flex;align-items:center;gap:6px;white-space:nowrap}
.btn:hover{background:var(--bg)}
.btn.prim{background:var(--ciano);border-color:var(--ciano);color:#fff}
.btn.prim:hover{background:var(--ciano-esc)}
.btn.roxo{background:var(--roxo);border-color:var(--roxo);color:#fff}
.btn.roxo:hover{background:var(--roxo-esc)}
.btn.perigo{color:var(--perigo)}
.btn.perigo:hover{background:var(--perigo-bg)}
.btn.fant{color:var(--mudo);padding:6px 10px;font-size:12px}
.btn.grande{width:100%;justify-content:center;padding:12px;font-size:15px}
.btn:disabled{opacity:.5;cursor:default}
.btn.pulsa{box-shadow:0 0 0 3px rgba(51,188,213,.35)}

/* app */
header{background:var(--roxo);color:#fff;display:flex;align-items:center;gap:16px;padding:12px 20px;border-bottom:3px solid var(--ciano);flex-wrap:wrap}
header img{height:38px}
.sep{width:1px;height:34px;background:var(--roxo-claro)}
.tit b{display:block;font-size:17px}
.tit span{font-size:12px;color:var(--ciano-txt)}
.chip{margin-left:auto;background:var(--ciano-txt);color:var(--roxo);font-weight:700;font-size:12px;padding:5px 12px;border-radius:99px}
header .btn{background:transparent;border-color:var(--roxo-claro);color:#fff}
header .btn:hover{background:var(--roxo-claro)}
main{max-width:1320px;margin:0 auto;padding:18px 20px 80px}
.topo{display:grid;grid-template-columns:1fr 280px;gap:16px}
@media (max-width:900px){.topo{grid-template-columns:1fr}}
.painel{background:var(--card);border:1px solid var(--borda);border-radius:12px}
.painel-cab{display:flex;align-items:center;gap:10px;padding:12px 14px 0;flex-wrap:wrap}
.painel-cab h2{margin:0;font-size:15px;color:var(--roxo)}
.dica{font-size:12px;color:var(--mudo)}
.painel-cab .acoes{margin-left:auto;display:flex;gap:6px}
#mapa{position:relative;margin:12px 14px 14px;height:220px;touch-action:none}
.tile{position:absolute;border:2px solid var(--borda);background:var(--bg);color:var(--desl);border-radius:6px;
  display:flex;flex-direction:column;align-items:center;justify-content:center;overflow:hidden;cursor:grab;user-select:none;touch-action:none;transition:outline-color .1s}
.tile.uso{background:var(--roxo);border-color:var(--ciano);color:#fff;box-shadow:inset 0 -4px 0 var(--ciano)}
.tile.inativo{background:var(--desl);color:#fff}
.tile.conflito{border-color:var(--perigo);box-shadow:inset 0 -4px 0 var(--perigo)}
.tile.alvo{outline:4px solid var(--ciano);outline-offset:1px}
.tile .canto{position:absolute;left:6px;top:4px;font-size:10px;font-weight:700;color:var(--mudo)}
.tile.uso .canto,.tile.inativo .canto{color:var(--ciano-txt)}
.tile .gr{font-weight:800;line-height:1;margin-top:10px}
.tile .leg{font-size:11px;max-width:94%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--mudo)}
.tile.uso .leg{color:var(--ciano-txt)}
.lado{display:flex;flex-direction:column;gap:10px}
.lado .btn{width:100%;justify-content:center;padding:10px}
.lado .btn.prim{padding:16px;font-size:16px}
#info-web{font-size:11px;color:var(--mudo);background:var(--card);border:1px dashed var(--borda);border-radius:8px;padding:8px 10px}
.sec{display:flex;align-items:center;gap:10px;margin:22px 0 10px}
.sec::before{content:"";width:4px;height:18px;background:var(--ciano);border-radius:2px}
.sec h2{margin:0;font-size:15px;color:var(--roxo)}
.sec .btn{margin-left:auto}
#aviso{display:flex;align-items:center;gap:10px;background:#fff7e0;border:1px solid #f0d68a;color:#6b5200;border-radius:8px;padding:8px 12px;margin-bottom:10px;font-size:13px}
.card{display:flex;background:var(--card);border:1px solid var(--borda);border-radius:10px;margin-bottom:8px;overflow:hidden}
.card .faixa{width:5px;background:var(--ciano);flex:none}
.card.off .faixa{background:var(--desl)}
.badge{width:78px;flex:none;background:var(--roxo);color:#fff;display:flex;flex-direction:column;align-items:center;justify-content:center;cursor:grab;user-select:none;touch-action:none;padding:6px 0}
.card.off .badge,.badge.sem{background:var(--desl)}
.badge small{font-size:9px;font-weight:700;color:var(--ciano-txt);letter-spacing:.06em}
.badge b{font-size:24px;line-height:1.1}
.badge span{font-size:10px;color:#e6e3f0}
.meio{flex:1;min-width:0;padding:10px 12px;display:flex;flex-direction:column;gap:8px}
.l1,.l2{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.nome{font-weight:700;font-size:15px;width:260px;max-width:100%}
.l2 label{font-size:11px;color:var(--mudo)}
.url{flex:1;min-width:180px}
.sel{width:210px;padding:9px 8px}
.chk{display:inline-flex;align-items:center;gap:5px;font-size:12px;color:var(--mudo);cursor:pointer}
.chk input{accent-color:var(--ciano);width:15px;height:15px}
.campo.segs{width:78px;padding:5px 6px;font-size:12px}
.campo.segs:disabled{background:var(--bg);color:var(--desl)}
.bts{display:grid;grid-template-columns:1fr 1fr;gap:6px;padding:10px 12px;align-content:center}
.bts .btn{justify-content:center;padding:6px 10px;font-size:12px}
@media (max-width:760px){
  .card{flex-wrap:wrap}.badge{width:64px}.meio{flex-basis:calc(100% - 70px)}
  .bts{grid-template-columns:repeat(4,1fr);width:100%;border-top:1px solid var(--borda)}
  .nome,.sel{width:100%}
  .l2>label:first-child{display:none}
  #mapa{margin:10px}
}
#ghost{position:fixed;z-index:50;pointer-events:none;background:var(--roxo);color:#fff;font-weight:700;font-size:13px;
  padding:7px 12px;border-radius:8px;border:2px solid var(--ciano);box-shadow:0 8px 24px rgba(0,0,0,.25);white-space:nowrap}
footer{position:fixed;left:0;right:0;bottom:0;background:var(--ink);color:#e6e3f0;font-size:12px;display:flex;gap:12px;padding:7px 16px;align-items:center}
footer .marca{margin-left:auto;color:var(--ciano-txt);white-space:nowrap}
@media (max-width:760px){footer .marca{display:none}}
#toast{position:fixed;right:16px;bottom:44px;z-index:60;background:var(--roxo);color:#fff;padding:10px 14px;border-radius:8px;
  border-left:4px solid var(--ciano);box-shadow:0 8px 24px rgba(0,0,0,.25);font-size:13px;opacity:0;transform:translateY(8px);transition:.2s;pointer-events:none;max-width:90vw}
#toast.on{opacity:1;transform:none}
#toast.erro{border-left-color:var(--perigo)}
/* sessões */
#sessoes{position:fixed;inset:0;z-index:65;background:rgba(10,9,18,.55);display:flex;align-items:center;justify-content:center;padding:16px}
.ss-card{background:var(--card);border-radius:12px;width:100%;max-width:720px;max-height:90vh;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 20px 60px rgba(10,6,30,.45)}
.ss-topo{background:var(--roxo);color:#fff;padding:12px 16px;border-bottom:3px solid var(--ciano);display:flex;align-items:center;gap:10px}
.ss-topo b{font-size:15px;margin-right:auto}
.ss-topo .btn{background:transparent;color:#fff;border-color:var(--roxo-claro);padding:5px 10px;font-size:12px}
.ss-corpo{padding:12px 16px;overflow:auto}
.ss-linha{display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--borda)}
.ss-linha:last-child{border-bottom:0}
.ss-linha .q{flex:1;min-width:0}
.ss-linha .q b{display:block;font-size:14px}
.ss-linha .q span{font-size:12px;color:var(--mudo)}
.ss-eu{font-size:11px;font-weight:700;color:var(--roxo);background:var(--bg);border-radius:99px;padding:4px 10px}
.ss-rodape{padding:12px 16px;border-top:1px solid var(--borda);display:flex;justify-content:flex-end;gap:8px}

/* acesso remoto */
#remoto{position:fixed;inset:0;z-index:70;background:#0a0912;display:flex;flex-direction:column}
.rm-barra{display:flex;gap:8px;align-items:center;padding:8px 12px;background:var(--roxo);border-bottom:3px solid var(--ciano);color:#fff;flex-wrap:wrap}
.rm-barra b{font-size:14px}
#rm-info{font-size:12px;color:var(--ciano-txt);margin-right:auto}
#rm-info .vivo{color:#7CFFB2}
.rm-barra .btn{background:transparent;color:#fff;border-color:var(--roxo-claro);padding:6px 10px;font-size:12px}
.rm-barra .btn:hover{background:var(--roxo-claro)}
.rm-area{flex:1;min-height:0;display:flex;align-items:center;justify-content:center;overflow:hidden;position:relative}
#rm-img{max-width:100%;max-height:100%;user-select:none;-webkit-user-drag:none;touch-action:none;cursor:default;box-shadow:0 0 0 1px #2a2540}
#rm-carregando{position:absolute;color:#e6e3f0;font-size:14px}
#rm-kbd{position:fixed;left:-9999px;top:0;width:1px;height:1px;opacity:0}
.bts .btn.acesso{grid-column:span 2;background:var(--roxo);border-color:var(--roxo);color:#fff}
.bts .btn.acesso:hover{background:var(--roxo-esc)}
@media (max-width:760px){.bts .btn.acesso{grid-column:span 4}}

</style>
</head>
<body>

<section id="tela-login" class="oculto">
  <form class="login-card" id="form-login" autocomplete="off">
    <div class="login-topo"><img alt="dashmgr" src="data:image/png;base64,__LOGO_GRANDE__"><div>GERENCIADOR DE DASHBOARDS · v__VERSAO__</div></div>
    <div class="login-corpo">
      <h1>Acesso restrito</h1>
      <p>Digite a senha para gerenciar as telas remotamente.</p>
      <input class="campo" type="password" id="senha" placeholder="Senha" autofocus>
      <div id="erro-login"></div>
      <button class="btn prim grande" type="submit">Desbloquear</button>
    </div>
  </form>
</section>

<section id="tela-app" class="oculto">
  <header>
    <img alt="dashmgr" src="data:image/png;base64,__LOGO__">
    <div class="sep"></div>
    <div class="tit"><b>Gerenciador de dashboards</b><span id="sub-pc">Controle remoto</span></div>
    <div class="chip" id="chip">– telas</div>
    <button class="btn" id="b-sessoes" title="Ver e derrubar quem está conectado">👥 Sessões</button>
    <button class="btn" id="b-sair" title="Sair">Sair</button>
  </header>

  <main>
    <div class="topo">
      <div class="painel">
        <div class="painel-cab">
          <h2>Mapa das telas</h2>
          <span class="dica">arraste a posição entre as telas</span>
          <div class="acoes"><button class="btn fant" id="b-ident">◎ Identificar todas</button></div>
        </div>
        <div id="mapa"></div>
      </div>
      <div class="lado">
        <button class="btn prim" id="b-abrir">▶&nbsp; ABRIR TODOS</button>
        <button class="btn" id="b-fechar">■&nbsp; Fechar todos os painéis</button>
        <button class="btn" id="b-recarregar-telas">↻&nbsp; Recarregar telas</button>
        <button class="btn" id="b-salvar">💾&nbsp; Salvar alterações</button>
        <div id="info-web"></div>
      </div>
    </div>

    <div class="sec"><h2>Links</h2><span class="dica" id="qtd"></span>
      <button class="btn roxo" id="b-add">+ Adicionar link</button></div>
    <div id="aviso" class="oculto"><span>Outra pessoa alterou a configuração enquanto você editava.</span>
      <button class="btn fant" id="b-recarregar">Recarregar (descarta suas edições)</button></div>
    <div id="lista"></div>
  </main>

  <footer><span id="status">Pronto.</span><span class="marca">dashmgr v__VERSAO__ · criado por mayk.cloud e luniobr.com</span></footer>
</section>

<div id="remoto" class="oculto">
  <div class="rm-barra">
    <b id="rm-tit">Acesso remoto</b><span id="rm-info"></span>
    <button class="btn" id="rm-teclado" title="Abre o teclado (celular)">⌨ Teclado</button>
    <button class="btn" id="rm-reload">↻ Recarregar página</button>
    <button class="btn" id="rm-full">⤢ Tela cheia</button>
    <button class="btn" id="rm-fechar">✕ Fechar</button>
  </div>
  <div class="rm-area"><img id="rm-img" alt="" draggable="false"><div id="rm-carregando">Conectando à tela…</div></div>
  <textarea id="rm-kbd" autocapitalize="off" autocomplete="off" autocorrect="off" spellcheck="false"></textarea>
</div>

<div id="sessoes" class="oculto">
  <div class="ss-card">
    <div class="ss-topo"><b>Sessões abertas no painel web</b><button class="btn" id="ss-atualizar">↻ Atualizar</button><button class="btn" id="ss-fechar">✕ Fechar</button></div>
    <div class="ss-corpo" id="ss-lista"></div>
    <div class="ss-rodape"><button class="btn perigo" id="ss-todas">Derrubar todas as outras sessões</button></div>
  </div>
</div>

<div id="toast"></div>

<script>
(() => {
const $ = s => document.querySelector(s);
let estado = null;          // {monitores, links, versao, log, pc}
let links = [];             // cópia editável
let sujo = false;
let versao = null;
let base = "";

/* ---------------- API ---------------- */
async function api(caminho, corpo) {
  const op = {method: corpo === undefined ? "GET" : "POST",
              headers: {"X-Painel": "1", "Content-Type": "application/json"}, credentials: "same-origin"};
  if (corpo !== undefined) op.body = JSON.stringify(corpo);
  const r = await fetch(caminho, op);
  let dados = {};
  try { dados = await r.json(); } catch (e) {}
  if (r.status === 401 && caminho !== "/api/login") { mostrarLogin(); throw new Error("Sessão expirada"); }
  if (!r.ok) { const e = new Error(dados.erro || ("Erro " + r.status)); e.status = r.status; throw e; }
  return dados;
}
function toast(msg, erro) {
  const t = $("#toast"); t.textContent = msg; t.className = "on" + (erro ? " erro" : "");
  clearTimeout(t._h); t._h = setTimeout(() => t.className = "", 3200);
}
function status(msg) { $("#status").textContent = msg; }

/* ---------------- login ---------------- */
function mostrarLogin() { $("#tela-app").classList.add("oculto"); $("#tela-login").classList.remove("oculto"); $("#senha").focus(); }
function mostrarApp() { $("#tela-login").classList.add("oculto"); $("#tela-app").classList.remove("oculto"); }
$("#form-login").addEventListener("submit", async ev => {
  ev.preventDefault();
  $("#erro-login").textContent = "";
  try {
    await api("/api/login", {senha: $("#senha").value});
    $("#senha").value = "";
    mostrarApp(); await carregar(true);
  } catch (e) { $("#erro-login").textContent = e.message; }
});
$("#b-sair").onclick = async () => { try { await api("/api/logout", {}); } catch (e) {} mostrarLogin(); };

/* ---------------- dados ---------------- */
async function carregar(forcar) {
  const d = await api("/api/estado");
  estado = d;
  if (forcar || !sujo) {
    links = d.links.map(l => ({...l}));
    base = JSON.stringify(d.links);
    versao = d.versao; marcarSujo(false);
    $("#aviso").classList.add("oculto");
    render();
  } else if (d.versao !== versao) {
    if (JSON.stringify(d.links) === base) versao = d.versao;   // nada mudou nos links: não é conflito
    else $("#aviso").classList.remove("oculto");
  }
  $("#chip").textContent = `${d.monitores.length} tela${d.monitores.length !== 1 ? "s" : ""} detectada${d.monitores.length !== 1 ? "s" : ""}`;
  $("#sub-pc").textContent = "Controle remoto · " + (d.pc || "");
  $("#info-web").innerHTML = "";
  $("#info-web").append(Object.assign(document.createElement("div"), {textContent: "Acesso: " + (d.enderecos || []).join("  ·  ")}));
  if (d.log) status(d.log);
}
function marcarSujo(v) { sujo = v; $("#b-salvar").classList.toggle("pulsa", v); $("#b-salvar").innerHTML = v ? "💾&nbsp; Salvar alterações •" : "💾&nbsp; Salvo"; }
async function salvar(msg, tentativa) {
  try {
    const d = await api("/api/salvar", {versao, links});
    versao = d.versao; marcarSujo(false);
    $("#aviso").classList.add("oculto");
    toast(msg || "✔ Configuração salva");
    await carregar(true);
  } catch (e) {
    if (e.status === 409 && !tentativa) {
      // confere se alguém mudou de verdade os links; se não mudou, salva de novo com a versão atual
      try {
        const d = await api("/api/estado");
        if (JSON.stringify(d.links) === base) { versao = d.versao; return salvar(msg, true); }
      } catch (e2) {}
    }
    if (e.status === 409) { $("#aviso").classList.remove("oculto"); toast(e.message, true); }
    else toast(e.message, true);
  }
}
$("#b-salvar").onclick = () => salvar();
$("#b-recarregar").onclick = () => carregar(true);
document.addEventListener("keydown", e => { if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); salvar(); } });

/* ---------------- helpers ---------------- */
const mon = dev => estado.monitores.find(m => m.device === dev);
const pos = l => links.indexOf(l) + 1;
const nomeDe = l => (l.nome || "").trim() || (l.url || "").trim() || "(sem nome)";
function el(tag, attrs, ...filhos) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") e.className = v; else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k in e) e[k] = v; else e.setAttribute(k, v);
  }
  for (const f of filhos) if (f != null) e.append(f);
  return e;
}

/* ---------------- render ---------------- */
function render() { renderMapa(); renderLista(); }

function renderMapa() {
  const box = $("#mapa"); box.innerHTML = "";
  const ms = estado.monitores; if (!ms.length) return;
  const x0 = Math.min(...ms.map(m => m.x)), y0 = Math.min(...ms.map(m => m.y));
  const x1 = Math.max(...ms.map(m => m.x + m.w)), y1 = Math.max(...ms.map(m => m.y + m.h));
  const W = box.clientWidth, H = Math.max(80, Math.min(260, W * (y1 - y0) / (x1 - x0)));
  box.style.height = H + "px";
  const esc = Math.min(W / (x1 - x0), H / (y1 - y0));
  const ox = (W - (x1 - x0) * esc) / 2, oy = (H - (y1 - y0) * esc) / 2;
  for (const m of ms) {
    const noMon = links.filter(l => l.monitor === m.device);
    const ativos = noMon.filter(l => l.ativo);
    const mostra = ativos.length ? ativos : noMon;
    const t = el("div", {class: "tile"});
    if (ativos.length) t.classList.add("uso"); else if (noMon.length) t.classList.add("inativo");
    if (ativos.length > 1) t.classList.add("conflito");
    t.dataset.device = m.device;
    const w = m.w * esc - 6, h = m.h * esc - 6;
    Object.assign(t.style, {left: (ox + (m.x - x0) * esc + 3) + "px", top: (oy + (m.y - y0) * esc + 3) + "px", width: w + "px", height: h + "px"});
    const gr = el("div", {class: "gr", textContent: mostra.length ? mostra.map(l => "P" + pos(l)).join(" + ") : "—"});
    gr.style.fontSize = Math.max(12, Math.min(34, h * 0.32)) + "px";
    t.append(el("div", {class: "canto", textContent: "Tela " + m.num + (m.primario ? " ★" : "")}), gr,
      el("div", {class: "leg", textContent: mostra.length ? (ativos.length > 1 ? "⚠ " : "") + mostra.map(nomeDe).join(" + ") : "arraste uma posição aqui"}));
    iniciarArraste(t, {tipo: "tela", m});
    box.append(t);
  }
}

function renderLista() {
  const lista = $("#lista"); lista.innerHTML = "";
  $("#qtd").textContent = `${links.length} cadastrado(s) · ${links.filter(l => l.ativo).length} ativo(s)`;
  links.forEach(l => {
    const m = mon(l.monitor);
    const badge = el("div", {class: "badge" + (m ? "" : " sem"), title: "Arraste até uma tela do mapa"},
      el("small", {textContent: "POSIÇÃO"}), el("b", {textContent: pos(l)}), el("span", {textContent: m ? "→ Tela " + m.num : "sem tela"}));
    iniciarArraste(badge, {tipo: "card", l});
    const mudou = () => { marcarSujo(true); renderMapa(); };
    const nome = el("input", {class: "campo nome", value: l.nome || "", placeholder: "Nome do painel",
      oninput: e => { l.nome = e.target.value; mudou(); }});
    const ativo = el("input", {type: "checkbox", checked: !!l.ativo, onchange: e => { l.ativo = e.target.checked; marcarSujo(true); render(); }});
    const kiosk = el("input", {type: "checkbox", checked: l.kiosk !== false, onchange: e => { l.kiosk = e.target.checked; marcarSujo(true); }});
    const separado = el("input", {type: "checkbox", checked: !!l.perfil_separado, onchange: e => { l.perfil_separado = e.target.checked; marcarSujo(true); }});
    const auto = el("input", {type: "checkbox", checked: !!l.auto_refresh, onchange: e => { l.auto_refresh = e.target.checked; segs.disabled = !e.target.checked; marcarSujo(true); }});
    const segs = el("input", {class: "campo segs", type: "number", min: 5, step: 5, value: l.refresh_s || 300, disabled: !l.auto_refresh, title: "Intervalo em segundos (mínimo 5)",
      oninput: e => { l.refresh_s = parseInt(e.target.value, 10) || 300; marcarSujo(true); }});
    const url = el("input", {class: "campo url", value: l.url || "", placeholder: "https://...", inputMode: "url",
      oninput: e => { l.url = e.target.value; mudou(); }});
    const sel = el("select", {class: "campo sel", onchange: e => { trocarTela(l, e.target.value); }});
    if (!m) sel.append(el("option", {value: l.monitor || "", textContent: "(tela ausente)"}));
    for (const mm of estado.monitores)
      sel.append(el("option", {value: mm.device, textContent: `Tela ${mm.num} · ${mm.w}×${mm.h}${mm.primario ? " ★" : ""}`, selected: mm.device === l.monitor}));
    const acao = (nomeAcao, extra) => async () => {
      if (sujo) await salvar();
      try { const d = await api("/api/" + nomeAcao, {id: l.id, ...(extra || {})}); toast(d.msg || "OK"); }
      catch (e) { toast(e.message, true); }
    };
    const card = el("div", {class: "card" + (l.ativo ? "" : " off")},
      el("div", {class: "faixa"}), badge,
      el("div", {class: "meio"},
        el("div", {class: "l1"}, nome,
          el("label", {class: "chk"}, ativo, "Ativo"),
          el("label", {class: "chk"}, kiosk, "Tela cheia (kiosk)"),
          el("label", {class: "chk", title: "Usa um login próprio, diferente das outras telas"}, separado, "Login separado"),
          el("span", {class: "chk"}, el("label", {class: "chk"}, auto, "Auto refresh a cada"), segs, "s")),
        el("div", {class: "l2"}, el("label", {textContent: "URL"}), url, el("label", {textContent: "Tela"}), sel)),
      el("div", {class: "bts"},
        el("button", {class: "btn acesso", textContent: "🖥 Acessar", title: "Ver e usar esta tela pelo navegador",
          onclick: () => abrirRemoto(l)}),
        el("button", {class: "btn prim", textContent: "▶ Abrir", onclick: acao("abrir")}),
        el("button", {class: "btn", textContent: "🔑 Login", title: "Abre janela normal no PC para fazer login",
          onclick: () => { if (confirm("Abrir janela de login no PC dos monitores?\nAlguém no local precisa digitar o login.")) acao("abrir", {login: true})(); }}),
        el("button", {class: "btn", textContent: "■ Fechar", onclick: acao("fechar")}),
        el("button", {class: "btn perigo", textContent: "🗑 Remover", onclick: () => {
          if (!confirm(`Remover ${nomeDe(l)}?`)) return;
          links.splice(links.indexOf(l), 1); marcarSujo(true); render(); }})));
    lista.append(card);
  });
}

function trocarTela(l, device) {
  const antigo = l.monitor;
  if (antigo === device) return;
  for (const o of links) if (o !== l && o.monitor === device) o.monitor = antigo;
  l.monitor = device;
}

/* ---------------- arrastar (mouse + toque) ---------------- */
let drag = null;
function iniciarArraste(elm, origem) {
  elm.addEventListener("pointerdown", e => {
    if (e.button !== undefined && e.button !== 0) return;
    drag = {origem, x: e.clientX, y: e.clientY, ghost: null, alvo: null};
    elm.setPointerCapture(e.pointerId);
  });
  elm.addEventListener("pointermove", e => {
    if (!drag) return;
    if (!drag.ghost) {
      if (Math.abs(e.clientX - drag.x) + Math.abs(e.clientY - drag.y) < 6) return;
      const g = el("div", {id: "ghost", textContent: origem.tipo === "card" ? `P${pos(origem.l)} · ${nomeDe(origem.l)}` : `Tela ${origem.m.num} ⇄ solte em outra tela`});
      document.body.append(g); drag.ghost = g;
      status("Solte sobre uma tela do mapa. Se ela já tiver um link, os dois trocam de lugar.");
    }
    drag.ghost.style.left = (e.clientX + 14) + "px"; drag.ghost.style.top = (e.clientY + 10) + "px";
    const alvo = document.elementFromPoint(e.clientX, e.clientY)?.closest(".tile");
    if (drag.alvo !== alvo) { drag.alvo?.classList.remove("alvo"); alvo?.classList.add("alvo"); drag.alvo = alvo; }
  });
  const fim = async e => {
    if (!drag) return;
    const d = drag; drag = null;
    if (!d.ghost) {                         // clique simples
      if (origem.tipo === "tela") identificar(origem.m.device);
      return;
    }
    d.ghost.remove(); d.alvo?.classList.remove("alvo");
    if (!d.alvo || e.type === "pointercancel") { status("Arraste cancelado."); return; }
    const destino = d.alvo.dataset.device, mDest = mon(destino);
    let msg;
    if (origem.tipo === "card") {
      if (origem.l.monitor === destino) return;
      trocarTela(origem.l, destino);
      msg = `✔ Posição ${pos(origem.l)} vinculada à Tela ${mDest.num}`;
    } else {
      const a = origem.m.device; if (a === destino) return;
      for (const l of links) { if (l.monitor === a) l.monitor = destino; else if (l.monitor === destino) l.monitor = a; }
      msg = `✔ Telas ${origem.m.num} e ${mDest.num} trocadas`;
    }
    marcarSujo(true); render(); status(msg);
    await salvar(msg);
  };
  elm.addEventListener("pointerup", fim);
  elm.addEventListener("pointercancel", fim);
}

/* ---------------- ações globais ---------------- */
async function acaoGlobal(rota, corpo, confirmar) {
  if (confirmar && !confirm(confirmar)) return;
  if (sujo && rota === "abrir_todos") await salvar();
  try { const d = await api("/api/" + rota, corpo || {}); toast(d.msg || "OK"); } catch (e) { toast(e.message, true); }
}
function identificar(device) { acaoGlobal("identificar", device ? {device} : {}); }
$("#b-abrir").onclick = () => acaoGlobal("abrir_todos", {}, "Abrir todos os links nas telas agora?\n(As janelas atuais do painel serão reabertas.)");
$("#b-fechar").onclick = () => acaoGlobal("fechar_todos", {}, "Fechar todas as janelas do painel?");
$("#b-ident").onclick = () => identificar(null);
$("#b-recarregar-telas").onclick = () => acaoGlobal("recarregar", {});
$("#b-add").onclick = () => {
  const usados = new Set(links.map(l => l.monitor));
  const livre = estado.monitores.find(m => !usados.has(m.device)) || estado.monitores[0];
  links.push({id: null, nome: "", url: "", monitor: livre ? livre.device : "", kiosk: true, ativo: true, perfil_separado: false, auto_refresh: false, refresh_s: 300});
  marcarSujo(true); render();
  const ns = document.querySelectorAll(".nome"); ns[ns.length - 1]?.focus();
};
window.addEventListener("resize", () => estado && renderMapa());
window.addEventListener("beforeunload", e => { if (sujo) { e.preventDefault(); e.returnValue = ""; } });

/* ---------------- acesso remoto a uma tela ---------------- */
let rm = null;
const dormir = ms => new Promise(r => setTimeout(r, ms));
async function abrirRemoto(l) {
  if (sujo) await salvar();
  let d;
  try { d = await api("/api/remoto/iniciar", {id: l.id}); } catch (e) { toast(e.message, true); return; }
  rm = {id: l.id, seq: 0, w: 0, h: 0, vivo: true, fila: [], tmr: null, ultMove: 0, toque: null, quadros: 0};
  $("#rm-tit").textContent = `Tela ${d.tela ?? "?"} · ${d.nome}`;
  $("#rm-info").innerHTML = "";
  $("#rm-info").append(Object.assign(document.createElement("span"), {className: "vivo", textContent: "● ao vivo"}),
    " · clique na imagem para usar mouse e teclado");
  $("#rm-img").removeAttribute("src");
  $("#rm-carregando").classList.remove("oculto");
  $("#remoto").classList.remove("oculto");
  $("#rm-kbd").focus({preventScroll: true});
  loopQuadros();
}
async function fecharRemoto() {
  if (!rm) return;
  const id = rm.id; rm.vivo = false; rm = null;
  $("#remoto").classList.add("oculto");
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  try { await api("/api/remoto/encerrar", {id}); } catch (e) {}
}
async function loopQuadros() {
  const meu = rm;
  while (rm === meu && meu.vivo) {
    try {
      const r = await fetch(`/api/remoto/quadro?id=${encodeURIComponent(meu.id)}&seq=${meu.seq}`, {credentials: "same-origin", cache: "no-store"});
      if (rm !== meu) return;
      if (r.status === 401) { fecharRemoto(); mostrarLogin(); return; }
      if (r.status === 200) {
        meu.seq = +r.headers.get("X-Seq") || meu.seq;
        meu.w = +r.headers.get("X-W") || meu.w; meu.h = +r.headers.get("X-H") || meu.h;
        const u = URL.createObjectURL(await r.blob());
        const img = $("#rm-img"), velho = img.src;
        img.src = u;
        if (velho && velho.startsWith("blob:")) setTimeout(() => URL.revokeObjectURL(velho), 2000);
        $("#rm-carregando").classList.add("oculto");
      } else if (r.status >= 400) {
        const d = await r.json().catch(() => ({}));
        toast(d.erro || "Tela indisponível", true); fecharRemoto(); return;
      }
    } catch (e) { await dormir(1000); }
  }
}
function rmEnviar(ev, ja) {
  if (!rm) return;
  rm.fila.push(ev);
  if (ja) rmFlush(); else if (!rm.tmr) rm.tmr = setTimeout(rmFlush, 60);
}
async function rmFlush() {
  if (!rm) return;
  clearTimeout(rm.tmr); rm.tmr = null;
  if (rm.enviando) { rm.pendente = true; return; }      // um envio por vez: mantém a ordem das teclas
  const meu = rm;
  while (rm === meu && meu.fila.length) {
    const eventos = meu.fila.splice(0);
    meu.enviando = true;
    try { await api("/api/remoto/entrada", {id: meu.id, eventos}); }
    catch (e) { toast(e.message, true); }
    finally { meu.enviando = false; }
  }
}
function rmPos(e) {
  const img = $("#rm-img"), r = img.getBoundingClientRect();
  const w = rm.w || img.naturalWidth, h = rm.h || img.naturalHeight;
  return {x: Math.max(0, Math.min(w, (e.clientX - r.left) / r.width * w)),
          y: Math.max(0, Math.min(h, (e.clientY - r.top) / r.height * h)), esc: h / r.height};
}
const rmMods = e => (e.altKey ? 1 : 0) | (e.ctrlKey ? 2 : 0) | (e.metaKey ? 4 : 0) | (e.shiftKey ? 8 : 0);
const rmBtn = b => b === 2 ? "right" : b === 1 ? "middle" : "left";
(() => {
  const img = $("#rm-img");
  img.addEventListener("contextmenu", e => e.preventDefault());
  img.addEventListener("pointerdown", e => {
    if (!rm) return;
    e.preventDefault(); $("#rm-kbd").focus({preventScroll: true});
    img.setPointerCapture(e.pointerId);
    const p = rmPos(e);
    if (e.pointerType === "touch") { rm.toque = {x: e.clientX, y: e.clientY, moveu: false}; return; }
    rmEnviar({t: "down", x: p.x, y: p.y, btn: rmBtn(e.button), n: e.detail || 1, mods: rmMods(e)}, true);
  });
  img.addEventListener("pointermove", e => {
    if (!rm) return;
    const p = rmPos(e);
    if (e.pointerType === "touch") {
      if (!rm.toque) return;
      const dy = (rm.toque.y - e.clientY) * p.esc, dx = (rm.toque.x - e.clientX) * p.esc;
      if (Math.abs(dx) + Math.abs(dy) > 4) {
        rm.toque.moveu = true; rm.toque.x = e.clientX; rm.toque.y = e.clientY;
        rmEnviar({t: "wheel", x: p.x, y: p.y, dx, dy});
      }
      return;
    }
    const agora = performance.now();
    if (agora - rm.ultMove < 70) return;
    rm.ultMove = agora;
    rmEnviar({t: "move", x: p.x, y: p.y, b: e.buttons, btn: e.buttons & 2 ? "right" : "left", mods: rmMods(e)});
  });
  const solta = e => {
    if (!rm) return;
    const p = rmPos(e);
    if (e.pointerType === "touch") {
      if (rm.toque && !rm.toque.moveu && e.type === "pointerup") {
        rmEnviar({t: "down", x: p.x, y: p.y, btn: "left", n: 1});
        rmEnviar({t: "up", x: p.x, y: p.y, btn: "left", n: 1}, true);
      }
      rm.toque = null; return;
    }
    rmEnviar({t: "up", x: p.x, y: p.y, btn: rmBtn(e.button), n: e.detail || 1, mods: rmMods(e)}, true);
  };
  img.addEventListener("pointerup", solta);
  img.addEventListener("pointercancel", solta);
  img.addEventListener("wheel", e => {
    if (!rm) return;
    e.preventDefault();
    const p = rmPos(e), k = e.deltaMode === 1 ? 40 : e.deltaMode === 2 ? 800 : 1;
    rmEnviar({t: "wheel", x: p.x, y: p.y, dx: e.deltaX * k, dy: e.deltaY * k, mods: rmMods(e)});
  }, {passive: false});

  const kbd = $("#rm-kbd");
  const tecla = (e, tipo) => {
    if (!rm) return;
    const colar = (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "v";
    if (colar) return;                                   // deixa o evento "paste" acontecer
    if (e.key === "Unidentified" || e.key === "Process") return;   // teclado do celular: tratado no "input"
    e.preventDefault();
    const txt = tipo === "down" ? (e.key.length === 1 ? e.key : e.key === "Enter" ? "\r" : "") : "";
    rmEnviar({t: "key", tipo, key: e.key, code: e.code, kc: e.keyCode, mods: rmMods(e), text: txt}, true);
  };
  kbd.addEventListener("keydown", e => tecla(e, "down"));
  kbd.addEventListener("keyup", e => tecla(e, "up"));
  kbd.addEventListener("input", () => { if (rm && kbd.value) { rmEnviar({t: "texto", v: kbd.value}, true); } kbd.value = ""; });
  kbd.addEventListener("paste", e => {
    const t = (e.clipboardData || window.clipboardData).getData("text");
    e.preventDefault();
    if (t) rmEnviar({t: "texto", v: t}, true);
  });
  $("#rm-fechar").onclick = fecharRemoto;
  $("#rm-reload").onclick = () => rmEnviar({t: "recarregar"}, true);
  $("#rm-full").onclick = () => { const el = $("#remoto"); (document.fullscreenElement ? document.exitFullscreen() : el.requestFullscreen()).catch(() => {}); };
  $("#rm-teclado").onclick = () => kbd.focus();
  window.addEventListener("beforeunload", () => { if (rm) navigator.sendBeacon && fetch("/api/remoto/encerrar", {method: "POST", keepalive: true, headers: {"X-Painel": "1", "Content-Type": "application/json"}, body: JSON.stringify({id: rm.id})}); });
})();

/* ---------------- sessões do painel web ---------------- */
const hora = t => new Date(t * 1000).toLocaleString("pt-BR", {day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit"});
async function abrirSessoes() {
  $("#sessoes").classList.remove("oculto");
  await carregarSessoes();
}
async function carregarSessoes() {
  const lista = $("#ss-lista"); lista.innerHTML = "";
  let d;
  try { d = await api("/api/sessoes"); } catch (e) { toast(e.message, true); return; }
  const outras = d.sessoes.filter(x => !x.atual).length;
  $("#ss-todas").disabled = !outras;
  for (const x of d.sessoes) {
    const linha = el("div", {class: "ss-linha"},
      el("div", {class: "q"}, el("b", {textContent: `${x.ip} · ${x.navegador}`}),
        el("span", {textContent: `entrou ${hora(x.inicio)} · última atividade ${hora(x.ultimo)}`})),
      x.atual ? el("span", {class: "ss-eu", textContent: "esta sessão"})
              : el("button", {class: "btn perigo", textContent: "Derrubar", onclick: async () => {
                  if (!confirm(`Derrubar a sessão de ${x.ip}?`)) return;
                  try { const r = await api("/api/sessoes/derrubar", {id: x.id}); toast(r.msg); } catch (e) { toast(e.message, true); }
                  carregarSessoes(); }}));
    lista.append(linha);
  }
}
$("#b-sessoes").onclick = abrirSessoes;
$("#ss-fechar").onclick = () => $("#sessoes").classList.add("oculto");
$("#ss-atualizar").onclick = carregarSessoes;
$("#ss-todas").onclick = async () => {
  if (!confirm("Derrubar todas as outras sessões? Essas pessoas vão precisar digitar a senha de novo.")) return;
  try { const r = await api("/api/sessoes/derrubar", {todas: true}); toast(r.msg); } catch (e) { toast(e.message, true); }
  carregarSessoes();
};

/* ---------------- início + atualização periódica ---------------- */
setInterval(() => { if (!$("#tela-app").classList.contains("oculto") && !drag && !rm) carregar(false).catch(() => {}); }, 5000);
api("/api/estado").then(() => { mostrarApp(); return carregar(true); }).catch(() => mostrarLogin());
})();
</script>
</body>
</html>
'''


# --------------------------------------------------------------------------- tema
COR = {
    "roxo": "#392776", "roxo_esc": "#2a1c5a", "roxo_claro": "#5b4a9e",
    "ciano": "#33BCD5", "ciano_esc": "#239fb6", "ciano_txt": "#6FD2E4",
    "bg": "#f0eff6", "card": "#ffffff", "borda": "#D9D5E8",
    "ink": "#16122b", "mudo": "#5A5470", "desligado": "#b9b4cc",
    "perigo": "#c0392b", "perigo_bg": "#fbeaea",
}
FONTE = "Segoe UI"
F_TIT = (FONTE, 16, "bold")
F_SUB = (FONTE, 9)
F_SEC = (FONTE, 11, "bold")
F_TXT = (FONTE, 10)
F_NOME = (FONTE, 11, "bold")
F_BTN = (FONTE, 9, "bold")
F_PEQ = (FONTE, 8)


class Botao(tk.Label):
    """Botão plano com hover (o ttk do Windows não permite recolorir botões)."""
    ESTILOS = {
        "primario":   (COR["ciano"], "#ffffff", COR["ciano_esc"], "#ffffff"),
        "roxo":       (COR["roxo"], "#ffffff", COR["roxo_esc"], "#ffffff"),
        "contorno":   (COR["card"], COR["roxo"], COR["bg"], COR["roxo"]),
        "fantasma":   (COR["card"], COR["mudo"], COR["bg"], COR["roxo"]),
        "perigo":     (COR["card"], COR["perigo"], COR["perigo_bg"], COR["perigo"]),
        "cabecalho":  (COR["roxo"], "#ffffff", COR["roxo_claro"], "#ffffff"),
    }

    def __init__(self, master, texto, comando, estilo="contorno", fonte=F_BTN, padx=12, pady=6, **kw):
        bg, fg, hbg, hfg = self.ESTILOS[estilo]
        borda = COR["borda"] if estilo in ("contorno", "fantasma", "perigo") else bg
        super().__init__(master, text=texto, bg=bg, fg=fg, font=fonte, padx=padx, pady=pady,
                         cursor="hand2", highlightthickness=1, highlightbackground=borda,
                         highlightcolor=borda, **kw)
        self._cores = (bg, fg, hbg, hfg)
        self._cmd = comando
        self.bind("<Enter>", lambda e: self.configure(bg=hbg, fg=hfg))
        self.bind("<Leave>", lambda e: self.configure(bg=bg, fg=fg))
        self.bind("<Button-1>", lambda e: self._cmd())


def aplicar_estilo(root):
    st = ttk.Style(root)
    st.theme_use("clam")
    st.configure(".", font=F_TXT, background=COR["bg"], foreground=COR["ink"])
    st.configure("TEntry", fieldbackground="#ffffff", bordercolor=COR["borda"],
                 lightcolor=COR["borda"], darkcolor=COR["borda"], padding=5)
    st.map("TEntry", bordercolor=[("focus", COR["ciano"])], lightcolor=[("focus", COR["ciano"])])
    st.configure("Nome.TEntry", font=F_NOME)
    st.configure("TCombobox", fieldbackground="#ffffff", background="#ffffff", bordercolor=COR["borda"],
                 lightcolor=COR["borda"], darkcolor=COR["borda"], arrowcolor=COR["roxo"], padding=4)
    st.map("TCombobox", fieldbackground=[("readonly", "#ffffff")],
           selectbackground=[("readonly", "#ffffff")], selectforeground=[("readonly", COR["ink"])],
           bordercolor=[("focus", COR["ciano"])])
    st.configure("Card.TCheckbutton", background=COR["card"], foreground=COR["mudo"], font=F_PEQ,
                 indicatorcolor="#ffffff", indicatorbackground="#ffffff")
    st.map("Card.TCheckbutton", indicatorcolor=[("selected", COR["ciano"])],
           background=[("active", COR["card"])])
    st.configure("Bg.TCheckbutton", background=COR["bg"], foreground=COR["mudo"], font=F_PEQ)
    st.map("Bg.TCheckbutton", indicatorcolor=[("selected", COR["ciano"])], background=[("active", COR["bg"])])
    st.configure("Vertical.TScrollbar", background=COR["borda"], troughcolor=COR["bg"],
                 bordercolor=COR["bg"], arrowcolor=COR["roxo"], lightcolor=COR["borda"], darkcolor=COR["borda"])
    root.option_add("*TCombobox*Listbox.font", F_TXT)
    root.option_add("*TCombobox*Listbox.selectBackground", COR["roxo"])
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")


# --------------------------------------------------------------------------- interface
class App(tk.Tk):
    def __init__(self, minimizado=False):
        super().__init__()
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("mayk.cloud.dashmgr")
        except Exception:
            pass
        self.title(APP_NOME)
        self.geometry("1400x780")
        self.minsize(1080, 600)
        self.configure(bg=COR["bg"])
        aplicar_estilo(self)
        self.img_header = tk.PhotoImage(data="".join(LOGO_HEADER))
        self.img_overlay = tk.PhotoImage(data="".join(LOGO_OVERLAY))
        self.img_cor = tk.PhotoImage(data="".join(LOGO_COR))
        self.img_icone = tk.PhotoImage(data="".join(ICONE))
        self.iconphoto(True, self.img_icone)
        ico = os.path.join(BASE_DIR, "dashmgr.ico")
        if os.path.isfile(ico):
            try:
                self.iconbitmap(default=ico)
            except Exception:
                pass

        self.monitores = listar_monitores()
        self.cfg = carregar_config(self.monitores)
        self.linhas = []
        self._montar()
        self._carregar_linhas()
        iniciar_atalho_global(lambda: self.log("Tela fechada pelo atalho Ctrl+Alt+Q.")
                              if fechar_tela_sob_mouse() else None)
        self.web = PainelWeb(ao_mudar=lambda: self.after(0, self.recarregar_externo),
                             ao_identificar=lambda dev: self.after(0, lambda: self.identificar(
                                 [m for m in self.monitores if m["device"] == dev] or None)))
        self.iniciar_web()
        iniciar_guarda_cookies(lambda: self.cfg)
        iniciar_auto_refresh(lambda: self.cfg)
        self.protocol("WM_DELETE_WINDOW", self.sair)
        if minimizado:
            self.iconify()

    # ---- helpers
    def rotulo_mon(self, m):
        p = "  ★ principal" if m["primario"] else ""
        return f"Tela {m['num']}  ·  {m['w']}×{m['h']}{p}"

    def mon_por_rotulo(self, rot):
        for m in self.monitores:
            if self.rotulo_mon(m) == rot:
                return m
        return None

    # ---- layout
    def _montar(self):
        # cabeçalho roxo com logo
        cab = tk.Frame(self, bg=COR["roxo"], height=72)
        cab.pack(fill="x")
        cab.pack_propagate(False)
        tk.Label(cab, image=self.img_header, bg=COR["roxo"]).pack(side="left", padx=(22, 18))
        tk.Frame(cab, bg=COR["roxo_claro"], width=1).pack(side="left", fill="y", pady=16)
        tt = tk.Frame(cab, bg=COR["roxo"])
        tt.pack(side="left", padx=18)
        tk.Label(tt, text="Gerenciador de dashboards", font=F_TIT, fg="#ffffff", bg=COR["roxo"]).pack(anchor="w")
        tk.Label(tt, text=f"Cada sistema na tela certa, em tela cheia  ·  v{APP_VERSAO}", font=F_SUB,
                 fg=COR["ciano_txt"], bg=COR["roxo"]).pack(anchor="w")
        Botao(cab, "⚙  Configurações", self.configuracoes, "cabecalho").pack(side="right", padx=(0, 22))
        self.lbl_chip = tk.Label(cab, font=F_BTN, fg=COR["roxo"], bg=COR["ciano_txt"], padx=12, pady=4)
        self.lbl_chip.pack(side="right", padx=12)
        self.lbl_web = tk.Label(cab, font=F_BTN, fg="#ffffff", bg=COR["roxo_claro"], padx=12, pady=4, cursor="hand2")
        self.lbl_web.pack(side="right")
        self.lbl_web.bind("<Button-1>", lambda e: self.copiar_endereco_web())
        tk.Frame(self, bg=COR["ciano"], height=3).pack(fill="x")

        # rodapé (empacotado antes do corpo para ficar sempre visível)
        rod = tk.Frame(self, bg=COR["ink"])
        rod.pack(fill="x", side="bottom")
        self.status = tk.StringVar(value="Dica: Ctrl+Alt+Q fecha a tela do painel que estiver sob o mouse.")
        tk.Label(rod, textvariable=self.status, font=F_PEQ, fg="#e6e3f0", bg=COR["ink"],
                 anchor="w", padx=14, pady=6).pack(side="left", fill="x", expand=True)
        tk.Label(rod, text=f"{APP_NOME} v{APP_VERSAO}  ·  {APP_CREDITOS}",
                 font=F_PEQ, fg=COR["ciano_txt"], bg=COR["ink"], padx=14).pack(side="right")

        # área superior: mapa das telas + ações
        topo = tk.Frame(self, bg=COR["bg"])
        topo.pack(fill="x", padx=20, pady=(16, 8))

        cmapa = tk.Frame(topo, bg=COR["card"], highlightthickness=1, highlightbackground=COR["borda"])
        cmapa.pack(side="left", fill="both", expand=True)
        hm = tk.Frame(cmapa, bg=COR["card"])
        hm.pack(fill="x", padx=14, pady=(10, 0))
        tk.Label(hm, text="Mapa das telas", font=F_SEC, fg=COR["roxo"], bg=COR["card"]).pack(side="left")
        tk.Label(hm, text="arraste a posição entre as telas", font=F_PEQ,
                 fg=COR["mudo"], bg=COR["card"]).pack(side="left", padx=10)
        Botao(hm, "↻ Redetectar", self.redetectar, "fantasma", padx=8, pady=3).pack(side="right")
        Botao(hm, "◎ Identificar todas", self.identificar, "fantasma", padx=8, pady=3).pack(side="right", padx=6)
        self.mapa = tk.Canvas(cmapa, height=170, bg=COR["card"], highlightthickness=0)
        self.mapa.pack(fill="both", expand=True, padx=14, pady=10)
        self.mapa.bind("<Configure>", lambda e: self.desenhar_mapa())
        # movimento/soltura no widget (os itens do mapa são redesenhados durante o arraste)
        self.mapa.bind("<B1-Motion>", self._drag_mov)
        self.mapa.bind("<ButtonRelease-1>", self._drag_fim)

        acoes = tk.Frame(topo, bg=COR["bg"])
        acoes.pack(side="right", fill="y", padx=(16, 0))
        Botao(acoes, "▶   ABRIR TODOS", self.abrir, "primario", fonte=(FONTE, 13, "bold"),
              padx=28, pady=14).pack(fill="x")
        Botao(acoes, "■   Fechar todos os painéis", self.fechar, "contorno", pady=9).pack(fill="x", pady=(10, 0))
        Botao(acoes, "↻   Recarregar telas", self.recarregar, "contorno", pady=9).pack(fill="x", pady=(8, 0))
        Botao(acoes, "💾   Salvar configuração", self.salvar, "contorno", pady=9).pack(fill="x", pady=(8, 0))
        self.var_startup = tk.BooleanVar(value=inicia_com_windows())
        ttk.Checkbutton(acoes, text="Abrir automaticamente ao iniciar o Windows", style="Bg.TCheckbutton",
                        variable=self.var_startup, command=self.toggle_startup).pack(anchor="w", pady=(12, 0))

        # título da lista
        sec = tk.Frame(self, bg=COR["bg"])
        sec.pack(fill="x", padx=20, pady=(8, 6))
        tk.Frame(sec, bg=COR["ciano"], width=4, height=18).pack(side="left", padx=(0, 8))
        tk.Label(sec, text="Links", font=F_SEC, fg=COR["roxo"], bg=COR["bg"]).pack(side="left")
        self.lbl_qtd = tk.Label(sec, font=F_PEQ, fg=COR["mudo"], bg=COR["bg"])
        self.lbl_qtd.pack(side="left", padx=8)
        Botao(sec, "+  Adicionar link", lambda: self.add_linha(), "roxo", padx=12, pady=5).pack(side="right")

        # lista rolável de cartões
        corpo = tk.Frame(self, bg=COR["bg"])
        corpo.pack(fill="both", expand=True, padx=(20, 8), pady=(0, 10))
        self.canvas = tk.Canvas(corpo, bg=COR["bg"], highlightthickness=0)
        sb = ttk.Scrollbar(corpo, orient="vertical", command=self.canvas.yview)
        self.lista = tk.Frame(self.canvas, bg=COR["bg"])
        self.lista.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        jan = self.canvas.create_window((0, 0), window=self.lista, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(jan, width=e.width - 4))
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y", padx=(4, 0))
        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))

        self.atualizar_chip()

    def atualizar_chip(self):
        n = len(self.monitores)
        self.lbl_chip.configure(text=f"{n} tela{'s' if n != 1 else ''} detectada{'s' if n != 1 else ''}")

    # ---- mapa
    def desenhar_mapa(self):
        c = self.mapa
        c.delete("all")
        self._tiles = []
        if not self.monitores:
            return
        W, H = max(c.winfo_width(), 50), max(c.winfo_height(), 50)
        x0 = min(m["x"] for m in self.monitores)
        y0 = min(m["y"] for m in self.monitores)
        x1 = max(m["x"] + m["w"] for m in self.monitores)
        y1 = max(m["y"] + m["h"] for m in self.monitores)
        esc = min((W - 8) / (x1 - x0), (H - 8) / (y1 - y0))
        ox = (W - (x1 - x0) * esc) / 2
        oy = (H - (y1 - y0) * esc) / 2

        uso = {}
        for v in self.linhas:
            m = self.mon_por_rotulo(v["monitor"].get())
            if m:
                uso.setdefault(m["device"], []).append(v)
        alvo = getattr(self, "_drag_alvo", None)

        for m in self.monitores:
            ax = ox + (m["x"] - x0) * esc + 3
            ay = oy + (m["y"] - y0) * esc + 3
            bx = ax + m["w"] * esc - 6
            by = ay + m["h"] * esc - 6
            self._tiles.append((m, ax, ay, bx, by))
            links = uso.get(m["device"], [])
            ativos = [v for v in links if v["ativo"].get()]
            conflito = len(ativos) > 1
            if ativos:
                fill, out, fg, fg2 = COR["roxo"], (COR["perigo"] if conflito else COR["ciano"]), "#ffffff", COR["ciano_txt"]
            elif links:
                fill, out, fg, fg2 = COR["desligado"], COR["borda"], "#ffffff", COR["roxo"]
            else:
                fill, out, fg, fg2 = COR["bg"], COR["borda"], COR["desligado"], COR["mudo"]
            larg = 2
            if alvo is m:
                out, larg = COR["ciano"], 5
            tag = f"m{m['num']}"
            c.create_rectangle(ax, ay, bx, by, fill=fill, outline=out, width=larg, tags=tag)
            if ativos:
                c.create_rectangle(ax, by - 4, bx, by, fill=out, outline="", tags=tag)
            # canto: número físico da tela
            c.create_text(ax + 6, ay + 4, text=f"Tela {m['num']}", anchor="nw",
                          font=(FONTE, 7, "bold"), fill=fg2, tags=tag)
            tam = max(10, min(26, int((by - ay) * 0.32)))
            mostra = ativos or links
            if mostra:
                grande = " + ".join(f"P{self.posicao(v)}" for v in mostra)
                nomes = [v["nome"].get().strip() or v["url"].get().strip() or "(sem nome)" for v in mostra]
                legenda = ("⚠ " if conflito else "") + " + ".join(nomes)
            else:
                grande, legenda = "—", "arraste uma posição aqui"
            c.create_text((ax + bx) / 2, (ay + by) / 2 - tam * 0.25, text=grande,
                          font=(FONTE, tam, "bold"), fill=fg, tags=tag)
            maxc = max(4, int((bx - ax) / 6.5))
            if len(legenda) > maxc:
                legenda = legenda[:maxc - 1] + "…"
            c.create_text((ax + bx) / 2, (ay + by) / 2 + tam * 0.8, text=legenda,
                          font=F_PEQ, fill=fg2, tags=tag)
            c.tag_bind(tag, "<ButtonPress-1>", lambda e, mm=m: self._drag_ini(e, ("tela", mm)))
            c.tag_bind(tag, "<Enter>", lambda e: c.configure(cursor="fleur"))
            c.tag_bind(tag, "<Leave>", lambda e: c.configure(cursor=""))

    # ---- arrastar e soltar (posição → tela, tela ↔ tela)
    def _tile_sob_ponteiro(self):
        px, py = self.winfo_pointerxy()
        cx, cy = px - self.mapa.winfo_rootx(), py - self.mapa.winfo_rooty()
        for m, ax, ay, bx, by in getattr(self, "_tiles", []):
            if ax <= cx <= bx and ay <= cy <= by:
                return m
        return None

    def _drag_ini(self, e, origem):
        self._drag = {"origem": origem, "x": e.x_root, "y": e.y_root, "ghost": None}
        self._drag_alvo = None

    def _drag_mov(self, e):
        d = getattr(self, "_drag", None)
        if not d:
            return
        if not d["ghost"]:
            if abs(e.x_root - d["x"]) + abs(e.y_root - d["y"]) < 6:
                return
            g = tk.Toplevel(self)
            g.overrideredirect(True)
            g.attributes("-topmost", True)
            try:
                g.attributes("-alpha", 0.9)
            except Exception:
                pass
            tipo, obj = d["origem"]
            if tipo == "card":
                nome = obj["nome"].get().strip() or obj["url"].get().strip() or "(sem nome)"
                txt = f"  P{self.posicao(obj)}  ·  {nome}  "
            else:
                txt = f"  Tela {obj['num']}  ⇄  solte em outra tela para trocar  "
            tk.Label(g, text=txt, font=F_BTN, fg="#ffffff", bg=COR["roxo"], padx=8, pady=6,
                     highlightthickness=2, highlightbackground=COR["ciano"]).pack()
            d["ghost"] = g
            self.status.set("Solte sobre uma tela do mapa para vincular. Se a tela já tiver um link, eles trocam de lugar.")
        d["ghost"].geometry(f"+{e.x_root + 14}+{e.y_root + 10}")
        alvo = self._tile_sob_ponteiro()
        if alvo is not self._drag_alvo:
            self._drag_alvo = alvo
            self.desenhar_mapa()

    def _drag_fim(self, e):
        d = getattr(self, "_drag", None)
        self._drag = None
        if not d:
            return
        tipo, obj = d["origem"]
        if not d["ghost"]:                      # foi só um clique
            if tipo == "tela":
                self.identificar([obj])
            return
        d["ghost"].destroy()
        alvo = self._tile_sob_ponteiro()
        self._drag_alvo = None
        if not alvo:
            self.desenhar_mapa()
            self.status.set("Arraste cancelado.")
            return
        rot_alvo = self.rotulo_mon(alvo)
        if tipo == "card":
            v = obj
            rot_antigo = v["monitor"].get()
            if rot_antigo == rot_alvo:
                self.desenhar_mapa()
                return
            # quem estava na tela de destino vai para a tela antiga (troca)
            for o in self.linhas:
                if o is not v and o["monitor"].get() == rot_alvo:
                    o["monitor"].set(rot_antigo)
            v["monitor"].set(rot_alvo)
            msg = f"✔ Posição {self.posicao(v)} vinculada à Tela {alvo['num']} (salvo)."
        else:
            rot_origem = self.rotulo_mon(obj)
            if rot_origem == rot_alvo:
                self.desenhar_mapa()
                return
            a = [o for o in self.linhas if o["monitor"].get() == rot_origem]
            b = [o for o in self.linhas if o["monitor"].get() == rot_alvo]
            for o in a:
                o["monitor"].set(rot_alvo)
            for o in b:
                o["monitor"].set(rot_origem)
            msg = f"✔ Telas {obj['num']} e {alvo['num']} trocadas (salvo)."
        self._apos_mudanca()
        self.salvar()
        self.status.set(msg)

    # ---- cartões
    def _carregar_linhas(self):
        for item in self.cfg["links"]:
            self.add_linha(item, redesenhar=False)
        self._apos_mudanca()

    def _apos_mudanca(self, *_):
        for v in self.linhas:
            self._pintar_card(v)
        n_at = sum(1 for v in self.linhas if v["ativo"].get())
        self.lbl_qtd.configure(text=f"{len(self.linhas)} cadastrado(s) · {n_at} ativo(s)")
        self.desenhar_mapa()

    def posicao(self, v):
        return self.linhas.index(v) + 1

    def _pintar_card(self, v):
        m = self.mon_por_rotulo(v["monitor"].get())
        ativo = v["ativo"].get()
        v["faixa"].configure(bg=COR["ciano"] if ativo else COR["desligado"])
        bg = COR["roxo"] if (ativo and m) else COR["desligado"]
        for w in (v["badge"], v["b_rot"], v["b_num"], v["b_tela"]):
            w.configure(bg=bg)
        v["b_num"].configure(text=str(self.posicao(v)))
        v["b_tela"].configure(text=f"→ Tela {m['num']}" if m else "sem tela")

    def add_linha(self, item=None, redesenhar=True):
        if item is None:
            usados = {self.mon_por_rotulo(x["monitor"].get())["device"]
                      for x in self.linhas if self.mon_por_rotulo(x["monitor"].get())}
            livre = next((m["device"] for m in self.monitores if m["device"] not in usados),
                         self.monitores[0]["device"] if self.monitores else "")
            item = {"id": uuid.uuid4().hex[:8], "nome": "", "url": "", "monitor": livre,
                    "kiosk": True, "ativo": True}

        card = tk.Frame(self.lista, bg=COR["card"], highlightthickness=1, highlightbackground=COR["borda"])
        card.pack(fill="x", pady=4)
        v = {
            "id": item["id"],
            "ativo": tk.BooleanVar(value=item.get("ativo", True)),
            "nome": tk.StringVar(value=item.get("nome", "")),
            "url": tk.StringVar(value=item.get("url", "")),
            "kiosk": tk.BooleanVar(value=item.get("kiosk", True)),
            "separado": tk.BooleanVar(value=item.get("perfil_separado", False)),
            "auto": tk.BooleanVar(value=item.get("auto_refresh", False)),
            "refresh_s": tk.StringVar(value=str(item.get("refresh_s") or 300)),
            "monitor": tk.StringVar(),
            "frame": card,
            "device_original": item.get("monitor"),
        }
        mon = resolver_monitor(item, self.monitores)
        v["monitor"].set(self.rotulo_mon(mon) if mon else f"(tela ausente: {item.get('monitor')})")
        v["item_original"] = dict(item)

        v["faixa"] = tk.Frame(card, bg=COR["ciano"], width=5)
        v["faixa"].pack(side="left", fill="y")
        v["badge"] = tk.Frame(card, bg=COR["roxo"], width=74, cursor="fleur")
        v["badge"].pack(side="left", fill="y", padx=(0, 12))
        v["badge"].pack_propagate(False)
        v["b_rot"] = tk.Label(v["badge"], text="POSIÇÃO", font=(FONTE, 7, "bold"), fg=COR["ciano_txt"],
                              bg=COR["roxo"], cursor="fleur")
        v["b_rot"].pack(pady=(8, 0))
        v["b_num"] = tk.Label(v["badge"], font=(FONTE, 20, "bold"), fg="#ffffff", bg=COR["roxo"], cursor="fleur")
        v["b_num"].pack()
        v["b_tela"] = tk.Label(v["badge"], font=(FONTE, 7), fg="#e6e3f0", bg=COR["roxo"], cursor="fleur")
        v["b_tela"].pack()
        for w in (v["badge"], v["b_rot"], v["b_num"], v["b_tela"]):
            w.bind("<ButtonPress-1>", lambda e, vv=v: self._drag_ini(e, ("card", vv)))
            w.bind("<B1-Motion>", self._drag_mov)
            w.bind("<ButtonRelease-1>", self._drag_fim)

        meio = tk.Frame(card, bg=COR["card"])
        meio.pack(side="left", fill="both", expand=True, pady=8)
        l1 = tk.Frame(meio, bg=COR["card"])
        l1.pack(fill="x")
        e_nome = ttk.Entry(l1, textvariable=v["nome"], style="Nome.TEntry", font=F_NOME, width=28)
        e_nome.pack(side="left")
        ttk.Checkbutton(l1, text="Ativo", variable=v["ativo"], style="Card.TCheckbutton").pack(side="left", padx=(14, 4))
        ttk.Checkbutton(l1, text="Tela cheia (kiosk)", variable=v["kiosk"], style="Card.TCheckbutton").pack(side="left", padx=4)
        ttk.Checkbutton(l1, text="Login separado", variable=v["separado"], style="Card.TCheckbutton").pack(side="left", padx=4)
        ttk.Checkbutton(l1, text="Auto refresh a cada", variable=v["auto"], style="Card.TCheckbutton").pack(side="left", padx=(4, 2))
        ttk.Spinbox(l1, textvariable=v["refresh_s"], from_=REFRESH_MIN_S, to=86400, increment=5, width=6).pack(side="left")
        tk.Label(l1, text="s", font=F_PEQ, fg=COR["mudo"], bg=COR["card"]).pack(side="left", padx=(2, 0))

        l2 = tk.Frame(meio, bg=COR["card"])
        l2.pack(fill="x", pady=(6, 0))
        tk.Label(l2, text="URL", font=F_PEQ, fg=COR["mudo"], bg=COR["card"]).pack(side="left", padx=(0, 6))
        ttk.Entry(l2, textvariable=v["url"]).pack(side="left", fill="x", expand=True)
        tk.Label(l2, text="Tela", font=F_PEQ, fg=COR["mudo"], bg=COR["card"]).pack(side="left", padx=(12, 6))
        ttk.Combobox(l2, textvariable=v["monitor"], width=26, state="readonly",
                     values=[self.rotulo_mon(m) for m in self.monitores]).pack(side="left")

        bts = tk.Frame(card, bg=COR["card"])
        bts.pack(side="right", padx=12)
        g1 = tk.Frame(bts, bg=COR["card"])
        g1.pack(pady=(0, 4))
        Botao(g1, "▶ Abrir", lambda: self.abrir_um(v), "primario", padx=6, pady=4, width=9).pack(side="left", padx=2)
        Botao(g1, "🔑 Login", lambda: self.abrir_um(v, kiosk=False), "contorno", padx=6, pady=4, width=9).pack(side="left", padx=2)
        g2 = tk.Frame(bts, bg=COR["card"])
        g2.pack()
        Botao(g2, "■ Fechar", lambda: self.fechar_um(v), "contorno", padx=6, pady=4, width=9).pack(side="left", padx=2)
        Botao(g2, "🗑 Remover", lambda: self.remover(v), "perigo", padx=6, pady=4, width=9).pack(side="left", padx=2)

        for var in (v["ativo"], v["monitor"], v["nome"], v["url"]):
            var.trace_add("write", self._apos_mudanca)
        for var in (v["auto"], v["refresh_s"]):          # auto refresh vale na hora
            var.trace_add("write", lambda *_: self.coletar())
        self.linhas.append(v)
        if redesenhar:
            self._apos_mudanca()
            e_nome.focus_set()

    def remover(self, v):
        nome = v["nome"].get().strip() or "este link"
        if not messagebox.askyesno(APP_NOME, f"Remover {nome}?"):
            return
        v["frame"].destroy()
        self.linhas.remove(v)
        self._apos_mudanca()

    # ---- dados
    def coletar(self):
        links = []
        for v in self.linhas:
            mon = self.mon_por_rotulo(v["monitor"].get())
            links.append({
                "id": v["id"], "nome": v["nome"].get().strip(), "url": v["url"].get().strip(),
                "monitor": mon["device"] if mon else v["device_original"],
                "monitor_hwid": mon.get("hwid", "") if mon else v["item_original"].get("monitor_hwid", ""),
                "monitor_pos": [mon["x"], mon["y"]] if mon else v["item_original"].get("monitor_pos"),
                "kiosk": v["kiosk"].get(), "ativo": v["ativo"].get(),
                "perfil_separado": v["separado"].get(),
                "auto_refresh": v["auto"].get(),
                "refresh_s": _segundos(v["refresh_s"].get()),
            })
        self.cfg["links"] = links
        return self.cfg

    def salvar(self, aplicar=True):
        try:
            antigo = carregar_config(self.monitores)
        except Exception:
            antigo = {"links": []}
        novo = self.coletar()
        salvar_config(novo)
        if aplicar:
            aplicar_mudancas_async(antigo, novo, self.log)
        self.status.set(f"✔ Configuração salva em {CONFIG_PATH}")

    # ---- ações
    def log(self, msg):
        self.after(0, lambda: self.status.set(msg))

    def abrir(self):
        self.salvar(aplicar=False)        # ABRIR TODOS já reabre tudo
        cfg = json.loads(json.dumps(self.cfg))
        threading.Thread(target=abrir_todos, args=(cfg, self.monitores, self.log), daemon=True).start()

    def abrir_um(self, v, kiosk=None):
        url = v["url"].get().strip()
        mon = self.mon_por_rotulo(v["monitor"].get())
        if not url or not mon:
            messagebox.showwarning(APP_NOME, "Preencha a URL e escolha a tela.")
            return
        self.coletar()
        item = {"id": v["id"], "url": url, "kiosk": v["kiosk"].get(), "perfil_separado": v["separado"].get()}
        extras = ()
        if kiosk is False:
            extras = ("chrome://settings/onStartup",)
            messagebox.showinfo(APP_NOME,
                "Vai abrir uma janela normal com 2 abas:\n\n"
                "1) Aba 'Configurações' → em 'Ao iniciar', escolha\n"
                "    \"Continuar de onde parou\".  (só precisa fazer 1 vez)\n\n"
                "2) Aba do sistema → faça o login normalmente\n"
                "    (marque 'Lembrar de mim' / 'Manter conectado', se houver).\n\n"
                "3) Feche essa janela pelo X e clique em '↻ Recarregar telas'.\n\n"
                "O login vale para TODOS os links do mesmo sistema\n"
                "(exceto os marcados como 'Login separado').")

        def tarefa():
            try:
                fechar_perfil(self.cfg, v["id"])
                abrir_link(self.cfg, item, mon, kiosk=kiosk, extras=extras)
                self.log(f"Aberto na Tela {mon['num']}: {url}")
            except Exception as e:
                self.log(f"[ERRO] {e}")
        threading.Thread(target=tarefa, daemon=True).start()

    def fechar_um(self, v):
        nome = v["nome"].get().strip() or v["url"].get().strip()
        self.coletar()

        def tarefa():
            self.log(f"Fechando '{nome}'...")
            fechar_perfil(self.cfg, v["id"])
            self.log(f"'{nome}' fechado.")
        threading.Thread(target=tarefa, daemon=True).start()

    def fechar(self):
        cfg = self.coletar()
        threading.Thread(target=lambda: (fechar_paineis(cfg), self.log("Painéis fechados.")), daemon=True).start()

    def recarregar(self):
        cfg = self.coletar()
        threading.Thread(target=lambda: self.log(f"↻ {recarregar_telas(cfg)} tela(s) recarregada(s).")
                         , daemon=True).start()

    def identificar(self, monitores=None):
        janelas = []
        for m in (monitores or self.monitores):
            t = tk.Toplevel(self)
            t.overrideredirect(True)
            t.attributes("-topmost", True)
            t.configure(bg=COR["roxo"])
            t.geometry(f"{m['w']}x{m['h']}+{m['x']}+{m['y']}")
            tk.Frame(t, bg=COR["ciano"], height=10).pack(fill="x", side="top")
            tk.Label(t, image=self.img_overlay, bg=COR["roxo"]).pack(side="bottom", pady=40)
            caixa = tk.Frame(t, bg=COR["roxo"])
            caixa.pack(expand=True)
            tk.Label(caixa, text="TELA", fg=COR["ciano_txt"], bg=COR["roxo"],
                     font=(FONTE, max(18, m["h"] // 30), "bold")).pack()
            tk.Label(caixa, text=str(m["num"]), fg="#ffffff", bg=COR["roxo"],
                     font=(FONTE, max(80, m["h"] // 4), "bold")).pack()
            tk.Label(caixa, text=f"{m['w']}×{m['h']}   ·   {m['device'].replace(chr(92) * 2 + '.' + chr(92), '')}",
                     fg=COR["ciano_txt"], bg=COR["roxo"], font=(FONTE, 18)).pack()
            t.bind("<Button-1>", lambda e: [j.destroy() for j in janelas if j.winfo_exists()])
            janelas.append(t)
        self.after(4000, lambda: [j.destroy() for j in janelas if j.winfo_exists()])

    def redetectar(self):
        self.coletar()
        self.monitores = listar_monitores()
        for v in list(self.linhas):
            v["frame"].destroy()
        self.linhas.clear()
        self._carregar_linhas()
        self.atualizar_chip()
        self.status.set(f"{len(self.monitores)} monitor(es) detectado(s).")

    def toggle_startup(self):
        try:
            if self.var_startup.get():
                self.salvar()
                os.makedirs(STARTUP_DIR, exist_ok=True)
                alvo, args = comando_inicializacao()
                ico = os.path.join(BASE_DIR, "dashmgr.ico")
                criar_atalho(STARTUP_CMD, alvo, args, ico if os.path.isfile(ico) else "")
                self.status.set("Inicialização automática ativada (abre 20 s após o logon).")
            else:
                for arq in [STARTUP_CMD, STARTUP_CMD_TODOS] + STARTUP_ANTIGOS:
                    if os.path.isfile(arq):
                        try:
                            os.remove(arq)
                        except PermissionError:
                            self.var_startup.set(True)
                            messagebox.showwarning(APP_NOME, "A inicialização foi configurada pelo instalador.\n"
                                                   "Para desativar, rode o desinstalar.bat como administrador.")
                            return
                self.status.set("Inicialização automática desativada.")
        except Exception as e:
            messagebox.showerror(APP_NOME, str(e))

    # ---- painel web
    def iniciar_web(self):
        w = cfg_web(self.cfg)
        self.web.parar()
        if not w.get("ativo"):
            self.lbl_web.configure(text="🌐 Web desligado", bg=COR["roxo_claro"])
            return
        try:
            self.web.iniciar(w.get("porta", WEB_PORTA_PADRAO))
            end = self.web.enderecos()
            self.lbl_web.configure(text=f"🌐 {end[0]}", bg=COR["roxo_claro"])
            self.status.set("Painel web ativo em " + "  ·  ".join(end) + "   (clique no endereço para copiar)")
            if not w.get("senha_hash"):
                self.status.set("⚠ Defina a senha do painel web em Configurações para liberar o acesso pelo navegador.")
        except OSError as e:
            self.lbl_web.configure(text="🌐 Web: erro", bg=COR["perigo"])
            self.status.set(f"[ERRO] Painel web não iniciou na porta {w.get('porta')}: {e}")

    def copiar_endereco_web(self):
        end = self.web.enderecos()
        if end:
            self.clipboard_clear()
            self.clipboard_append(end[0])
            self.status.set(f"Endereço copiado: {end[0]}")

    def recarregar_externo(self):
        """Alguém salvou pelo navegador: recarrega os cartões a partir do arquivo."""
        try:
            self.cfg = carregar_config(self.monitores)
        except Exception as e:
            self.status.set(f"[ERRO] {e}")
            return
        for v in list(self.linhas):
            v["frame"].destroy()
        self.linhas.clear()
        self._carregar_linhas()
        self.status.set("↻ Configuração atualizada pelo painel web.")

    def sair(self):
        try:
            salvar_cookies(self.cfg)
            self.web.parar()
        finally:
            self.destroy()

    def configuracoes(self):
        d = tk.Toplevel(self)
        d.title("Configurações")
        d.configure(bg=COR["card"])
        d.transient(self)
        d.grab_set()
        d.resizable(False, False)
        topo = tk.Frame(d, bg=COR["roxo"])
        topo.pack(fill="x")
        tk.Label(topo, text="Configurações", font=F_SEC, fg="#ffffff", bg=COR["roxo"],
                 padx=16, pady=10).pack(side="left")
        tk.Frame(d, bg=COR["ciano"], height=3).pack(fill="x")
        corpo = tk.Frame(d, bg=COR["card"], padx=16, pady=12)
        corpo.pack(fill="both")

        vc = tk.StringVar(value=self.cfg.get("chrome_path", ""))
        vp = tk.StringVar(value=self.cfg.get("perfis_dir", PERFIS_PADRAO))
        va = tk.StringVar(value=str(self.cfg.get("atraso_s", 1.5)))
        campos = (("Caminho do chrome.exe", vc), ("Pasta dos perfis (logins salvos)", vp),
                  ("Atraso entre janelas (segundos)", va))
        for i, (rot, var) in enumerate(campos):
            tk.Label(corpo, text=rot, font=F_PEQ, fg=COR["mudo"], bg=COR["card"]).grid(
                row=i * 2, column=0, sticky="w", pady=(8 if i else 0, 2))
            ttk.Entry(corpo, textvariable=var, width=72).grid(row=i * 2 + 1, column=0, sticky="we")
        Botao(corpo, "Procurar…", lambda: vc.set(
            filedialog.askopenfilename(filetypes=[("chrome.exe", "chrome.exe")]) or vc.get()),
            "fantasma", padx=8, pady=3).grid(row=1, column=1, padx=(6, 0))
        tk.Label(corpo, text=f"A pasta dos perfis precisa conter '{MARCADOR_PERFIL}' no caminho.",
                 font=F_PEQ, fg=COR["mudo"], bg=COR["card"]).grid(row=6, column=0, sticky="w", pady=(10, 0))

        w = cfg_web(self.cfg)
        tk.Frame(corpo, bg=COR["borda"], height=1).grid(row=7, column=0, columnspan=2, sticky="we", pady=12)
        tk.Label(corpo, text="Painel web (acesso remoto pelo navegador)", font=F_SEC, fg=COR["roxo"],
                 bg=COR["card"]).grid(row=8, column=0, sticky="w")
        vw = tk.BooleanVar(value=w.get("ativo", True))
        ttk.Checkbutton(corpo, text="Ativar painel web", variable=vw, style="Card.TCheckbutton").grid(
            row=9, column=0, sticky="w", pady=(6, 0))
        vporta = tk.StringVar(value=str(w.get("porta", WEB_PORTA_PADRAO)))
        vsenha = tk.StringVar()
        tk.Label(corpo, text="Porta", font=F_PEQ, fg=COR["mudo"], bg=COR["card"]).grid(row=10, column=0, sticky="w", pady=(8, 2))
        ttk.Entry(corpo, textvariable=vporta, width=10).grid(row=11, column=0, sticky="w")
        tk.Label(corpo, text="Nova senha de acesso (deixe em branco para manter a atual)", font=F_PEQ,
                 fg=COR["mudo"], bg=COR["card"]).grid(row=12, column=0, sticky="w", pady=(8, 2))
        ttk.Entry(corpo, textvariable=vsenha, width=40, show="•").grid(row=13, column=0, sticky="w")
        lbl_sess = tk.Label(corpo, font=F_PEQ, fg=COR["mudo"], bg=COR["card"])
        lbl_sess.grid(row=14, column=0, sticky="w", pady=(12, 2))

        def atualizar_sessoes():
            ss = self.web.listar_sessoes() if hasattr(self.web, "listar_sessoes") else []
            lbl_sess.configure(text=f"Sessões abertas no painel web: {len(ss)}" +
                               ("  —  " + ", ".join(sorted({x['ip'] for x in ss})) if ss else ""))

        def derrubar_todas():
            if not messagebox.askyesno(APP_NOME, "Derrubar todas as sessões do painel web?\n"
                                       "Quem estiver conectado vai precisar digitar a senha de novo.", parent=d):
                return
            n = self.web.derrubar(None)
            atualizar_sessoes()
            self.status.set(f"👥 {n} sessão(ões) do painel web derrubada(s).")
        Botao(corpo, "Derrubar todas as sessões web", derrubar_todas, "perigo", padx=10, pady=4).grid(
            row=15, column=0, sticky="w")
        atualizar_sessoes()

        def ok():
            if MARCADOR_PERFIL not in vp.get():
                messagebox.showerror(APP_NOME, f"O caminho dos perfis deve conter '{MARCADOR_PERFIL}'.", parent=d)
                return
            try:
                self.cfg["atraso_s"] = float(va.get().replace(",", "."))
            except ValueError:
                self.cfg["atraso_s"] = 1.5
            try:
                porta = int(vporta.get())
                assert 1 <= porta <= 65535
            except Exception:
                messagebox.showerror(APP_NOME, "Porta inválida.", parent=d)
                return
            if vsenha.get() and len(vsenha.get()) < 6:
                messagebox.showerror(APP_NOME, "A senha precisa ter pelo menos 6 caracteres.", parent=d)
                return
            self.cfg["chrome_path"] = vc.get().strip()
            self.cfg["perfis_dir"] = vp.get().strip()
            w["ativo"], w["porta"] = vw.get(), porta
            if vsenha.get():
                definir_senha_web(self.cfg, vsenha.get())
                self.web.sessoes.clear()          # derruba quem estava logado com a senha antiga
            self.salvar()
            self.iniciar_web()
            d.destroy()

        rod = tk.Frame(d, bg=COR["card"], padx=16, pady=12)
        rod.pack(fill="x")
        Botao(rod, "Salvar", ok, "primario", padx=18).pack(side="right")
        Botao(rod, "Cancelar", d.destroy, "fantasma", padx=14).pack(side="right", padx=8)


# --------------------------------------------------------------------------- main
def ja_esta_rodando():
    """Instância única: se já houver uma aberta (ex.: iniciada com o Windows), traz ela para frente."""
    try:
        k32 = ctypes.windll.kernel32
        k32.CreateMutexW.restype = wintypes.HANDLE
        global _MUTEX
        _MUTEX = k32.CreateMutexW(None, False, "Local\\dashmgrMaykCloud")
        if k32.GetLastError() != 183:       # ERROR_ALREADY_EXISTS
            return False
        user32.FindWindowW.restype = wintypes.HWND
        hwnd = user32.FindWindowW(None, APP_NOME)
        if hwnd:
            user32.ShowWindow(hwnd, 9)      # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def main():
    if "--versao" in sys.argv:
        print(APP_VERSAO)
        return
    if "--fechar" in sys.argv:
        fechar_paineis(carregar_config(listar_monitores()))
        return
    if ja_esta_rodando():
        return
    if "--auto" in sys.argv:
        for a in sys.argv:
            if a.startswith("--espera="):
                try:
                    time.sleep(max(0, min(600, int(a.split("=", 1)[1]))))
                except ValueError:
                    pass
        mons = listar_monitores()
        cfg = carregar_config(mons)
        abrir_todos(cfg, mons, log=lambda m: None)
        if not cfg_web(cfg).get("ativo"):
            return
        App(minimizado=True).mainloop()      # continua rodando para o acesso remoto
        return
    App(minimizado="--web" in sys.argv).mainloop()


if __name__ == "__main__":
    main()
