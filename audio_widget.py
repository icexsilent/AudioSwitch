"""
AudioSwitch BT — Widget de Barra de Tarefas para alternar Saída de Som do PC e do Discord em sincronia.
Visual inspirado no BateriaBT (EnricoSpanier/BateriaBT).

Configuração salva em: %APPDATA%\\AudioSwitchBT\\config.json
Executar sem console: pythonw audio_widget.py
"""

import ctypes
from ctypes import wintypes
import faulthandler
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import winreg

from PySide6.QtCore import (
    QAbstractAnimation,
    QEvent,
    QLockFile,
    QObject,
    QPoint,
    QPointF,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QButtonGroup,
    QColorDialog,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

import audio_backend as AB
import graphics as G

APP = "AudioSwitchBT"
APP_TITLE = "AudioSwitch BT"
VERSION = "1.0.0"
CONFIG_DIR = Path(os.environ["APPDATA"]) / APP
CONFIG_FILE = CONFIG_DIR / "config.json"
BATERIABT_CONFIG = Path(os.environ["APPDATA"]) / "BateriaBT" / "config.json"
STARTUP_LNK = Path(os.environ["APPDATA"]) / r"Microsoft\Windows\Start Menu\Programs\Startup" / f"{APP}.lnk"
PERSONALIZE = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
ICON_FONT = "Segoe Fluent Icons"

DEFAULTS = {
    "hidden": [],                   # IDs ocultos da pílula da barra de tarefas
    "order": [],                    # Ordem personalizada dos IDs na pílula
    "names": {},                    # id -> nome curto personalizado (ex: "Cloud III", "KZ EDX")
    "known": {},                    # id -> nome original completo do Windows
    "kinds": {},                    # id -> tipo de ícone ("headset", "inear", "wireless", "speaker", "monitor")
    "device_colors": {},            # id -> cor de destaque individual opcional (#HEX)
    "initialized_defaults": False,  # Na 1ª execução, oculta monitores/steam para focar nos fones principais
    "sync_discord": True,           # Sincroniza Padrão + Comunicação + Processo Discord.exe
    "rpc_client_id": "",            # Opcional: Client ID do app Discord RPC (para trocar dropdown interno do Discord)
    "rpc_client_secret": "",        # Opcional: Client Secret do app Discord RPC
    "rpc_access_token": "",         # Token OAuth2 salvo após autorizar no Discord
    "keep_mic_fixed": True,         # Mantém o microfone atual (ex: HyperX SoloCast) fixo ao trocar de fone
    "fixed_mic_id": None,           # Se definido e keep_mic_fixed=True, garante que este mic continue padrão
    "wheel_volume": True,           # Roda do mouse sobre a pílula ajusta o volume do fone
    "hotkey_enabled": True,         # Atalho global Ctrl+Alt+S para alternar fone mesmo em jogo tela cheia
    "click_mode": "smart",          # "smart" (clicar no fone ativa ele; clicar no ativo alterna) | "toggle" | "panel"
    "highlight_target": "active",   # "active" (saída ativa), "both" (ambas acesas), ou o ID de uma saída específica
    "highlight_style": "bateriabt", # "bateriabt" (ícone + barra verde), "capsule" (fundo preenchido), "dot" (ponto), "neon_line"
    "highlight_color": "#10B981",   # Verde esmeralda idêntico ao BateriaBT
    "inactive_opacity": 48,         # Opacidade (20..100%) dos itens não destacados na pílula
    "display_mode": "full",         # "full" (ícone + barra/bateria + nome), "name" (ícone + nome), "pill_only" (ícone + barra/ % estilo BateriaBT), "icon_only"
    "show_hyperx_battery": True,    # Mostra a % real de bateria do HyperX Cloud III Wireless quando ligado
    "theme": "auto",                # auto / escuro / claro / dark_cyber / green / cyan / purple / oled...
    "widget_style": "standard",     # standard / capsules / frameless / neon
    "icon_style": "outline",        # outline / filled / minimal
    "widget_opacity": 95,
    "icon_size": "auto",
    "offset": None,                 # Distância (px) da borda direita da barra até o widget
    "widget_visible": True,
    "notify_on_switch": False,      # Balão de notificação ao alternar (opcional)
}

WIN_DARK = dict(bg="#1A1A1F", surface="#24242B", border="#34343D", text="#FFFFFF", sub="#A7A7B0")
WIN_LIGHT = dict(bg="#F3F3F6", surface="#FFFFFF", border="#E1E1E6", text="#1B1B1F", sub="#5C5C66")
THEMES = {
    "dark_cyber": ("Dark Cyber", True, "#10B981", "#14141B", "#1D1D27", "#2D2D3B", "#F4F4F5", "#A1A1AA", True),
    "bateriabt_dark": ("BateriaBT Original", True, "#10B981", "#1A1A1F", "#24242B", "#34343D", "#FFFFFF", "#8E8E98", False),
    "green": ("Verde Esmeralda", True, "#34D399", "#0A1812", "#11241B", "#1D392B", "#ECFDF5", "#9CC8B4", True),
    "cyan": ("Ciano KZ", True, "#22D3EE", "#0B171C", "#11222A", "#193B47", "#ECFEFF", "#A5F3FC", True),
    "red": ("HyperX Red", True, "#F87171", "#1B0C0F", "#281317", "#402228", "#FEF2F2", "#D6A6AB", True),
    "purple": ("Roxo", True, "#A855F7", "#140E1E", "#1D142B", "#34224C", "#FAF5FF", "#C4B5FD", True),
    "blue": ("Azul", True, "#38BDF8", "#0C1522", "#132034", "#22344F", "#F1F5F9", "#94A3B8", True),
    "oled": ("OLED Preto", True, "#10B981", "#000000", "#0D0D0E", "#27272A", "#FFFFFF", "#A1A1AA", False),
    "day_light": ("Claro", False, "#10B981", "#F6F7FA", "#FFFFFF", "#E2E4EA", "#18181B", "#5B5B66", False),
}
THEME_NAMES = {
    "auto": "Automático ( igual ao BateriaBT )",
    "bateriabt_dark": "Escuro BateriaBT (#1A1A1F)",
    "escuro": "Escuro Windows",
    "claro": "Claro Windows",
    **{k: v[0] for k, v in THEMES.items() if k != "bateriabt_dark"},
}
STYLE_NAMES = {
    "standard": "Padrão (Pílula única)",
    "capsules": "Cápsulas separadas",
    "frameless": "Sem bordas",
    "neon": "Neon (Linha inferior)",
}
HIGHLIGHT_STYLE_NAMES = {
    "bateriabt": "Pílula Verde (BateriaBT)",
    "capsule": "Cápsula Preenchida",
    "dot": "Ponto Luminoso",
    "neon_line": "Barra Neon Inferior",
}
DISPLAY_MODE_NAMES = {
    "full": "Ícone + Pílula + Nome",
    "name": "Ícone + Nome Curto",
    "pill_only": "Ícone + Pílula + %",
    "icon_only": "Compacto (Só Ícones)",
}
CLICK_MODE_NAMES = {
    "smart": "Inteligente (Ativa/Alterna)",
    "toggle": "Alternar Direto",
    "panel": "Abrir Painel ao Clicar",
}
ICON_NAMES = {"outline": "Contorno (BateriaBT)", "filled": "Preenchido", "minimal": "Minimalista"}

PRESET_COLORS = [
    ("Verde BateriaBT", "#10B981"),
    ("Ciano KZ", "#22D3EE"),
    ("Vermelho HyperX", "#EF4444"),
    ("Roxo Discord", "#818CF8"),
    ("Laranja", "#F59E0B"),
    ("Branco Puro", "#FFFFFF"),
]


# ---------- Persistência de Configuração ----------
def load_config() -> dict:
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    return {**DEFAULTS, **{k: v for k, v in cfg.items() if k in DEFAULTS}}


def save_config(cfg: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(cfg, ensure_ascii=False, indent=2)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, CONFIG_FILE)
    except OSError:
        CONFIG_FILE.write_text(text, encoding="utf-8")


def startup_enabled() -> bool:
    return STARTUP_LNK.exists()


def set_startup(on: bool):
    if not on:
        STARTUP_LNK.unlink(missing_ok=True)
        return
    STARTUP_LNK.parent.mkdir(parents=True, exist_ok=True)
    if getattr(sys, "frozen", False):
        target, args, work = sys.executable, "", Path(sys.executable).parent
    else:
        pyw = Path(sys.executable).with_name("pythonw.exe")
        script = Path(__file__).resolve()
        target = str(pyw if pyw.exists() else sys.executable)
        args = f'"{script}"'
        work = script.parent
    ps = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK);"
        "$s.TargetPath = $env:TGT; $s.Arguments = $env:ARGS; $s.WorkingDirectory = $env:WRK; $s.Save()"
    )
    env = {**os.environ, "LNK": str(STARTUP_LNK), "TGT": str(target), "ARGS": args, "WRK": str(work)}
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env, creationflags=0x08000000)


# ---------- Integração com a Barra de Tarefas do Windows (Win32) ----------
user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi

for fn in ("GetWindowLongPtrW", "SetWindowLongPtrW"):
    if not hasattr(user32, fn):
        setattr(user32, fn, getattr(user32, fn.replace("Ptr", "")))
user32.GetWindowLongPtrW.restype = ctypes.c_void_p
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowExW.restype = wintypes.HWND


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def taskbar_rects():
    """
    Retorna (hwnd_taskbar, rect_barra, rect_bandeja) em pixels físicos.
    Se executado de um ambiente sem acesso direto ao HWND do Shell_TrayWnd, usa a geometria da tela primária.
    """
    tb = user32.FindWindowW("Shell_TrayWnd", None)
    if tb:
        r, n = RECT(), RECT()
        user32.GetWindowRect(tb, ctypes.byref(r))
        if r.right > r.left and r.bottom > r.top:
            notify = user32.FindWindowExW(tb, None, "TrayNotifyWnd", None)
            if notify:
                user32.GetWindowRect(notify, ctypes.byref(n))
            else:
                n = r
            return tb, r, n

    # Fallback usando QGuiApplication.primaryScreen()
    scr = QGuiApplication.primaryScreen()
    if not scr:
        return None
    dpr = scr.devicePixelRatio()
    full = scr.geometry()
    avail = scr.availableGeometry()
    bh = full.bottom() - avail.bottom()
    if bh < 24:
        bh = 48
    r = RECT(
        int(full.left() * dpr),
        int((full.bottom() - bh + 1) * dpr),
        int((full.left() + full.width()) * dpr),
        int((full.top() + full.height()) * dpr),
    )
    n = RECT(r.right - int(220 * dpr), r.top, r.right, r.bottom)
    return 0, r, n


def default_offset_beside_bateriabt(bar, notify, dpr: float) -> int:
    """
    Calcula a posição inicial na barra de tarefas:
    Se o usuário já tem o BateriaBT rodando, posiciona automaticamente à esquerda do BateriaBT
    para que os dois widgets fiquem lado a lado em harmonia!
    """
    try:
        if BATERIABT_CONFIG.exists():
            bt_cfg = json.loads(BATERIABT_CONFIG.read_text(encoding="utf-8"))
            bt_off = bt_cfg.get("offset")
            if isinstance(bt_off, (int, float)) and bt_off > 0:
                # BateriaBT com 2 dispositivos tem ~165px de largura; deixamos 8px de margem
                return int(bt_off + 172)
    except Exception:
        pass
    return int((bar.right - notify.left) / dpr + 168)


def _reg(path: str, name: str, default):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return default


def bar_is_dark(theme: str) -> bool:
    if theme in ("escuro", "bateriabt_dark"):
        return True
    if theme == "claro":
        return False
    return not _reg(PERSONALIZE, "SystemUsesLightTheme", 0)


def palette(theme: str, custom_accent: str | None = None) -> dict:
    if theme in THEMES:
        _, dark, acc_hex, bg, surface, border, text, sub, glow = THEMES[theme]
        base = dict(bg=bg, surface=surface, border=border, text=text, sub=sub, glow=glow)
        acc = QColor(custom_accent or acc_hex)
    else:
        dark = True if theme in ("escuro", "bateriabt_dark") else (False if theme == "claro" else not _reg(PERSONALIZE, "AppsUseLightTheme", 0))
        base = {**(WIN_DARK if dark else WIN_LIGHT), "glow": False}
        acc = QColor(custom_accent or "#10B981")
    on = "#000000" if acc.lightnessF() > 0.60 else "#FFFFFF"
    return {**base, "accent": acc.name(), "on_accent": on, "dark": dark}


def taskbar_visible(bar) -> bool:
    cy = user32.GetSystemMetrics(1)
    if cy <= 0:
        return True
    return bar.top < cy - 6


def fullscreen_app(tb) -> bool:
    if not tb:
        return False
    mi = (ctypes.c_long * 10)()
    mi[0] = ctypes.sizeof(mi)
    user32.GetMonitorInfoW(user32.MonitorFromWindow(tb, 2), mi)
    mon, own, r, cloaked = tuple(mi[1:5]), os.getpid(), RECT(), ctypes.c_int()
    pid = ctypes.c_ulong()
    h = user32.GetTopWindow(None)
    while h and h != tb:
        user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if user32.IsWindowVisible(h) and not user32.IsIconic(h) and pid.value != own:
            dwmapi.DwmGetWindowAttribute(h, 14, ctypes.byref(cloaked), 4)
            user32.GetWindowRect(h, ctypes.byref(r))
            if not cloaked.value and (r.left, r.top) <= mon[:2] and r.right >= mon[2] and r.bottom >= mon[3]:
                return True
        h = user32.GetWindow(h, 2)
    return False


# ---------- Métricas da Pílula (Mesmas proporções do BateriaBT) ----------
def metrics(pill_h: int, icon_size="auto") -> dict:
    h = max(16, min(64, pill_h))
    small = h <= 20
    if icon_size != "auto":
        icon = max(10, min(int(icon_size), max(10, h - 4 if h > 18 else h - 2)))
        r = icon / 16
    else:
        r = h / 32
        icon = max(12 if h >= 18 else 11, round(16 * r))
    bh = max(7 if small else 8, round(11 * r))
    m = dict(
        h=h,
        r=r,
        icon=icon,
        batt_h=bh,
        batt_w=round(2 * bh),
        pad=max(3, round(4 * r)) if small else max(5, round(6 * r)),
        sep=max(4, round(6 * r)) if small else max(6, round(8 * r)),
        frame_pad=max(1, round(2 * r)) if small else max(2, round(3 * r)),
        glow=1 if small else 3,
    )
    m["radius"] = min(9 * r, (h + 2 * m["frame_pad"]) / 2 - 1.5)
    f = QFont("Segoe UI")
    f.setPixelSize(max(10 if small else 11, round(12 * r)))
    f.setWeight(QFont.DemiBold)
    m["font"], m["fm"] = f, QFontMetrics(f)
    return m


# ---------- Tooltip Flutuante ----------
class HoverPopup(QLabel):
    """Mostra detalhes da saída, sincronização com Discord, volume e bateria ao passar o mouse."""

    def __init__(self, app):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.app = app
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setTextFormat(Qt.RichText)

    def show_for(self, row: dict, anchor: QPoint, extra_msg: str | None = None):
        pal = palette(self.app.cfg["theme"], self.app.cfg["highlight_color"])
        self.setStyleSheet(
            f"QLabel{{background:{pal['bg']};color:{pal['text']};border:1px solid {pal['border']};"
            f"border-radius:8px;padding:8px 12px;font:9pt 'Segoe UI'}}"
        )
        status_parts = []
        if row["active"] and row["comm_active"]:
            status_parts.append(f"<span style='color:{pal['accent']};font-weight:700'>● Ativo (PC + Discord)</span>")
        elif row["active"]:
            status_parts.append(f"<span style='color:{pal['accent']};font-weight:700'>● Ativo (PC)</span>")
        else:
            status_parts.append("Clique para ativar no PC + Discord")

        if row.get("volume") is not None:
            vol_txt = "Mudo" if row.get("muted") else f"Vol: {row['volume']}%"
            status_parts.append(vol_txt)

        if row.get("battery") is not None:
            chg = " ⚡" if row.get("charging") else ""
            status_parts.append(f"Bateria: {row['battery']}%{chg}")

        if extra_msg:
            status_parts = [f"<span style='color:{pal['accent']};font-weight:700'>{extra_msg}</span>"]

        sub_html = " · ".join(status_parts)
        self.setText(
            f"<b>{row['name']}</b> <span style='color:{pal['sub']};font-size:8pt'>({row['full_name']})</span><br>"
            f"<span style='color:{pal['sub']}'>{sub_html}</span>"
        )
        self.adjustSize()
        x = max(8, anchor.x() - self.width() // 2)
        y = max(8, anchor.y() - self.height() - 6)
        self.move(x, y)
        self.show()


# ---------- Widget na Barra de Tarefas ----------
class TaskbarWidget(QWidget):
    """Pílula na barra de tarefas com o mesmo visual do BateriaBT."""

    def __init__(self, app):
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus,
        )
        self.app = app
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.rows = []
        self.pills = []
        self.m = None
        self.frame = QRectF()
        self.popup = HoverPopup(app)
        self._press = None
        self._drag = None
        self._owned = False
        self._want = True
        self._bar_h = 48
        self._hover_idx = None
        self._switch_flash = {}  # did -> float 0..1

        self.keep = QTimer(self, interval=2000, timeout=self.place)
        self.keep.start()
        self.follow = QTimer(self, interval=200, timeout=self.sync_shown)
        self.follow.start()

    def sync_shown(self):
        rects = taskbar_rects()
        shown = (
            self._want
            and rects is not None
            and taskbar_visible(rects[1])
            and not fullscreen_app(rects[0])
        )
        if shown != self.isVisible():
            self.setVisible(shown)
            if shown:
                self.place()
            else:
                self.popup.hide()

    def flash_device(self, did: str):
        anim = QVariantAnimation(self, startValue=1.0, endValue=0.0, duration=450)
        anim.valueChanged.connect(lambda v, d=did: (self._switch_flash.__setitem__(d, float(v)), self.update()))
        anim.finished.connect(lambda d=did: (self._switch_flash.pop(d, None), self.update()))
        anim.start(QAbstractAnimation.DeleteWhenStopped)

    def _pill_label(self, row: dict, mode: str) -> str:
        if mode == "icon_only":
            return ""
        if mode == "pill_only":
            if row.get("battery") is not None and self.app.cfg["show_hyperx_battery"]:
                return f"{row['battery']}%"
            return row["name"]
        if mode == "full":
            if row.get("battery") is not None and self.app.cfg["show_hyperx_battery"]:
                return f"{row['name']} {row['battery']}%"
            return row["name"]
        return row["name"]

    def _has_battery_pill(self, row: dict, mode: str) -> bool:
        """Desenha a pilhazinha estilo BateriaBT na saída se 'bateriabt' ou se tiver bateria HyperX."""
        if mode in ("full", "pill_only") and self.app.cfg["highlight_style"] == "bateriabt":
            return True
        if row.get("battery") is not None and self.app.cfg["show_hyperx_battery"] and mode != "name":
            return True
        return False

    def _pill_w(self, row: dict, m: dict) -> int:
        mode = self.app.cfg["display_mode"]
        hs = self.app.cfg["highlight_style"]
        gap = max(4, int(0.18 * m["h"]))
        w = m["pad"] * 2 + m["icon"]

        if hs == "dot":
            w += gap + 6

        if self._has_battery_pill(row, mode):
            w += gap + m["batt_w"]

        lbl = self._pill_label(row, mode)
        if lbl:
            w += gap + m["fm"].horizontalAdvance(lbl)

        return w

    def set_rows(self, rows: list[dict]):
        self.rows = rows
        self.relayout()
        self._want = bool(rows) and self.app.cfg["widget_visible"]
        self.sync_shown()
        self.place()
        self.update()

    def relayout(self):
        cfg, n = self.app.cfg, len(self.rows)
        H = self._bar_h
        m0 = metrics(32)
        pill_h = max(18, H - 2 * (m0["glow"] + m0["frame_pad"]) - 2)
        m = self.m = metrics(pill_h, cfg["icon_size"])

        widths = [self._pill_w(r, m) for r in self.rows]
        left = m["glow"] + m["frame_pad"]
        top = (H - m["h"]) / 2
        self.pills = []
        x = left
        for w in widths:
            self.pills.append(QRectF(x, top, w, m["h"]))
            x += w + m["sep"]

        total_w = 2 * left + sum(widths) + m["sep"] * max(0, n - 1)
        self.frame = QRectF(
            m["glow"] + 0.5,
            top - m["frame_pad"] + 0.5,
            max(10, total_w - 2 * m["glow"] - 1),
            m["h"] + 2 * m["frame_pad"] - 1,
        )
        self.setFixedWidth(max(24, round(total_w)))

    def is_row_highlighted(self, row: dict) -> bool:
        target = self.app.cfg["highlight_target"]
        if target == "active":
            return bool(row["active"])
        if target == "both":
            return True
        return row["id"] == target

    def row_highlight_color(self, row: dict) -> QColor:
        custom = self.app.cfg["device_colors"].get(row["id"])
        if custom:
            return QColor(custom)
        return QColor(self.app.cfg["highlight_color"])

    def paintEvent(self, _):
        if not self.m or not self.rows:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cfg, m = self.app.cfg, self.m
        st = cfg["widget_style"]
        pal = palette(cfg["theme"], cfg["highlight_color"])
        op = cfg["widget_opacity"]
        acc = QColor(pal["accent"])

        # Fundo invisível mínimo para capturar eventos do mouse em toda a área
        p.fillRect(self.rect(), QColor(0, 0, 0, 1))

        if st in ("standard", "neon"):
            fr, rad = self.frame, m["radius"]
            if st == "standard" and pal.get("glow"):
                for i, alpha in ((3, 22), (2, 38), (1, 60)):
                    c = QColor(acc)
                    c.setAlpha(alpha)
                    p.setPen(QPen(c, 1.2))
                    p.setBrush(Qt.NoBrush)
                    p.drawRoundedRect(fr.adjusted(-i, -i, i, i), rad + i, rad + i)

            bg = QColor(pal["bg"])
            bg.setAlpha(int(255 * op / 100))
            if st == "standard":
                border = QColor(acc if pal.get("glow") else pal["border"])
                border.setAlpha(185 if pal.get("glow") else 160)
                p.setPen(QPen(border, 1.1))
            else:
                p.setPen(QPen(QColor(pal["border"]), 1.0))
            p.setBrush(bg)
            p.drawRoundedRect(fr, rad, rad)

            if st == "neon":
                p.setPen(QPen(acc, 1.8))
                p.drawLine(QPointF(fr.left() + rad, fr.bottom()), QPointF(fr.right() - rad, fr.bottom()))
            else:
                self._draw_separators(p, pal)

        for idx, (rect, row) in enumerate(zip(self.pills, self.rows)):
            self._paint_pill(p, idx, rect, row, pal, st, op)

        p.end()

    def _draw_separators(self, p: QPainter, pal: dict):
        c = QColor(pal["sub"])
        c.setAlpha(65)
        p.setPen(QPen(c, 1))
        inset = max(3.0, 0.16 * self.m["h"])
        for a, b in zip(self.pills, self.pills[1:]):
            x = round((a.right() + b.left()) / 2) + 0.5
            p.drawLine(QPointF(x, a.top() + inset), QPointF(x, a.bottom() - inset))

    def _paint_pill(self, p: QPainter, idx: int, rect: QRectF, row: dict, pal: dict, st: str, op: int):
        cfg, m = self.app.cfg, self.m
        mode = cfg["display_mode"]
        hs = cfg["highlight_style"]
        highlighted = self.is_row_highlighted(row)
        is_active = bool(row["active"])
        hovered = idx == self._hover_idx
        h_col = self.row_highlight_color(row)
        flash = self._switch_flash.get(row["id"], 0.0)

        p.save()

        # Opacidade do item (destacado = 100%, inativo = configurável, hover = realça)
        base_opacity = 1.0 if highlighted else (max(0.25, cfg["inactive_opacity"] / 100.0))
        if hovered and not highlighted:
            base_opacity = min(1.0, base_opacity + 0.25)
        p.setOpacity(base_opacity)

        # Cápsulas separadas ou destaque tipo cápsula
        if st == "capsules":
            surf = QColor(pal["surface"])
            surf.setAlpha(int(240 * op / 100))
            pen_c = QColor(h_col if highlighted else pal["border"])
            pen_c.setAlpha(200 if highlighted else 120)
            p.setPen(QPen(pen_c, 1.2 if highlighted else 1.0))
            p.setBrush(surf)
            p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), m["radius"], m["radius"])
        elif hs == "capsule" and highlighted:
            cap_bg = QColor(h_col)
            cap_bg.setAlpha(42 if not hovered else 58)
            cap_border = QColor(h_col)
            cap_border.setAlpha(175)
            p.setPen(QPen(cap_border, 1.1))
            p.setBrush(cap_bg)
            p.drawRoundedRect(rect.adjusted(1.0, 1.5, -1.0, -1.5), m["radius"] - 1.5, m["radius"] - 1.5)
        elif hovered:
            hov_bg = QColor(pal["surface"])
            hov_bg.setAlpha(90)
            p.setPen(Qt.NoPen)
            p.setBrush(hov_bg)
            p.drawRoundedRect(rect.adjusted(1.0, 1.5, -1.0, -1.5), m["radius"] - 1.5, m["radius"] - 1.5)

        if hs == "neon_line" and highlighted:
            p.setPen(QPen(h_col, 2.2))
            p.drawLine(
                QPointF(rect.left() + 6, rect.bottom() - 1.2),
                QPointF(rect.right() - 6, rect.bottom() - 1.2),
            )

        if flash > 0:
            ring = QColor(h_col)
            ring.setAlphaF(flash * 0.85)
            p.setPen(QPen(ring, 2.0))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rect.adjusted(1.0, 1.0, -1.0, -1.0), m["radius"] - 1, m["radius"] - 1)

        h = m["h"]
        cy = rect.center().y()
        gap = max(4.0, 0.18 * h)
        x = rect.x() + m["pad"]
        icon_s = m["icon"]

        # 1. Ícone do Fone / Saída
        # No BateriaBT original, o ícone do dispositivo fica discreto (pal["sub"]) ou na cor de destaque
        if hs == "bateriabt":
            icon_color = QColor(h_col if (highlighted and not self._has_battery_pill(row, mode)) else pal["sub"])
            if highlighted:
                icon_color = QColor(pal["sub"])
                icon_color.setAlpha(200)
        else:
            icon_color = QColor(h_col if highlighted else pal["sub"])

        irect = QRectF(x, cy - icon_s / 2, icon_s, icon_s)
        G.draw_device_icon(p, irect, row["kind"], icon_color, style=cfg["icon_style"])
        x += icon_s + gap

        # 2. Ponto luminoso se highlight_style == "dot"
        if hs == "dot":
            dot_c = QColor(h_col if highlighted else pal["sub"])
            if not highlighted:
                dot_c.setAlpha(80)
            p.setPen(Qt.NoPen)
            p.setBrush(dot_c)
            p.drawEllipse(QPointF(x + 3, cy), 3.0 if highlighted else 2.2, 3.0 if highlighted else 2.2)
            x += 6 + gap

        # 3. Pilha / Barra Verde estilo BateriaBT
        if self._has_battery_pill(row, mode):
            bw, bh = m["batt_w"], m["batt_h"]
            if row.get("battery") is not None and cfg["show_hyperx_battery"]:
                lvl = row["battery"]
            else:
                # Quando é um fone com fio (ou sem leitura HID), a pilha funciona como indicador visual:
                # Cheia (100%) e verde quando a saída está em destaque/ativa, ou vazia (0%) quando inativa!
                lvl = 100 if highlighted else 0
            fill_c = h_col if highlighted else QColor(pal["sub"])
            outline_c = QColor(pal["text"] if highlighted else pal["sub"])
            outline_c.setAlpha(210 if highlighted else 130)
            G.draw_battery(
                p,
                QRectF(x, cy - bh / 2, bw, bh),
                lvl,
                fill_c,
                outline_c,
                None,
                charging=bool(row.get("charging")),
                bolt_fill=pal["text"],
                bolt_outline=pal["bg"],
            )
            x += bw + gap

        # 4. Texto (Nome curto e/ou %)
        lbl = self._pill_label(row, mode)
        if lbl:
            p.setFont(m["font"])
            txt_c = QColor(pal["text"] if (highlighted or is_active) else pal["sub"])
            p.setPen(txt_c)
            p.drawText(
                QRectF(x, rect.top(), rect.right() - x + 2, h),
                Qt.AlignVCenter | Qt.AlignLeft,
                lbl,
            )

        p.restore()

    def place(self):
        rects = taskbar_rects()
        if not rects or not self.isVisible():
            return
        tb, bar, notify = rects
        hwnd = int(self.winId())
        if tb and (not self._owned or user32.GetWindowLongPtrW(hwnd, -8) != tb):
            user32.SetWindowLongPtrW(hwnd, -8, tb)
            ex = user32.GetWindowLongW(hwnd, -20)
            user32.SetWindowLongW(hwnd, -20, ex | 0x08000000)  # WS_EX_NOACTIVATE
            self._owned = True
        elif not tb and not self._owned:
            ex = user32.GetWindowLongW(hwnd, -20)
            user32.SetWindowLongW(hwnd, -20, ex | 0x08000000)
            self._owned = True

        dpr = self.devicePixelRatioF()
        H = max(28, round((bar.bottom - bar.top) / dpr))
        self.setFixedHeight(H)
        if H != self._bar_h:
            self._bar_h = H
            self.relayout()

        right = bar.right / dpr
        offset = self.app.cfg["offset"]
        if offset is None:
            offset = default_offset_beside_bateriabt(bar, notify, dpr)
        x = right - offset - self.width()
        x = max(bar.left / dpr, min(x, right - self.width()))
        if self._press is None:
            self.move(round(x), round(bar.top / dpr))
        user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)

    def _pill_index_at(self, px: float, py: float) -> int | None:
        return next(
            (
                i
                for i, r in enumerate(self.pills)
                if r.left() - 4 <= px <= r.right() + 4 and r.top() - 2 <= py <= r.bottom() + 2
            ),
            None,
        )

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = e.globalPosition().x()
            self._drag = self._press - self.x()
            self.popup.hide()
        elif e.button() == Qt.MiddleButton:
            self.popup.hide()
            self.app.panel.toggle()

    def mouseMoveEvent(self, e):
        gx = e.globalPosition().x()
        if self._press is not None:
            if abs(gx - self._press) > 4:
                self.move(round(gx - self._drag), self.y())
            return
        i = self._pill_index_at(e.position().x(), e.position().y())
        if i != self._hover_idx:
            self._hover_idx = i
            self.update()
        if i is None or i >= len(self.rows):
            self.popup.hide()
        else:
            anchor = self.mapToGlobal(QPoint(round(self.pills[i].center().x()), 0))
            self.popup.show_for(self.rows[i], anchor)

    def mouseReleaseEvent(self, e):
        if self._press is None or e.button() != Qt.LeftButton:
            return
        moved = abs(e.globalPosition().x() - self._press) > 4
        self._press = None
        if moved:
            rects = taskbar_rects()
            if rects:
                right = rects[1].right / self.devicePixelRatioF()
                self.app.set("offset", max(0, round(right - self.x() - self.width())))
            return

        # Clique simples sem arrastar
        mode = self.app.cfg["click_mode"]
        if mode == "panel":
            self.app.panel.toggle()
            return
        if mode == "toggle":
            self.app.cycle_output()
            return

        # Modo "smart":
        # - Se clicou em um fone inativo, muda diretamente para ele.
        # - Se clicou no fone que JÁ está ativo (ou entre as pílulas), alterna para o próximo fone da pílula!
        i = self._pill_index_at(e.position().x(), e.position().y())
        if i is not None and i < len(self.rows):
            clicked = self.rows[i]
            if not clicked["active"]:
                self.app.activate_output(clicked["id"])
            else:
                self.app.cycle_output()
        else:
            self.app.cycle_output()

    def wheelEvent(self, e):
        if not self.app.cfg["wheel_volume"] or not self.rows:
            return
        i = self._pill_index_at(e.position().x(), e.position().y())
        target = self.rows[i] if (i is not None and i < len(self.rows)) else next((r for r in self.rows if r["active"]), self.rows[0])
        delta = e.angleDelta().y()
        if delta == 0:
            return
        step = 2 if delta > 0 else -2
        cur = target.get("volume") if target.get("volume") is not None else 50
        new_vol = max(0, min(100, cur + step))
        if AB.set_device_volume(target["id"], new_vol):
            target["volume"] = new_vol
            idx = self.rows.index(target)
            anchor = self.mapToGlobal(QPoint(round(self.pills[idx].center().x()), 0))
            self.popup.show_for(target, anchor, extra_msg=f"Volume: {new_vol}%")

    def leaveEvent(self, _):
        self._hover_idx = None
        self.popup.hide()
        self.update()

    def contextMenuEvent(self, e):
        self.popup.hide()
        self.app.show_context_menu(e.globalPos())


# ---------- Estilos do Painel Flyout (Mesmo Design do BateriaBT) ----------
def stylesheet(c: dict) -> str:
    return f"""
    #FlyoutRoot QLabel {{ color: {c['text']}; background: transparent; }}
    QLabel[role="title"] {{ font-size: 15px; font-weight: 700; }}
    QLabel[role="subtitle"] {{ font-size: 12px; color: {c['sub']}; }}
    QLabel[role="section"] {{ font-size: 12px; font-weight: 700; color: {c['sub']}; padding: 4px 2px 0 2px; }}
    QLabel[role="rowtitle"] {{ font-size: 13px; }}
    QLabel[role="rowsub"] {{ font-size: 11px; color: {c['sub']}; }}
    QLabel[role="value"] {{ font-size: 12px; font-weight: 700; color: {c['sub']}; }}
    QScrollArea, QStackedWidget, #Page {{ background: transparent; border: none; }}
    QFrame#Group {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 10px; }}
    QFrame[role="divider"] {{ background: {c['border']}; border: none; }}
    QFrame#Tabs {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 9px; }}
    QPushButton[kind="tab"] {{ background: transparent; border: none; border-radius: 7px; padding: 6px;
                               color: {c['sub']}; font-size: 12px; font-weight: 600; }}
    QPushButton[kind="tab"]:hover {{ color: {c['text']}; }}
    QPushButton[kind="tab"]:checked {{ background: {c['accent']}; color: {c['on_accent']}; }}
    QPushButton[kind="icon"] {{ background: transparent; border: none; border-radius: 8px; color: {c['sub']};
                                font-family: "{ICON_FONT}"; font-size: 14px; min-width: 30px; min-height: 30px; }}
    QPushButton[kind="icon"]:hover {{ background: {c['border']}; color: {c['text']}; }}
    QPushButton[kind="secondary"] {{ background: {c['bg']}; color: {c['text']}; border: 1px solid {c['border']};
                                     border-radius: 8px; padding: 6px 12px; font-size: 12px; font-weight: 600; }}
    QPushButton[kind="secondary"]:hover {{ border-color: {c['accent']}; }}
    QPushButton[kind="primary"] {{ background: {c['accent']}; color: {c['on_accent']}; border: none;
                                   border-radius: 8px; padding: 6px 12px; font-size: 12px; font-weight: 700; }}
    QPushButton[kind="chip"] {{ background: {c['bg']}; color: {c['text']}; border: 1px solid {c['border']};
                                border-radius: 10px; padding: 3px 10px; font-size: 11px; font-weight: 600; min-height: 18px; }}
    QPushButton[kind="chip"]:hover {{ border-color: {c['accent']}; }}
    QPushButton[kind="chip"]:checked {{ background: {c['accent']}; color: {c['on_accent']}; border-color: {c['accent']}; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px 0 2px 2px; }}
    QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 3px; min-height: 36px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
    QSlider {{ min-height: 20px; }}
    QSlider::groove:horizontal {{ height: 4px; background: {c['border']}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: {c['bg']}; border: 3px solid {c['accent']}; width: 10px; height: 10px;
                                  margin: -6px 0; border-radius: 8px; }}
    QSpinBox, QLineEdit {{ background: {c['bg']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 6px;
                           padding: 3px 8px; font-size: 12px; min-height: 24px; }}
    QLineEdit:hover, QLineEdit:focus {{ border-color: {c['accent']}; }}
    QComboBox {{ background: {c['bg']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 8px;
                 padding: 4px 10px; font-size: 12px; min-height: 22px; min-width: 135px; }}
    QComboBox:hover, QComboBox:on {{ border-color: {c['accent']}; }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox QAbstractItemView {{ background: {c['bg']}; color: {c['text']}; border: 1px solid {c['border']};
                                   padding: 4px; outline: none; selection-background-color: {c['accent']};
                                   selection-color: {c['on_accent']}; }}
    """


def menu_stylesheet(c: dict) -> str:
    return f"""
    QMenu {{ background: {c['bg']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 8px;
             padding: 5px; font-size: 12px; font-family: 'Segoe UI'; }}
    QMenu::item {{ padding: 7px 24px 7px 14px; border-radius: 5px; }}
    QMenu::item:selected {{ background: {c['surface']}; color: {c['accent']}; }}
    QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px 8px; }}
    """


def round_menu(menu: QMenu) -> QMenu:
    menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
    menu.setAttribute(Qt.WA_TranslucentBackground)
    return menu


class Toggle(QAbstractButton):
    """Interruptor deslizante arredondado igual ao BateriaBT."""

    def __init__(self, panel, checked: bool, on_change):
        super().__init__()
        self.panel = panel
        self.setCheckable(True)
        self.setChecked(checked)
        self.toggled.connect(on_change)
        self.setFixedSize(40, 22)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, _):
        c = self.panel.pal
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        on = self.isChecked()
        p.setPen(Qt.NoPen if on else QPen(QColor(c["sub"]), 1.2))
        p.setBrush(QColor(c["accent"]) if on else Qt.NoBrush)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - (8 if on else 10)
        x = r.right() - d - 4 if on else r.left() + 5
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(c["on_accent"] if on else c["sub"]))
        p.drawEllipse(QRectF(x, r.center().y() - d / 2, d, d))
        p.end()


class OutputCard(QWidget):
    """
    Cartão interativo de saída de som no Painel:
    - Clicar no cartão ativa essa saída imediatamente (PC + Discord).
    - Botão de engrenagem abre a personalização (nome curto, ícone, cor de destaque).
    - Botão de olho mostra/oculta essa saída da pílula da barra de tarefas.
    """

    def __init__(self, panel, d: dict, clickable: bool = True):
        super().__init__()
        self.panel = panel
        self.d = d
        self.clickable = clickable
        self.setFixedHeight(66)
        self.hidden_in_bar = d["id"] in panel.app.cfg["hidden"]

        self.cfg_btn = QPushButton("", self)  # Ícone de personalizar
        self.cfg_btn.setProperty("kind", "icon")
        self.cfg_btn.setFixedSize(30, 30)
        self.cfg_btn.setCursor(Qt.PointingHandCursor)
        self.cfg_btn.setToolTip("Personalizar nome, ícone e cor de destaque desta saída")
        self.cfg_btn.clicked.connect(lambda: panel.open_detail(d["id"]))

        self.eye = QPushButton("Oculto" if self.hidden_in_bar else "Na barra", self)
        self.eye.setProperty("kind", "chip")
        self.eye.setFixedSize(68, 24)
        self.eye.setCheckable(True)
        self.eye.setChecked(not self.hidden_in_bar)
        self.eye.setCursor(Qt.PointingHandCursor)
        self.eye.setToolTip("Clique para mostrar ou ocultar esta saída na pílula da barra de tarefas")
        self.eye.clicked.connect(lambda: panel.app.toggle_hidden(d["id"]))

        if clickable:
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip("Clique para ativar esta saída no PC e no Discord")
        else:
            self.cfg_btn.hide()
            self.eye.hide()

    def resizeEvent(self, _):
        self.cfg_btn.move(self.width() - 10 - 30, (self.height() - 30) // 2)
        self.eye.move(self.width() - 10 - 30 - 6 - 68, (self.height() - 24) // 2)

    def paintEvent(self, _):
        c, d, app = self.panel.pal, self.d, self.panel.app
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        active = d["active"]
        h_col = app.widget.row_highlight_color(d)
        border_c = QColor(h_col if active else c["border"])
        p.setPen(QPen(border_c, 1.5 if active else 1.0))
        p.setBrush(QColor(c["surface"]))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.8, 0.8, -0.8, -0.8), 10, 10)

        acc = QColor(h_col if active else c["sub"])
        tint = QColor(acc)
        tint.setAlpha(45 if active else 25)
        box = QRectF(12, 14, 38, 38)
        p.setPen(Qt.NoPen)
        p.setBrush(tint)
        p.drawRoundedRect(box, 10, 10)
        G.draw_device_icon(p, box.adjusted(8, 8, -8, -8), d["kind"], acc, style=app.cfg["icon_style"])

        right = self.width() - (118 if self.clickable else 20)
        if d.get("battery") is not None:
            f = QFont("Segoe UI")
            f.setPixelSize(13)
            f.setBold(True)
            txt = f"{d['battery']}%"
            tw = QFontMetrics(f).horizontalAdvance(txt)
            p.setFont(f)
            p.setPen(QColor(c["text"]))
            p.drawText(QRectF(right - tw, 0, tw, self.height()), Qt.AlignVCenter | Qt.AlignRight, txt)
            bw, bh = 22, 11
            G.draw_battery(
                p,
                QRectF(right - tw - 6 - bw, (self.height() - bh) / 2, bw, bh),
                d["battery"],
                h_col,
                c["sub"],
                None,
                charging=bool(d.get("charging")),
            )
            right -= tw + 6 + bw + 10

        f = QFont("Segoe UI")
        f.setPixelSize(13)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor(c["text"] if not self.hidden_in_bar else c["sub"]))
        w = max(60, right - 62)
        title = d["name"]
        p.drawText(
            QRectF(62, 12, w, 20),
            Qt.AlignLeft | Qt.AlignVCenter,
            QFontMetrics(f).elidedText(title, Qt.ElideRight, int(w)),
        )

        # Subtítulo com status de sincronização
        if active and d["comm_active"]:
            status = "● Ativo no PC + Discord"
            sub_col = h_col
        elif active:
            status = "● Ativo no PC"
            sub_col = h_col
        else:
            status = d["full_name"]
            sub_col = QColor(c["sub"])

        if d.get("volume") is not None:
            status += f" · Vol {d['volume']}%"
        if self.hidden_in_bar:
            status += " · oculto da barra"

        f.setPixelSize(11)
        f.setWeight(QFont.DemiBold if active else QFont.Normal)
        p.setFont(f)
        p.setPen(sub_col)
        p.drawText(
            QRectF(62, 34, w, 18),
            Qt.AlignLeft | Qt.AlignVCenter,
            QFontMetrics(f).elidedText(status, Qt.ElideRight, int(w)),
        )
        p.end()

    def mouseReleaseEvent(self, e):
        if self.clickable and e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.panel.app.activate_output(self.d["id"])


# ---------- Painel Flyout (Saídas / Sincronização / Design & Destaque) ----------
class Panel(QWidget):
    W = 388

    def __init__(self, app):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName("FlyoutRoot")
        self.setFixedWidth(self.W)
        self.app = app
        self.tab = 0
        self.detail_did = None
        self._modal = False
        self._hidden_at = 0.0
        self.body = None
        self.pal = palette(app.cfg["theme"], app.cfg["highlight_color"])
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(16, 14, 16, 16)

    def build(self):
        if self.body:
            self.root.removeWidget(self.body)
            self.body.hide()
            self.body.deleteLater()
        self.pal = palette(self.app.cfg["theme"], self.app.cfg["highlight_color"])
        self.setStyleSheet(stylesheet(self.pal))
        self.body = QWidget()
        self.root.addWidget(self.body)
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.addLayout(self._header())
        self.tabs_frame = self._tabs()
        lay.addWidget(self.tabs_frame)
        self.stack = QStackedWidget()
        self.pages = [
            self._scroll(self._outputs_page()),
            self._scroll(self._sync_page()),
            self._scroll(self._design_page()),
        ]
        for pg in self.pages:
            self.stack.addWidget(pg)
        self.stack.setCurrentIndex(self.tab)
        lay.addWidget(self.stack)
        self.body.show()
        self._fit()
        if self.detail_did:
            self.open_detail(self.detail_did)

    def _scroll(self, content: QWidget) -> QScrollArea:
        content.setObjectName("Page")
        content.setFixedWidth(self.W - 32 - 10)
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        s.setWidget(content)
        return s

    def _fit(self):
        h = max(pg.widget().sizeHint().height() for pg in self.pages)
        self.stack.setFixedHeight(min(max(h, 300), 460))
        bottom = self.geometry().bottom()
        self.root.activate()
        self.adjustSize()
        if self.isVisible():
            self.move(self.x(), bottom - self.height() + 1)

    def _header(self):
        h = QHBoxLayout()
        h.setSpacing(10)
        logo = QLabel("")  # Ícone Fluent de Áudio / Alto-falante
        logo.setFixedSize(34, 34)
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet(
            f"background:{self.pal['accent']};color:{self.pal['on_accent']};border-radius:9px;"
            f"font-family:'{ICON_FONT}';font-size:16px"
        )
        v = QVBoxLayout()
        v.setSpacing(0)
        v.addWidget(self._label(APP_TITLE, "title"))
        self.subtitle = self._label(self._subtitle_text(), "subtitle")
        v.addWidget(self.subtitle)
        h.addWidget(logo)
        h.addLayout(v)
        h.addStretch()
        for glyph, tip, fn in (
            ("", "Alternar fone agora (PC + Discord)", self.app.cycle_output),
            ("", "Atualizar dispositivos e bateria", self.app.refresh),
            ("", "Fechar (Esc)", self.hide),
        ):
            h.addWidget(self._icon_button(glyph, tip, fn))
        return h

    def _icon_button(self, glyph: str, tip: str, fn) -> QPushButton:
        b = QPushButton(glyph)
        b.setProperty("kind", "icon")
        b.setToolTip(tip)
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(fn)
        return b

    def _subtitle_text(self) -> str:
        active = next((r for r in self.app.all_rows() if r["active"]), None)
        if not active:
            return "Nenhuma saída ativa"
        sync = "PC + Discord" if self.app.cfg["sync_discord"] else "Apenas PC"
        return f"Ativo: {active['name']} ({sync})"

    def _tabs(self) -> QFrame:
        fr = QFrame()
        fr.setObjectName("Tabs")
        hl = QHBoxLayout(fr)
        hl.setContentsMargins(3, 3, 3, 3)
        hl.setSpacing(3)
        grp = self.tab_group = QButtonGroup(fr)
        for i, t in enumerate(("Saídas de Som", "Sincronização", "Design e Destaque")):
            b = QPushButton(t)
            b.setProperty("kind", "tab")
            b.setCheckable(True)
            b.setChecked(i == self.tab)
            b.setCursor(Qt.PointingHandCursor)
            grp.addButton(b, i)
            hl.addWidget(b)
        grp.idClicked.connect(self._set_tab)
        return fr

    def _set_tab(self, i: int):
        self.tab = i
        self.tab_group.button(i).setChecked(True)
        self.close_detail()

    @staticmethod
    def _label(text: str, role: str, wrap: bool = False) -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty("role", role)
        lbl.setWordWrap(wrap)
        return lbl

    def _page(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 4, 0)
        v.setSpacing(8)
        return w, v

    def _group(self, *rows) -> QFrame:
        fr = QFrame()
        fr.setObjectName("Group")
        v = QVBoxLayout(fr)
        v.setContentsMargins(14, 8, 14, 8)
        v.setSpacing(6)
        for i, r in enumerate(rows):
            if i:
                div = QFrame()
                div.setProperty("role", "divider")
                div.setFixedHeight(1)
                v.addWidget(div)
            v.addWidget(r)
        return fr

    def _row(self, title: str, sub: str | None, control: QWidget | None) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 4, 0, 4)
        h.setSpacing(12)
        t = QVBoxLayout()
        t.setSpacing(2)
        t.addWidget(self._label(title, "rowtitle", True))
        if sub:
            t.addWidget(self._label(sub, "rowsub", True))
        h.addLayout(t, 1)
        if control is not None:
            h.addWidget(control, 0, Qt.AlignVCenter)
        return w

    def _toggle(self, title: str, sub: str | None, checked: bool, fn) -> QWidget:
        return self._row(title, sub, Toggle(self, checked, fn))

    def _combo(self, title: str, sub: str | None, names: dict, key: str) -> QWidget:
        combo = QComboBox()
        combo.setFixedWidth(168)
        for k, label in names.items():
            combo.addItem(label, k)
        combo.setCurrentIndex(max(0, combo.findData(self.app.cfg[key])))
        combo.currentIndexChanged.connect(lambda i: self.app.set(key, combo.itemData(i)))
        return self._row(title, sub, combo)

    def _value_slider(self, title: str, lo: int, hi: int, value: int, unit: str, on_change) -> QWidget:
        w = QWidget()
        sv = QVBoxLayout(w)
        sv.setContentsMargins(0, 4, 0, 4)
        sv.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(self._label(title, "rowtitle"))
        head.addStretch()
        val = self._label(f"{value} {unit}", "value")
        head.addWidget(val)
        sv.addLayout(head)
        s = QSlider(Qt.Horizontal)
        s.setRange(lo, hi)
        s.setValue(value)
        s.valueChanged.connect(lambda n: (val.setText(f"{n} {unit}"), on_change(n)))
        sv.addWidget(s)
        w.slider, w.value = s, val
        return w

    # --- Aba 1: Saídas de Som ---
    def _outputs_page(self) -> QWidget:
        w, v = self._page()
        rows = self.app.all_rows()
        vis = [r for r in rows if r["id"] not in self.app.cfg["hidden"]]
        hid_rows = [r for r in rows if r["id"] in self.app.cfg["hidden"]]

        v.addWidget(self._label("Na pílula da barra de tarefas (clique para ativar)", "section"))
        if not vis:
            v.addWidget(
                self._label(
                    "Nenhuma saída visível na barra. Clique no ícone de olho abaixo para exibir seus fones.",
                    "rowsub",
                    True,
                )
            )
        for r in vis:
            v.addWidget(OutputCard(self, r))

        if hid_rows:
            v.addWidget(self._label("Outras saídas disponíveis (ocultas da barra)", "section"))
            for r in hid_rows:
                v.addWidget(OutputCard(self, r))

        # Informação do Microfone Fixo
        mics = self.app.microphones
        active_mic = next((m for m in mics if m["is_default_console"]), None)
        mic_name = active_mic["full_name"] if active_mic else "Nenhum detectado"
        v.addWidget(self._label("Microfone (Entrada)", "section"))
        v.addWidget(
            self._group(
                self._row(
                    "Microfone atual mantido fixo",
                    f"{mic_name} (não é alterado ao trocar entre Cloud III e KZ EDX Pro)",
                    None,
                )
            )
        )
        v.addStretch()
        return w

    # --- Aba 2: Sincronização & Geral ---
    def _sync_page(self) -> QWidget:
        app, cfg = self.app, self.app.cfg
        w, v = self._page()

        v.addWidget(self._label("Sincronização PC + Discord", "section"))
        disc_status = AB.get_discord_configured_output_status()
        rpc_ok = bool(cfg.get("rpc_client_id") and cfg.get("rpc_access_token"))
        if rpc_ok:
            st_title = "Status do Discord: Conectado via RPC Oficial"
            st_sub = "O widget altera diretamente o Dispositivo de Saída dentro do Discord."
        elif disc_status.get("mode") == "fixed":
            hint = disc_status.get("hint") or "um fone específico"
            st_title = "⚠️ Atenção: Saída fixa nas configurações do Discord"
            st_sub = (
                f"No seu Discord (Configurações → Voz e Vídeo → Dispositivo de Saída), a saída está fixa em "
                f"'{hint}' em vez de 'Default'. Mude para 'Default' no Discord (1 única vez) ou conecte o RPC abaixo."
            )
        else:
            st_title = "Status do Discord: Sincronizado (Modo Default)"
            st_sub = "O Discord acompanha automaticamente o Dispositivo de Comunicação Padrão e o Mixer do Windows."

        v.addWidget(
            self._group(
                self._row(st_title, st_sub, None),
                self._toggle(
                    "Sincronizar saída com o Discord",
                    "Altera simultaneamente o Dispositivo Padrão, Comunicação Padrão e o Mixer do processo Discord.exe.",
                    cfg["sync_discord"],
                    lambda on: app.set("sync_discord", on),
                ),
                self._toggle(
                    "Manter microfone fixo (ex: SoloCast)",
                    "Altera apenas o fone/saída de som, sem mexer no seu microfone padrão.",
                    cfg["keep_mic_fixed"],
                    lambda on: app.set("keep_mic_fixed", on),
                ),
            )
        )

        # Seção opcional para Discord Local RPC (trocar o dropdown interno do Discord sem usar 'Default')
        v.addWidget(self._label("Discord RPC Direto (Opcional — sem usar 'Default')", "section"))
        cid_edit = QLineEdit(cfg.get("rpc_client_id", ""))
        cid_edit.setPlaceholderText("Client ID (Discord Developer Portal)")
        cid_edit.setFixedWidth(165)
        cid_edit.editingFinished.connect(lambda: app.set("rpc_client_id", cid_edit.text().strip()))

        csec_edit = QLineEdit(cfg.get("rpc_client_secret", ""))
        csec_edit.setPlaceholderText("Client Secret")
        csec_edit.setEchoMode(QLineEdit.Password)
        csec_edit.setFixedWidth(165)
        csec_edit.editingFinished.connect(lambda: app.set("rpc_client_secret", csec_edit.text().strip()))

        auth_btn = QPushButton("Reconectar RPC" if rpc_ok else "Autorizar no Discord")
        auth_btn.setProperty("kind", "primary" if not rpc_ok else "secondary")
        auth_btn.setCursor(Qt.PointingHandCursor)

        def _do_rpc_auth():
            app.set("rpc_client_id", cid_edit.text().strip())
            app.set("rpc_client_secret", csec_edit.text().strip())
            auth_btn.setText("Autorizando…")
            auth_btn.setEnabled(False)

            def _worker():
                ok, res = AB.discord_rpc_authorize(
                     app.cfg.get("rpc_client_id", ""),
                    app.cfg.get("rpc_client_secret", ""),
                )
                if ok:
                    app.cfg["rpc_access_token"] = res
                    save_config(app.cfg)
                QTimer.singleShot(0, self.build)

            threading.Thread(target=_worker, daemon=True).start()

        auth_btn.clicked.connect(_do_rpc_auth)
        v.addWidget(
            self._group(
                self._row("Client ID", "Adicione Redirect URI http://127.0.0.1 no app.", cid_edit),
                self._row("Client Secret", "Para autenticar SET_VOICE_SETTINGS local.", csec_edit),
                self._row(
                    "Conexão RPC",
                    "Conectado e ativo!" if rpc_ok else "Abre o modal de permissão no seu Discord.",
                    auth_btn,
                ),
            )
        )

        v.addWidget(self._label("Interação na Barra de Tarefas", "section"))
        v.addWidget(
            self._group(
                self._combo(
                    "Ao clicar na pílula",
                    "Como o clique esquerdo funciona no widget da barra.",
                    CLICK_MODE_NAMES,
                    "click_mode",
                ),
                self._toggle(
                    "Ajustar volume com a roda do mouse",
                    "Role o scroll em cima do fone na barra para subir/descer o volume.",
                    cfg["wheel_volume"],
                    lambda on: app.set("wheel_volume", on),
                ),
                self._toggle(
                    "Atalho global Ctrl + Alt + S",
                    "Alterna entre seus fones na hora mesmo dentro de jogos competitivos em tela cheia.",
                    cfg["hotkey_enabled"],
                    lambda on: app.set("hotkey_enabled", on),
                ),
            )
        )

        v.addWidget(self._label("Posição e Sistema", "section"))
        reset_pos = QPushButton("Restaurar")
        reset_pos.setProperty("kind", "secondary")
        reset_pos.setCursor(Qt.PointingHandCursor)
        reset_pos.clicked.connect(lambda: app.set("offset", None))
        v.addWidget(
            self._group(
                self._toggle(
                    "Mostrar widget na barra de tarefas",
                    "Exibe a pílula de áudio ao lado do seu BateriaBT.",
                    cfg["widget_visible"],
                    lambda on: app.set("widget_visible", on),
                ),
                self._row(
                    "Posição na barra",
                    "Arraste o widget com o mouse para qualquer lugar da barra.",
                    reset_pos,
                ),
                self._toggle("Iniciar com o Windows", None, startup_enabled(), set_startup),
            )
        )
        v.addStretch()
        return w

    # --- Aba 3: Design & Destaque ---
    def _design_page(self) -> QWidget:
        app, cfg = self.app, self.app.cfg
        w, v = self._page()

        v.addWidget(self._label("Personalização de Destaque", "section"))

        # Combo dinâmico para escolher QUAL saída fica em destaque
        target_names = {
            "active": "Saída Ativa (Automático)",
            "both": "Ambas as Saídas Acesas",
        }
        for r in app.all_rows():
            target_names[r["id"]] = f"Sempre: {r['name']}"

        target_combo = QComboBox()
        target_combo.setFixedWidth(168)
        for k, label in target_names.items():
            target_combo.addItem(label, k)
        target_combo.setCurrentIndex(max(0, target_combo.findData(cfg["highlight_target"])))
        target_combo.currentIndexChanged.connect(
            lambda i: app.set("highlight_target", target_combo.itemData(i))
        )

        # Seletor de cores de destaque rápidas + botão de cor livre
        swatches = QWidget()
        sh = QHBoxLayout(swatches)
        sh.setContentsMargins(0, 4, 0, 4)
        sh.setSpacing(6)
        for label, hex_col in PRESET_COLORS:
            b = QPushButton()
            b.setFixedSize(26, 26)
            b.setToolTip(f"{label} ({hex_col})")
            b.setCursor(Qt.PointingHandCursor)
            is_sel = cfg["highlight_color"].lower() == hex_col.lower()
            border_str = "2px solid #FFFFFF" if is_sel else f"1px solid { self.pal['border'] }"
            b.setStyleSheet(f"QPushButton{{background:{hex_col};border:{border_str};border-radius:13px}}")
            b.clicked.connect(lambda _=False, hc=hex_col: app.set("highlight_color", hc))
            sh.addWidget(b)
        sh.addStretch()
        pick_btn = QPushButton("Outra cor…")
        pick_btn.setProperty("kind", "secondary")
        pick_btn.setCursor(Qt.PointingHandCursor)
        pick_btn.clicked.connect(self.pick_highlight_color)
        sh.addWidget(pick_btn)

        v.addWidget(
            self._group(
                self._row(
                    "Qual saída fica em destaque",
                    "Escolha destacar a saída ativa ou fixar o destaque em um fone específico.",
                    target_combo,
                ),
                self._combo(
                    "Estilo do destaque",
                    "Como a saída destacada é diferenciada na pílula.",
                    HIGHLIGHT_STYLE_NAMES,
                    "highlight_style",
                ),
                self._row("Cor de destaque principal", "Padrão: Verde BateriaBT (#10B981).", None),
                swatches,
                self._value_slider(
                    "Brilho da saída inativa",
                    25,
                    100,
                    cfg["inactive_opacity"],
                    "%",
                    lambda n: app.set("inactive_opacity", n),
                ),
            )
        )

        v.addWidget(self._label("Formato e Aparência da Pílula", "section"))
        v.addWidget(
            self._group(
                self._combo("O que mostrar", None, DISPLAY_MODE_NAMES, "display_mode"),
                self._toggle(
                    "Mostrar bateria do HyperX Cloud III",
                    "Exibe a % real da bateria quando o Cloud III Wireless estiver ligado.",
                    cfg["show_hyperx_battery"],
                    lambda on: app.set("show_hyperx_battery", on),
                ),
                self._combo("Tema", None, THEME_NAMES, "theme"),
                self._combo("Estilo da moldura", None, STYLE_NAMES, "widget_style"),
                self._combo("Estilo dos ícones", None, ICON_NAMES, "icon_style"),
                self._value_slider(
                    "Opacidade do fundo",
                    30,
                    100,
                    cfg["widget_opacity"],
                    "%",
                    lambda n: app.set("widget_opacity", n),
                ),
            )
        )
        v.addStretch()
        return w

    # --- Página de Detalhes e Personalização de uma Saída ---
    def open_detail(self, did: str):
        d = next((r for r in self.app.all_rows() if r["id"] == did), None)
        if d is None:
            return self.close_detail()
        self.detail_did = did
        if self.stack.count() > 3:
            old = self.stack.widget(3)
            self.stack.removeWidget(old)
            old.deleteLater()
        pg = self._scroll(self._detail_page(d))
        self.stack.addWidget(pg)
        self.stack.setCurrentWidget(pg)
        self.tabs_frame.hide()

    def close_detail(self):
        self.detail_did = None
        if hasattr(self, "stack"):
            if self.stack.count() > 3:
                old = self.stack.widget(3)
                self.stack.removeWidget(old)
                old.deleteLater()
            self.stack.setCurrentIndex(self.tab)
            self.tabs_frame.show()

    def _detail_page(self, d: dict) -> QWidget:
        app, cfg, did = self.app, self.app.cfg, d["id"]
        w, v = self._page()
        top = QHBoxLayout()
        top.addWidget(self._icon_button("", "Voltar", self.close_detail))
        top.addWidget(self._label(d["name"], "title"))
        top.addStretch()
        act_btn = QPushButton("Ativo no momento" if d["active"] else "Ativar agora")
        act_btn.setProperty("kind", "primary" if not d["active"] else "secondary")
        act_btn.setCursor(Qt.PointingHandCursor)
        act_btn.clicked.connect(lambda: (app.activate_output(did), self.open_detail(did)))
        top.addWidget(act_btn)
        v.addLayout(top)

        v.addWidget(OutputCard(self, d, clickable=False))

        # Nome curto personalizado
        name_edit = QLineEdit(cfg["names"].get(did, ""))
        name_edit.setPlaceholderText(d["default_short_name"])
        name_edit.setFixedWidth(160)
        name_edit.editingFinished.connect(lambda: app.rename(did, name_edit.text()))

        # Tipo de ícone
        kind_combo = QComboBox()
        for k, label in G.KIND_LABELS.items():
            kind_combo.addItem(label, k)
        kind_combo.setCurrentIndex(max(0, kind_combo.findData(d["kind"])))
        kind_combo.currentIndexChanged.connect(lambda i: app.set_kind(did, kind_combo.itemData(i)))

        # Cor exclusiva para este dispositivo
        col_btn = QPushButton("Escolher cor…")
        col_btn.setProperty("kind", "secondary")
        col_btn.setCursor(Qt.PointingHandCursor)
        dev_col = cfg["device_colors"].get(did)
        if dev_col:
            fg = "#000000" if QColor(dev_col).lightnessF() > 0.6 else "#FFFFFF"
            col_btn.setText(dev_col)
            col_btn.setStyleSheet(
                f"QPushButton{{background:{dev_col};color:{fg};border:none;border-radius:8px;padding:6px 12px;font-weight:700}}"
            )
        col_btn.clicked.connect(lambda: self.pick_device_color(did))

        reset_col = QPushButton("Usar cor geral")
        reset_col.setProperty("kind", "secondary")
        reset_col.setCursor(Qt.PointingHandCursor)
        reset_col.clicked.connect(lambda: (app.set_device_color(did, None), self.open_detail(did)))

        col_wrap = QWidget()
        ch = QHBoxLayout(col_wrap)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.setSpacing(6)
        ch.addWidget(col_btn)
        if dev_col:
            ch.addWidget(reset_col)

        v.addWidget(
            self._group(
                self._row("Nome curto na pílula", f"Original: {d['full_name']}", name_edit),
                self._row("Ícone do dispositivo", None, kind_combo),
                self._row("Cor de destaque exclusiva", "Opcional: cor própria quando este fone estiver em destaque.", col_wrap),
            )
        )

        # Controle de volume direto
        if d.get("volume") is not None:
            v.addWidget(self._label("Volume desta saída", "section"))
            vol_slider = self._value_slider(
                "Nível de volume",
                0,
                100,
                d["volume"],
                "%",
                lambda n: AB.set_device_volume(did, n),
            )
            v.addWidget(self._group(vol_slider))

        v.addStretch()
        return w

    def refresh_outputs(self):
        if not self.body:
            return
        self.subtitle.setText(self._subtitle_text())
        old = self.pages[0].takeWidget()
        old.deleteLater()
        page = self._outputs_page()
        page.setObjectName("Page")
        page.setFixedWidth(self.W - 32 - 10)
        self.pages[0].setWidget(page)
        self._fit()

    def on_config(self, key: str):
        if not self.isVisible():
            return
        if key in ("theme", "highlight_color", "highlight_target", "device_colors"):
            QTimer.singleShot(0, self.build)
        elif key in ("hidden", "names", "kinds"):
            self.refresh_outputs()

    def pick_highlight_color(self):
        self._modal = True
        c = QColorDialog.getColor(QColor(self.app.cfg["highlight_color"]), None, "Cor de destaque")
        self._modal = False
        if c.isValid():
            self.app.set("highlight_color", c.name())
        self.show()
        self.activateWindow()

    def pick_device_color(self, did: str):
        self._modal = True
        cur = self.app.cfg["device_colors"].get(did, self.app.cfg["highlight_color"])
        c = QColorDialog.getColor(QColor(cur), None, "Cor exclusiva deste fone")
        self._modal = False
        if c.isValid():
            self.app.set_device_color(did, c.name())
        self.show()
        self.activateWindow()
        self.open_detail(did)

    def toggle(self):
        if self.isVisible():
            self.hide()
            return
        if time.monotonic() - self._hidden_at < 0.25:
            return
        self.detail_did = None
        self.build()
        scr = QGuiApplication.primaryScreen().availableGeometry()
        # Posiciona logo acima da pílula do widget (ou no canto inferior direito)
        wx = self.app.widget.x() + self.app.widget.width() // 2 - self.width() // 2
        x = max(scr.left() + 10, min(wx, scr.right() - self.width() - 11))
        y = scr.bottom() - self.height() - 11
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QColor(self.pal["border"]))
        p.setBrush(QColor(self.pal["bg"]))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        p.end()

    def changeEvent(self, e):
        if e.type() == QEvent.ActivationChange and not self.isActiveWindow() and not self._modal:
            self.hide()
        super().changeEvent(e)

    def hideEvent(self, e):
        self._hidden_at = time.monotonic()
        super().hideEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close_detail() if self.detail_did else self.hide()


# ---------- Leitor Assíncrono de Bateria do HyperX Cloud III Wireless ----------
class HyperXBatteryWorker(QObject):
    done = Signal(object)

    def __init__(self):
        super().__init__()
        self._busy = False

    def refresh(self):
        if self._busy:
            return
        self._busy = True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            res = AB.read_hyperx_cloud_battery()
        except Exception:
            res = None
        self._busy = False
        try:
            self.done.emit(res)
        except RuntimeError:
            pass


# ---------- Ouvinte de Atalho Global (Ctrl+Alt+S) ----------
class GlobalHotkeyPoller(QObject):
    triggered = Signal()

    def __init__(self, app):
        super().__init__()
        self.app = app
        self._was_down = False
        self.timer = QTimer(self, interval=60, timeout=self._check)
        self.timer.start()

    def _check(self):
        if not self.app.cfg.get("hotkey_enabled", True):
            return
        # VK_CONTROL (0x11), VK_MENU/ALT (0x12), 'S' (0x53)
        ctrl = bool(user32.GetAsyncKeyState(0x11) & 0x8000)
        alt = bool(user32.GetAsyncKeyState(0x12) & 0x8000)
        s_key = bool(user32.GetAsyncKeyState(0x53) & 0x8000)
        down = ctrl and alt and s_key
        if down and not self._was_down:
            self._was_down = True
            self.triggered.emit()
        elif not down:
            self._was_down = False


# ---------- Aplicativo Principal ----------
class App:
    def __init__(self, qapp: QApplication):
        self.qapp = qapp
        self.cfg = load_config()
        self.raw_outputs = []
        self.microphones = []
        self.hyperx_state = None  # {"connected": bool, "battery": int|None, "charging": bool}

        self.widget = TaskbarWidget(self)
        self.panel = Panel(self)
        self.tray = QSystemTrayIcon()
        self.menu = round_menu(QMenu())
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._tray_click)

        self.hx_worker = HyperXBatteryWorker()
        self.hx_worker.done.connect(self._on_hyperx_battery)

        self.hotkey = GlobalHotkeyPoller(self)
        self.hotkey.triggered.connect(self.cycle_output)

        # Polling leve de estado de áudio (para refletir trocas feitas pelo Windows/teclado imediatamente)
        self.audio_timer = QTimer(interval=1500, timeout=self.poll_audio_state)
        self.audio_timer.start()

        # Polling de bateria do HyperX Cloud III Wireless a cada 30s
        self.batt_timer = QTimer(interval=30_000, timeout=self.hx_worker.refresh)
        self.batt_timer.start()

        self.refresh()
        self.tray.show()

    def _tray_click(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.panel.toggle()
        elif reason == QSystemTrayIcon.MiddleClick:
            self.cycle_output()

    def _on_hyperx_battery(self, data):
        self.hyperx_state = data
        self.redraw()
        if self.panel.isVisible():
            self.panel.refresh_outputs()

    def refresh(self):
        self.poll_audio_state(force_redraw=True)
        self.hx_worker.refresh()

    def poll_audio_state(self, force_redraw: bool = False):
        outs = AB.list_audio_devices(AB.eRender)
        mics = AB.list_audio_devices(AB.eCapture)
        self.microphones = mics

        # Na 1ª execução, configura automaticamente apenas os fones principais visíveis (Cloud III e KZ EDX Pro)
        if not self.cfg["initialized_defaults"] and outs:
            auto_hidden = []
            preferred_order = []
            for d in outs:
                fn = d["full_name"].lower()
                if AB.is_virtual_noise_device(fn) or d["default_kind"] == "monitor":
                    auto_hidden.append(d["id"])
                else:
                    # Coloca Cloud III primeiro e KZ EDX Pro em segundo (lado a lado!)
                    if "cloud iii" in fn or "hyperx" in fn:
                        preferred_order.insert(0, d["id"])
                    else:
                        preferred_order.append(d["id"])
            self.cfg["hidden"] = auto_hidden
            self.cfg["order"] = preferred_order
            self.cfg["initialized_defaults"] = True
            save_config(self.cfg)

        # Registra nomes conhecidos
        known_changed = False
        for d in outs:
            did = d["id"]
            if self.cfg["known"].get(did) != d["full_name"]:
                self.cfg["known"][did] = d["full_name"]
                known_changed = True
            if did not in self.cfg["kinds"]:
                self.cfg["kinds"][did] = d["default_kind"]
                known_changed = True
        if known_changed:
            save_config(self.cfg)

        # Se o dispositivo padrão do PC e o de Comunicação (Discord) dessincronizaram externamente
        # e sync_discord estiver ativo, garante que o Discord acompanhe a saída padrão do PC
        if self.cfg["sync_discord"]:
            def_con = next((d for d in outs if d["is_default_console"]), None)
            def_com = next((d for d in outs if d["is_default_comm"]), None)
            if def_con and def_com and def_con["id"] != def_com["id"]:
                AB.switch_audio_output(def_con["id"], sync_discord=True, sync_comm=True)
                for d in outs:
                    d["is_default_comm"] = d["id"] == def_con["id"]

        prev_signature = [
            (d["id"], d["is_default_console"], d["is_default_comm"], d["volume"], d["muted"])
            for d in self.raw_outputs
        ]
        new_signature = [
            (d["id"], d["is_default_console"], d["is_default_comm"], d["volume"], d["muted"])
            for d in outs
        ]
        self.raw_outputs = outs
        if force_redraw or prev_signature != new_signature:
            self.redraw()
            if self.panel.isVisible():
                self.panel.refresh_outputs()

    def _entry(self, d: dict) -> dict:
        did = d["id"]
        name = self.cfg["names"].get(did) or d["default_short_name"]
        kind = self.cfg["kinds"].get(did) or d["default_kind"]
        is_hyperx = "cloud iii" in d["full_name"].lower() or "hyperx" in d["full_name"].lower()
        batt = None
        charging = False
        if is_hyperx and self.hyperx_state and self.hyperx_state.get("connected"):
            batt = self.hyperx_state.get("battery")
            charging = bool(self.hyperx_state.get("charging"))

        return {
            "id": did,
            "name": name,
            "full_name": d["full_name"],
            "default_short_name": d["default_short_name"],
            "kind": kind,
            "active": d["is_default_console"],
            "comm_active": d["is_default_comm"],
            "volume": d["volume"],
            "muted": d["muted"],
            "battery": batt,
            "charging": charging,
        }

    def all_rows(self) -> list[dict]:
        order = self.cfg.get("order", [])
        rows = [self._entry(d) for d in self.raw_outputs]
        rows.sort(
            key=lambda r: (
                order.index(r["id"]) if r["id"] in order else 999,
                0 if "cloud" in r["name"].lower() else (1 if "kz" in r["name"].lower() else 2),
                r["name"].lower(),
            )
        )
        return rows

    def visible_rows(self) -> list[dict]:
        return [r for r in self.all_rows() if r["id"] not in self.cfg["hidden"]]

    def activate_output(self, device_id: str):
        """Ativa a saída escolhida no Windows e no Discord simultaneamente."""
        # Preserva o microfone atual se keep_mic_fixed estiver ligado
        fixed_mic = None
        if self.cfg["keep_mic_fixed"]:
            cur_mic = next((m for m in self.microphones if m["is_default_console"]), None)
            if cur_mic:
                fixed_mic = cur_mic["id"]

        ok = AB.switch_audio_output(
            device_id,
            sync_discord=self.cfg["sync_discord"],
            sync_comm=True,
            linked_mic_id=fixed_mic,
            rpc_client_id=self.cfg.get("rpc_client_id", ""),
            rpc_access_token=self.cfg.get("rpc_access_token", ""),
        )
        if ok:
            for d in self.raw_outputs:
                is_target = d["id"] == device_id
                d["is_default_console"] = is_target
                d["is_default_comm"] = is_target
            self.widget.flash_device(device_id)
            self.redraw()
            if self.panel.isVisible():
                self.panel.refresh_outputs()
            if self.cfg.get("notify_on_switch"):
                row = next((r for r in self.all_rows() if r["id"] == device_id), None)
                if row:
                    self.tray.showMessage(
                        APP_TITLE,
                        f"Saída alterada para {row['name']} (PC + Discord)",
                        QSystemTrayIcon.Information,
                        2500,
                    )

    def cycle_output(self):
        """Alterna entre as saídas visíveis na pílula (ex: Cloud III <-> KZ EDX Pro)."""
        rows = self.visible_rows()
        if not rows:
            rows = self.all_rows()
        if not rows:
            return
        cur_idx = next((i for i, r in enumerate(rows) if r["active"]), -1)
        next_row = rows[(cur_idx + 1) % len(rows)]
        self.activate_output(next_row["id"])

    # --- Mutadores de Configuração ---
    def set(self, key: str, value):
        self.cfg[key] = value
        save_config(self.cfg)
        self.redraw()
        self.panel.on_config(key)

    def toggle_hidden(self, did: str):
        hidden = set(self.cfg["hidden"]) ^ {did}
        self.set("hidden", sorted(hidden))

    def rename(self, did: str, new_name: str):
        names = dict(self.cfg["names"])
        new_name = new_name.strip()
        if new_name:
            names[did] = new_name
        else:
            names.pop(did, None)
        self.set("names", names)

    def set_kind(self, did: str, kind: str):
        kinds = {**self.cfg["kinds"], did: kind}
        self.set("kinds", kinds)

    def set_device_color(self, did: str, hex_col: str | None):
        cols = dict(self.cfg["device_colors"])
        if hex_col:
            cols[did] = hex_col
        else:
            cols.pop(did, None)
        self.set("device_colors", cols)

    # --- Menu de Contexto (Botão Direito na Pílula ou Bandeja) ---
    def show_context_menu(self, global_pos: QPoint):
        self._populate_menu()
        self.menu.exec(global_pos)

    def _populate_menu(self):
        self.menu.clear()
        pal = palette(self.cfg["theme"], self.cfg["highlight_color"])
        self.menu.setStyleSheet(menu_stylesheet(pal))

        rows = self.all_rows()
        for r in rows:
            prefix = "✓  " if r["active"] else "    "
            batt_str = f" ({r['battery']}%)" if r.get("battery") is not None else ""
            act = QAction(f"{prefix}{r['name']}{batt_str}", self.menu)
            act.triggered.connect(lambda _=False, did=r["id"]: self.activate_output(did))
            self.menu.addAction(act)

        self.menu.addSeparator()

        # Submenu: Qual saída fica em destaque
        hl_menu = round_menu(self.menu.addMenu("Qual saída fica em destaque"))
        hl_menu.setStyleSheet(menu_stylesheet(pal))
        cur_target = self.cfg["highlight_target"]
        for key, label in [
            ("active", "Saída ativa no momento (Padrão)"),
            ("both", "Ambas as saídas acesas"),
            *[(r["id"], f"Sempre destacar: {r['name']}") for r in rows],
        ]:
            a = QAction(("✓  " if cur_target == key else "    ") + label, hl_menu)
            a.triggered.connect(lambda _=False, k=key: self.set("highlight_target", k))
            hl_menu.addAction(a)

        # Submenu: Saídas visíveis na pílula
        vis_menu = round_menu(self.menu.addMenu("Saídas visíveis na pílula"))
        vis_menu.setStyleSheet(menu_stylesheet(pal))
        for r in rows:
            shown = r["id"] not in self.cfg["hidden"]
            a = QAction(("✓  " if shown else "    ") + f"{r['name']} ({r['full_name']})", vis_menu)
            a.triggered.connect(lambda _=False, did=r["id"]: self.toggle_hidden(did))
            vis_menu.addAction(a)

        # Sincronizar Discord
        sync_act = QAction("Sincronizar com o Discord", self.menu, checkable=True)
        sync_act.setChecked(self.cfg["sync_discord"])
        sync_act.toggled.connect(lambda on: self.set("sync_discord", on))
        self.menu.addAction(sync_act)

        self.menu.addSeparator()
        self.menu.addAction("Abrir painel de configurações…", lambda: self.panel.isVisible() or self.panel.toggle())
        self.menu.addAction("Alternar fone agora (Ctrl+Alt+S)", self.cycle_output)
        self.menu.addAction("Restaurar posição na barra", lambda: self.set("offset", None))
        self.menu.addSeparator()
        self.menu.addAction("Sair", self.qapp.quit)

    def redraw(self):
        vis = self.visible_rows()
        self.widget.set_rows(vis)
        active = next((r for r in self.all_rows() if r["active"]), None)
        self.tray.setIcon(self.make_tray_icon(active))
        tip_lines = [APP_TITLE]
        for r in vis:
            mark = "● " if r["active"] else "○ "
            b = f" · {r['battery']}%" if r.get("battery") is not None else ""
            tip_lines.append(f"{mark}{r['name']}{b}")
        self.tray.setToolTip("\n".join(tip_lines))
        self._populate_menu()

    def make_tray_icon(self, active_row: dict | None) -> QIcon:
        pm = QPixmap(64, 64)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        col = self.widget.row_highlight_color(active_row) if active_row else QColor("#10B981")
        kind = active_row["kind"] if active_row else "headset"
        G.draw_device_icon(p, QRectF(6, 6, 52, 52), kind, col, weight=2.2, style=self.cfg["icon_style"])
        p.end()
        return QIcon(pm)


class NoWheel(QObject):
    """Faz a roda do mouse rolar o painel em vez de alterar combos acidentalmente."""

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Wheel and isinstance(obj, (QComboBox, QSpinBox)):
            w = obj.parent()
            while w and not isinstance(w, QScrollArea):
                w = w.parent()
            if w:
                QApplication.sendEvent(w.verticalScrollBar(), e)
            return True
        return False


def main():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(CONFIG_DIR / "app.lock"))
    if not lock.tryLock(2000 if "--restart" in sys.argv else 100):
        return
    log = open(CONFIG_DIR / "erros.log", "a", encoding="utf-8", buffering=1)
    sys.stderr = log
    qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setStyle("Fusion")
    qapp.setFont(QFont("Segoe UI", 9))
    no_wheel = NoWheel(qapp)
    qapp.installEventFilter(no_wheel)
    if startup_enabled():
        set_startup(True)
    app = App(qapp)  # noqa: F841
    sys.exit(qapp.exec())


if __name__ == "__main__":
    main()
