"""
Wallpaper Animado para Windows 10/11

Arquitetura (para nao travar):
  - Processo "controle": janela, bandeja, biblioteca de videos, configuracoes.
  - Processo "player"  : toca o video atras dos icones. Se travar, o controle
                         detecta (heartbeat) e reinicia so o player.
"""
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QTimer, QPoint
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap, QBrush, QPolygon
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QSlider, QSystemTrayIcon, QMenu, QVBoxLayout, QWidget,
)

APP_NAME = "WallpaperAnimado"
VIDEO_EXTS = "Vídeos (*.mp4 *.mkv *.mov *.avi *.webm *.wmv *.m4v);;Todos (*.*)"
CREATE_NO_WINDOW = 0x08000000

BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
LIB_DIR = DATA_DIR / "videos"
CONFIG = DATA_DIR / "config.json"
HEARTBEAT = DATA_DIR / "heartbeat.txt"
LOGFILE = DATA_DIR / "log.txt"

DEFAULT_CFG = {"current": None, "active": False, "muted": True, "volume": 50,
               "fill": True, "autopause": False}


# ------------------------------------------------------------ utilidades ----
def log(msg):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if LOGFILE.exists() and LOGFILE.stat().st_size > 512_000:
            LOGFILE.write_text("", "utf-8")
        with open(LOGFILE, "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + msg + "\n")
    except Exception:
        pass


def read_cfg():
    cfg = dict(DEFAULT_CFG)
    try:
        cfg.update(json.loads(CONFIG.read_text("utf-8")))
    except Exception:
        pass
    return cfg


def write_cfg(cfg):
    """Escrita atomica: o player nunca le um arquivo pela metade."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2), "utf-8")
    os.replace(tmp, CONFIG)


# ----------------------------------------------------------------- Win32 ----
HWND = wintypes.HWND
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, HWND, wintypes.LPARAM)

if sys.platform == "win32":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = HWND
    user32.FindWindowExW.argtypes = [HWND, HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowExW.restype = HWND
    user32.SendMessageTimeoutW.argtypes = [HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                           wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
    user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
    user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.SetParent.argtypes = [HWND, HWND]
    user32.SetParent.restype = HWND
    user32.MoveWindow.argtypes = [HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.BOOL]
    user32.MoveWindow.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.GetWindowLongPtrW.argtypes = [HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [HWND, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = HWND
    user32.GetClassNameW.argtypes = [HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.IsWindow.argtypes = [HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.GetParent.argtypes = [HWND]
    user32.GetParent.restype = HWND
    user32.SetWindowPos.argtypes = [HWND, HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, wintypes.UINT]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.RedrawWindow.argtypes = [HWND, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    user32.RedrawWindow.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.MonitorFromWindow.argtypes = [HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    user32.GetMonitorInfoW.restype = wintypes.BOOL

    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
else:
    user32 = None
    kernel32 = None


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
                 "SHELLDLL_DefView", "XamlExplorerHostIslandWindow"}


_MUTEXES = []


def acquire_mutex(name):
    """True se conseguiu ser a unica instancia com esse nome."""
    h = kernel32.CreateMutexW(None, False, name)
    already = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
    if not h:
        return True
    if already:
        kernel32.CloseHandle(h)
        return False
    _MUTEXES.append(h)  # mantem vivo ate o processo terminar
    return True


def pid_alive(pid):
    if not pid:
        return True
    h = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if not h:
        return False
    try:
        return kernel32.WaitForSingleObject(h, 0) == 0x102  # WAIT_TIMEOUT
    finally:
        kernel32.CloseHandle(h)


def fullscreen_app_active():
    """True se o programa em primeiro plano cobre o monitor inteiro (jogo, F11, etc.)."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd or not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
        return False
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    if buf.value in SHELL_CLASSES:
        return False
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == os.getpid():
        return False
    r = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return False
    mon = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    if not user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
        return False
    m = mi.rcMonitor
    return r.left <= m.left and r.top <= m.top and r.right >= m.right and r.bottom >= m.bottom


def _find_workerw():
    progman = user32.FindWindowW("Progman", None)
    if not progman:
        raise RuntimeError("Janela Progman nao encontrada")
    # Windows 11 24H2+: WorkerW e filho do Progman
    child = user32.FindWindowExW(progman, None, "WorkerW", None)
    if child:
        return child
    found = []

    def enum_proc(hwnd, _):
        if user32.FindWindowExW(hwnd, None, "SHELLDLL_DefView", None):
            w = user32.FindWindowExW(None, hwnd, "WorkerW", None)
            if w:
                found.append(w)
        return True

    cb = WNDENUMPROC(enum_proc)
    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def find_desktop_host():
    """HWND onde o video e encaixado, atras dos icones (Windows 10 e 11).
    Nunca devolve o Progman (colocaria o video POR CIMA dos icones): se nao achar, levanta erro."""
    progman = user32.FindWindowW("Progman", None)
    if not progman:
        raise RuntimeError("Janela Progman nao encontrada")
    res = ctypes.c_size_t()
    for _ in range(4):
        for wparam, lparam in ((0xD, 0), (0xD, 1), (0, 0)):
            user32.SendMessageTimeoutW(progman, 0x052C, wparam, lparam, 0, 500, ctypes.byref(res))
            host = _find_workerw()
            if host:
                # garante que o WorkerW fica no fundo (atras dos icones)
                user32.SetWindowPos(host, 1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)  # HWND_BOTTOM
                return host
        time.sleep(0.3)
    raise RuntimeError("WorkerW (fundo da area de trabalho) nao encontrado")


def attach_to_desktop(widget, host):
    hwnd = int(widget.winId())
    GWL_STYLE, WS_CHILD, WS_POPUP = -16, 0x40000000, 0x80000000
    GWL_EXSTYLE = -20
    style = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
    user32.SetWindowLongPtrW(hwnd, GWL_STYLE, (style & ~WS_POPUP) | WS_CHILD)
    ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    ex = (ex | 0x80 | 0x08000000) & ~0x40000  # TOOLWINDOW | NOACTIVATE, sem APPWINDOW
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex)
    user32.SetParent(hwnd, host)
    if user32.GetParent(hwnd) != host:
        raise RuntimeError("Nao foi possivel encaixar o video no desktop (SetParent falhou)")


def place(widget, x, y, w, h):
    """Posiciona/mostra a janela sem esperar pelo Explorer (SWP_ASYNCWINDOWPOS evita travar)."""
    hwnd = int(widget.winId())
    vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    # SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_ASYNCWINDOWPOS
    user32.SetWindowPos(hwnd, None, x - vx, y - vy, w, h, 0x0004 | 0x0010 | 0x0040 | 0x4000)
    # RDW_INVALIDATE | RDW_ERASE | RDW_ALLCHILDREN | RDW_UPDATENOW
    user32.RedrawWindow(hwnd, None, None, 0x0001 | 0x0004 | 0x0080 | 0x0100)


# =============================================================== PLAYER ======
class ScreenWallpaper(QVideoWidget):
    def __init__(self, screen, path, muted, volume, fill, start_pos=0):
        super().__init__()
        self.screen_ref = screen
        self._start_pos = start_pos
        self.host = None
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAspectRatioMode(Qt.KeepAspectRatioByExpanding if fill else Qt.KeepAspectRatio)
        self.setStyleSheet("background:black;")

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setMuted(muted)
        self.audio.setVolume(volume / 100)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self)
        self.player.setLoops(QMediaPlayer.Loops.Infinite)
        self.player.errorOccurred.connect(lambda e, msg: log(f"erro player: {e} {msg}"))
        if start_pos > 0:
            self.player.mediaStatusChanged.connect(self._seek_once)
        self.player.setSource(QUrl.fromLocalFile(str(path)))

    def _seek_once(self, status):
        if self._start_pos > 0 and status in (QMediaPlayer.MediaStatus.LoadedMedia,
                                              QMediaPlayer.MediaStatus.BufferedMedia):
            pos, self._start_pos = self._start_pos, 0
            self.player.setPosition(pos)

    def start(self):
        dpr = self.screen_ref.devicePixelRatio()
        g = self.screen_ref.geometry()
        self._rect = (int(g.x() * dpr), int(g.y() * dpr),
                      int(g.width() * dpr), int(g.height() * dpr))
        self.winId()  # cria o HWND SEM mostrar a janela
        try:
            self.host = find_desktop_host()
            attach_to_desktop(self, self.host)  # encaixa antes de aparecer: nunca vira janela solta
        except Exception:
            self.hide()
            raise
        self.show()
        place(self, *self._rect)
        self.player.play()
        for ms in (100, 400, 1200):
            QTimer.singleShot(ms, self._reapply)

    def repair(self):
        """Reencaixa a janela existente no desktop, sem recriar (sem piscar)."""
        try:
            self.host = find_desktop_host()
            attach_to_desktop(self, self.host)
        except Exception:
            self.hide()
            raise
        place(self, *self._rect)
        self.player.setVideoOutput(None)
        self.player.setVideoOutput(self)  # renova a superficie de video
        self.player.play()

    def _reapply(self):
        try:
            place(self, *self._rect)
        except Exception:
            pass

    def alive(self):
        """False se a janela ou o desktop host foram destruidos (precisa recriar)."""
        try:
            hwnd = int(self.winId())
            return bool(user32.IsWindow(self.host) and user32.IsWindow(hwnd))
        except Exception:
            return False

    def attached(self):
        """True se continua filha do desktop host e visivel."""
        try:
            hwnd = int(self.winId())
            return user32.GetParent(hwnd) == self.host and bool(user32.IsWindowVisible(hwnd))
        except Exception:
            return False

    def stop(self):
        try:
            self.hide()
            self.player.stop()
            self.player.setVideoOutput(None)
            self.close()
            self.deleteLater()
        except Exception:
            pass


class PlayerApp:
    """Roda no processo player: obedece o config.json e se auto-repara."""

    def __init__(self, parent_pid):
        self.parent_pid = parent_pid
        self.wallpapers = []
        self.cfg = read_cfg()
        self.sig = None
        self.current = None
        self.paused = False
        self.was_fs = False
        self.rebuilds = []
        self.last_pos = -1
        self.stuck = 0
        self.pending = None
        self.in_fs = False
        self.fs_hits = 0
        self.nofs_hits = 0
        self.fs_since = 0.0
        self.last_tick = 0.0
        self.retry_at = 0
        self.fail_count = 0
        self.n = 0
        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(500)
        self.tick()

    def heartbeat(self):
        try:
            HEARTBEAT.write_text(f"{os.getpid()} {time.time()}", "utf-8")
        except Exception:
            pass

    def reload_cfg(self):
        try:
            st = CONFIG.stat()
            sig = (st.st_mtime_ns, st.st_size)
        except OSError:
            return
        if sig == self.sig:
            return
        try:
            cfg = json.loads(CONFIG.read_text("utf-8"))
        except Exception:
            return  # arquivo sendo escrito; tenta no proximo ciclo
        self.sig = sig
        self.cfg = {**DEFAULT_CFG, **cfg}
        for w in self.wallpapers:
            w.audio.setMuted(self.cfg["muted"])
            w.audio.setVolume(self.cfg["volume"] / 100)
            w.setAspectRatioMode(Qt.KeepAspectRatioByExpanding if self.cfg["fill"] else Qt.KeepAspectRatio)

    def build(self, path, keep_position=False, pos=None):
        if pos is None:
            pos = 0
            if keep_position and self.wallpapers:
                try:
                    pos = int(self.wallpapers[0].player.position())
                except Exception:
                    pos = 0
        self.stop_walls()
        for sc in QApplication.screens():
            w = ScreenWallpaper(sc, path, self.cfg["muted"], self.cfg["volume"], self.cfg["fill"], pos)
            self.wallpapers.append(w)
            w.start()
        self.current = path
        self.last_pos = -1
        self.stuck = 0

    def safe_build(self, path, keep_position=False, pos=None):
        """Recria o wallpaper; se o desktop ainda nao estiver pronto, tenta de novo em 2s."""
        if pos is None:
            pos = 0
            if keep_position and self.wallpapers:
                try:
                    pos = int(self.wallpapers[0].player.position())
                except Exception:
                    pos = 0
        try:
            self.build(path, pos=pos)
            self.pending = None
            self.fail_count = 0
        except Exception:
            self.fail_count += 1
            log(f"falha ao montar wallpaper (tentativa {self.fail_count}):\n" + traceback.format_exc())
            self.stop_walls()
            self.current = None
            if self.fail_count >= 6:
                raise
            self.pending = (path, pos)
            self.retry_at = time.time() + 2

    def stop_walls(self):
        for w in self.wallpapers:
            w.stop()
        self.wallpapers = []

    def check_frozen(self):
        """Se o video diz que toca mas a posicao nao anda por ~6s, recria."""
        if not self.wallpapers:
            return False
        try:
            p = self.wallpapers[0].player
            playing = p.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            pos = int(p.position())
        except Exception:
            return False
        if playing and pos == self.last_pos:
            self.stuck += 1
        else:
            self.stuck = 0
        self.last_pos = pos
        if self.stuck >= 3:
            log("video congelado (posicao parada); recriando")
            self.stuck = 0
            self.rebuild()
            return True
        return False

    def after_fullscreen(self):
        try:
            if self.in_fs:
                return  # voltou para tela cheia; espera sair de novo
            if not self.wallpapers or not self.current:
                return
            log("recriando wallpaper depois da tela cheia")
            self.safe_build(self.current, keep_position=True)
        except Exception:
            log("ERRO apos tela cheia:\n" + traceback.format_exc())

    def fix_all(self, force):
        if not force and self.check_frozen():
            return
        if not all(w.alive() for w in self.wallpapers):
            log("janela/desktop destruido; recriando")
            self.rebuild()
            return
        for w in self.wallpapers:
            if force or not w.attached():
                if not force:
                    log("wallpaper desencaixado; reencaixando")
                try:
                    w.repair()
                except Exception:
                    log("repair falhou; recriando:\n" + traceback.format_exc())
                    self.rebuild()
                    return
            elif w.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                w.player.play()

    def rebuild(self):
        now = time.time()
        self.rebuilds = [t for t in self.rebuilds if now - t < 60]
        if len(self.rebuilds) >= 6:
            log("muitas recriacoes em 1 minuto; ignorando")
            return
        self.rebuilds.append(now)
        self.safe_build(self.current, keep_position=True)

    def quit(self):
        self.timer.stop()
        self.stop_walls()
        QApplication.quit()

    def tick(self):
        self.n += 1
        now_t = time.time()
        if self.last_tick and now_t - self.last_tick > 3:
            log(f"thread do player ficou parada por {now_t - self.last_tick:.1f}s")
        self.last_tick = now_t
        try:
            if self.parent_pid and not pid_alive(self.parent_pid):
                return self.quit()
            if self.n % 2 == 0 or self.n == 1:
                self.heartbeat()
            self.reload_cfg()
            if not self.cfg.get("active") or not self.cfg.get("current"):
                return self.quit()
            path = self.cfg["current"]
            if not Path(path).exists():
                log("video nao existe: " + path)
                return self.quit()
            if self.pending:
                if time.time() >= self.retry_at:
                    p, pos = self.pending
                    self.safe_build(p, pos=pos)
                return
            if path != self.current:
                self.safe_build(path)
                return

            # --- tela cheia com debounce: entra apos ~1s seguido, sai apos ~1,5s sem
            if fullscreen_app_active():
                self.fs_hits += 1
                self.nofs_hits = 0
            else:
                self.nofs_hits += 1
                self.fs_hits = 0
            if not self.in_fs and self.fs_hits >= 2:
                self.in_fs = True
                self.fs_since = time.time()
                log("tela cheia detectada")
                if self.cfg.get("autopause") and not self.paused:
                    self.paused = True
                    for w in self.wallpapers:
                        w.player.pause()
            elif self.in_fs and self.nofs_hits >= 3:
                self.in_fs = False
                dur = time.time() - self.fs_since
                was_paused, self.paused = self.paused, False
                if dur >= 3:
                    log(f"saiu da tela cheia (durou {dur:.0f}s)")
                    QTimer.singleShot(700, self.after_fullscreen)
                else:
                    log(f"tela cheia curta ({dur:.1f}s); ignorada")
                    if was_paused:
                        for w in self.wallpapers:
                            w.player.play()
            if self.in_fs:
                return  # em tela cheia nao mexe em nada (o video segue tocando)
            if self.n % 4 == 0:
                self.fix_all(force=False)
        except Exception:
            log("ERRO no player:\n" + traceback.format_exc())
            self.timer.stop()
            self.stop_walls()
            QApplication.exit(2)  # codigo 2 = falha ao ativar


def run_player(parent_pid):
    # espera um player antigo (de outro controle) terminar; nunca ha dois ao mesmo tempo
    for _ in range(24):
        if acquire_mutex("Local\\WallpaperAnimadoPlayer"):
            break
        time.sleep(0.25)
    else:
        log("outro player ainda ativo; saindo")
        sys.exit(3)
    app = QApplication([sys.argv[0]])
    app.setQuitOnLastWindowClosed(False)
    pa = PlayerApp(parent_pid)  # noqa: F841 (mantem referencia viva)
    sys.exit(app.exec())


# ============================================================== CONTROLE =====
def make_icon():
    png = BASE_DIR / "icon.png"
    if png.exists():
        return QIcon(str(png))
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QBrush(QColor("#6C5CE7")))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(4, 4, 56, 56, 14, 14)
    p.setBrush(QBrush(QColor("white")))
    p.drawPolygon(QPolygon([QPoint(25, 20), QPoint(25, 44), QPoint(45, 32)]))
    p.end()
    return QIcon(pm)


def create_desktop_shortcut():
    """Cria 'Wallpaper Animado.lnk' na area de trabalho. Retorna (ok, mensagem)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    icon_dst = DATA_DIR / "icon.ico"
    try:
        src = BASE_DIR / "icon.ico"
        if src.exists():
            shutil.copy2(src, icon_dst)
    except Exception:
        pass

    if getattr(sys, "frozen", False):
        target, args = sys.executable, ""
    else:
        pyw = Path(sys.executable).with_name("pythonw.exe")
        target = str(pyw if pyw.exists() else sys.executable)
        args = f'"{Path(__file__).resolve()}"'
    workdir = str(Path(target).parent)
    icon = str(icon_dst) if icon_dst.exists() else target

    def q(v):  # escapa aspas simples para o PowerShell
        return str(v).replace("'", "''")

    ps = (
        "$d=[Environment]::GetFolderPath('Desktop');"
        "$l=Join-Path $d 'Wallpaper Animado.lnk';"
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($l);"
        f"$s.TargetPath='{q(target)}';"
        f"$s.Arguments='{q(args)}';"
        f"$s.WorkingDirectory='{q(workdir)}';"
        f"$s.IconLocation='{q(icon)}';"
        "$s.Description='Wallpaper Animado';"
        "$s.Save();"
        "Write-Output $l"
    )
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                           creationflags=CREATE_NO_WINDOW, capture_output=True,
                           text=True, timeout=30)
        out = (r.stdout or "").strip()
        if r.returncode == 0 and out:
            return True, out
        log("atalho falhou: " + (r.stderr or out))
        return False, (r.stderr or out or "erro desconhecido").strip()
    except Exception as ex:
        log("atalho falhou:\n" + traceback.format_exc())
        return False, str(ex)


class MainWindow(QMainWindow):
    def __init__(self, start_hidden=False):
        super().__init__()
        self.setWindowTitle("Wallpaper Animado")
        self.setWindowIcon(make_icon())
        self.resize(520, 540)
        self.proc = None
        self.proc_started = 0.0
        self.starts = []
        self.cfg = self.load_config()
        self.build_ui()
        self.build_tray()
        self.refresh_list()

        self.guard = QTimer(self)
        self.guard.timeout.connect(self.guard_tick)
        self.guard.start(2000)

        if self.cfg.get("active") and self.cfg.get("current"):
            QTimer.singleShot(1500, self.start_player)
        if not start_hidden:
            self.show()

    # ---- config
    def load_config(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        LIB_DIR.mkdir(parents=True, exist_ok=True)
        bundled = BASE_DIR / "videos"
        if bundled.exists():
            for f in bundled.iterdir():
                if f.is_file() and not (LIB_DIR / f.name).exists():
                    shutil.copy2(f, LIB_DIR / f.name)
        return read_cfg()

    def save_config(self):
        write_cfg(self.cfg)

    # ---- processo do player
    def player_alive(self):
        return self.proc is not None and self.proc.poll() is None

    def start_player(self):
        if self.player_alive() or not self.cfg.get("active"):
            return
        now = time.time()
        self.starts = [t for t in self.starts if now - t < 60]
        if len(self.starts) >= 5:
            log("player falhou 5x em 1 minuto; desativando")
            self.cfg["active"] = False
            self.save_config()
            self.refresh_list()
            self.tray.showMessage("Wallpaper Animado",
                                  f"O wallpaper falhou varias vezes. Veja {LOGFILE}",
                                  QSystemTrayIcon.Warning, 5000)
            return
        self.starts.append(now)
        env = os.environ.copy()
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"  # player independente do controle
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--player", str(os.getpid())]
        else:
            pyw = Path(sys.executable).with_name("pythonw.exe")
            exe = pyw if pyw.exists() else Path(sys.executable)
            cmd = [str(exe), str(Path(__file__).resolve()), "--player", str(os.getpid())]
        try:
            self.proc = subprocess.Popen(cmd, env=env, creationflags=CREATE_NO_WINDOW,
                                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL, close_fds=True)
            self.proc_started = time.time()
            log(f"player iniciado (pid {self.proc.pid})")
        except Exception:
            log("falha ao iniciar player:\n" + traceback.format_exc())
            self.proc = None

    def read_heartbeat(self):
        try:
            pid, t = HEARTBEAT.read_text("utf-8").split()
            return int(pid), float(t)
        except Exception:
            return None

    def kill_player(self):
        pids = set()
        if self.player_alive():
            pids.add(self.proc.pid)
        hb = self.read_heartbeat()
        if hb and hb[1] >= self.proc_started - 1 and self.proc_started:
            pids.add(hb[0])
        for pid in pids:
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                               creationflags=CREATE_NO_WINDOW, capture_output=True, timeout=10)
            except Exception:
                pass
        self.proc = None

    def guard_tick(self):
        try:
            if not self.cfg.get("active") or not self.cfg.get("current"):
                return
            if self.player_alive():
                hb = self.read_heartbeat()
                ref = max(hb[1] if hb else 0, self.proc_started)
                if time.time() - ref > 25:
                    log("player sem sinal ha 25s (travado); reiniciando")
                    self.kill_player()
                else:
                    return
            else:
                code = self.proc.poll() if self.proc is not None else None
                if code == 2:
                    self.cfg["active"] = False
                    self.save_config()
                    self.proc = None
                    self.refresh_list()
                    QMessageBox.critical(self, "Erro ao ativar",
                                         f"Nao foi possivel ativar o wallpaper.\nDetalhes em:\n{LOGFILE}")
                    return
            self.start_player()
        except Exception:
            log("ERRO no guard:\n" + traceback.format_exc())

    # ---- UI
    def build_ui(self):
        root = QWidget()
        lay = QVBoxLayout(root)

        lay.addWidget(QLabel("<b>Biblioteca de vídeos</b> (duplo clique para ativar)"))
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda it: self.activate(it.data(Qt.UserRole)))
        lay.addWidget(self.list, 1)

        row = QHBoxLayout()
        b_add = QPushButton("➕ Adicionar vídeo")
        b_add.clicked.connect(self.add_video)
        b_rm = QPushButton("🗑 Remover da lista")
        b_rm.clicked.connect(self.remove_video)
        row.addWidget(b_add); row.addWidget(b_rm)
        lay.addLayout(row)

        row = QHBoxLayout()
        b_set = QPushButton("▶ Definir como papel de parede")
        b_set.clicked.connect(self.set_selected)
        b_off = QPushButton("⏹ Desativar")
        b_off.clicked.connect(self.deactivate)
        row.addWidget(b_set); row.addWidget(b_off)
        lay.addLayout(row)

        self.status = QLabel("")
        lay.addWidget(self.status)

        b_lnk = QPushButton("🖥 Criar atalho na área de trabalho")
        b_lnk.clicked.connect(self.make_shortcut)
        lay.addWidget(b_lnk)

        self.chk_mute = QCheckBox("Sem som")
        self.chk_mute.setChecked(self.cfg["muted"])
        self.chk_mute.toggled.connect(self.on_audio)
        lay.addWidget(self.chk_mute)

        vrow = QHBoxLayout()
        vrow.addWidget(QLabel("Volume"))
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(self.cfg["volume"])
        self.vol.valueChanged.connect(self.on_audio)
        vrow.addWidget(self.vol)
        lay.addLayout(vrow)

        frow = QHBoxLayout()
        frow.addWidget(QLabel("Ajuste"))
        self.fit = QComboBox()
        self.fit.addItems(["Preencher a tela (corta as bordas)", "Ajustar (barras pretas)"])
        self.fit.setCurrentIndex(0 if self.cfg["fill"] else 1)
        self.fit.currentIndexChanged.connect(self.on_fit)
        frow.addWidget(self.fit)
        lay.addLayout(frow)

        self.chk_pause = QCheckBox("Pausar o vídeo em jogo/tela cheia (economiza desempenho)")
        self.chk_pause.setChecked(self.cfg.get("autopause", False))
        self.chk_pause.toggled.connect(self.on_autopause)
        lay.addWidget(self.chk_pause)

        self.chk_boot = QCheckBox("Iniciar com o Windows")
        self.chk_boot.setChecked(self.autostart_enabled())
        self.chk_boot.toggled.connect(self.set_autostart)
        lay.addWidget(self.chk_boot)

        self.setCentralWidget(root)

    def build_tray(self):
        self.tray = QSystemTrayIcon(make_icon(), self)
        menu = QMenu()
        a_open = QAction("Abrir", self, triggered=self.show_normal)
        a_off = QAction("Desativar wallpaper", self, triggered=self.deactivate)
        a_lnk = QAction("Criar atalho na área de trabalho", self, triggered=self.make_shortcut)
        a_quit = QAction("Sair", self, triggered=self.quit_app)
        for a in (a_open, a_off, a_lnk, a_quit):
            menu.addAction(a)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: self.show_normal() if r == QSystemTrayIcon.Trigger else None)
        self.tray.setToolTip("Wallpaper Animado")
        self.tray.show()

    def make_shortcut(self):
        ok, msg = create_desktop_shortcut()
        if ok:
            QMessageBox.information(self, "Atalho criado", f"Atalho criado em:\n{msg}")
        else:
            QMessageBox.warning(self, "Atalho", f"Não foi possível criar o atalho:\n{msg}")

    def show_normal(self):
        self.showNormal(); self.activateWindow()

    def closeEvent(self, e):
        e.ignore()
        self.hide()
        if self.cfg.get("active"):
            self.tray.showMessage("Wallpaper Animado",
                                  "Continua rodando na bandeja do sistema.",
                                  QSystemTrayIcon.Information, 2500)

    def quit_app(self):
        self.guard.stop()
        self.kill_player()
        self.tray.hide()
        QApplication.quit()

    # ---- biblioteca
    def refresh_list(self):
        active = bool(self.cfg.get("active"))
        self.list.clear()
        for f in sorted(LIB_DIR.iterdir()):
            if f.is_file():
                mark = "● " if active and str(f) == self.cfg.get("current") else "   "
                it = QListWidgetItem(mark + f.name)
                it.setData(Qt.UserRole, str(f))
                self.list.addItem(it)
        self.status.setText(
            f"Ativo: {Path(self.cfg['current']).name}" if active and self.cfg.get("current")
            else "Wallpaper animado desativado")

    def add_video(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Escolha vídeo(s)", "", VIDEO_EXTS)
        for f in files:
            dst = LIB_DIR / Path(f).name
            if not dst.exists():
                shutil.copy2(f, dst)
        self.refresh_list()

    def remove_video(self):
        it = self.list.currentItem()
        if not it:
            return
        path = it.data(Qt.UserRole)
        if QMessageBox.question(self, "Remover", f"Remover {Path(path).name} da biblioteca?") != QMessageBox.Yes:
            return
        if path == self.cfg.get("current"):
            self.deactivate()
            time.sleep(1.2)  # deixa o player soltar o arquivo
        try:
            os.remove(path)
        except OSError:
            pass
        self.refresh_list()

    def set_selected(self):
        it = self.list.currentItem()
        if not it:
            QMessageBox.information(self, "Wallpaper", "Selecione um vídeo na lista.")
            return
        self.activate(it.data(Qt.UserRole))

    # ---- wallpaper (so grava config; o player obedece)
    def activate(self, path):
        if not Path(path).exists():
            return
        self.cfg["current"], self.cfg["active"] = path, True
        self.save_config()
        self.start_player()  # se ja estiver rodando, ele troca de video sozinho
        self.refresh_list()

    def deactivate(self):
        self.cfg["active"] = False
        self.save_config()  # o player ve e encerra em ate ~1s
        self.refresh_list()

    def on_audio(self, *_):
        self.cfg["muted"], self.cfg["volume"] = self.chk_mute.isChecked(), self.vol.value()
        self.save_config()

    def on_fit(self, idx):
        self.cfg["fill"] = idx == 0
        self.save_config()

    def on_autopause(self, on):
        self.cfg["autopause"] = on
        self.save_config()

    # ---- iniciar com o Windows
    RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

    def autostart_enabled(self):
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.RUN_KEY) as k:
                winreg.QueryValueEx(k, APP_NAME)
                return True
        except Exception:
            return False

    def set_autostart(self, on):
        import winreg
        if getattr(sys, "frozen", False):
            cmd = f'"{sys.executable}" --hidden'
        else:
            pyw = Path(sys.executable).with_name("pythonw.exe")
            cmd = f'"{pyw}" "{Path(__file__).resolve()}" --hidden'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(k, APP_NAME)
                except FileNotFoundError:
                    pass


def main():
    if sys.platform != "win32":
        print("Este app é para Windows.")
        sys.exit(1)
    if "--player" in sys.argv:
        i = sys.argv.index("--player")
        pid = int(sys.argv[i + 1]) if len(sys.argv) > i + 1 else 0
        run_player(pid)
        return
    if not acquire_mutex("Local\\WallpaperAnimadoControle"):
        ctypes.windll.user32.MessageBoxW(
            None, "O Wallpaper Animado já está aberto.\nProcure o ícone perto do relógio (bandeja).",
            "Wallpaper Animado", 0x40)
        sys.exit(0)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    win = MainWindow(start_hidden="--hidden" in sys.argv)  # noqa: F841
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
