"""
Wallpaper Animado para Windows 10/11
- Usa um vídeo como papel de parede (atrás dos ícones da área de trabalho)
- Biblioteca de vídeos: adicione quantos quiser e troque quando quiser
- "Desativar" volta ao papel de parede normal do Windows
"""
import ctypes
import json
import os
import shutil
import sys
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap, QBrush
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QSlider, QSystemTrayIcon, QMenu, QVBoxLayout, QWidget,
)

APP_NAME = "WallpaperAnimado"
VIDEO_EXTS = "Vídeos (*.mp4 *.mkv *.mov *.avi *.webm *.wmv *.m4v);;Todos (*.*)"

BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
LIB_DIR = DATA_DIR / "videos"
CONFIG = DATA_DIR / "config.json"

user32 = ctypes.windll.user32 if sys.platform == "win32" else None


# ----------------------------------------------------------------- Win32 ----
def _find_desktop_host():
    """Retorna o HWND (WorkerW/Progman) onde o vídeo deve ser encaixado,
    ficando atrás dos ícones. Funciona no Windows 10 e no Windows 11 (incl. 24H2)."""
    progman = user32.FindWindowW("Progman", None)
    res = wintypes.DWORD()
    # Pede ao Explorer para criar a janela WorkerW atrás dos ícones
    for wparam, lparam in ((0xD, 0), (0xD, 1), (0, 0)):
        user32.SendMessageTimeoutW(progman, 0x052C, wparam, lparam, 0, 1000, ctypes.byref(res))

    # Windows 11 24H2+: WorkerW é filho do Progman
    child = user32.FindWindowExW(progman, 0, "WorkerW", None)
    if child:
        return child

    # Windows 10 / 11 antigo: WorkerW irmão logo após o que contém os ícones
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd, _):
        if user32.FindWindowExW(hwnd, 0, "SHELLDLL_DefView", None):
            w = user32.FindWindowExW(0, hwnd, "WorkerW", None)
            if w:
                found.append(w)
        return True

    user32.EnumWindows(enum_proc, 0)
    return found[0] if found else progman


def _attach_to_desktop(widget, host, x, y, w, h):
    hwnd = int(widget.winId())
    GWL_STYLE, WS_CHILD, WS_POPUP = -16, 0x40000000, 0x80000000
    style = user32.GetWindowLongW(hwnd, GWL_STYLE)
    user32.SetWindowLongW(hwnd, GWL_STYLE, (style & ~WS_POPUP) | WS_CHILD)
    user32.SetParent(hwnd, host)
    # coordenadas relativas ao host (origem = canto do desktop virtual)
    vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    user32.MoveWindow(hwnd, x - vx, y - vy, w, h, True)
    user32.ShowWindow(hwnd, 5)


# ------------------------------------------------------------- Wallpaper ----
class ScreenWallpaper(QVideoWidget):
    def __init__(self, screen, path, muted, volume, fill):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setAspectRatioMode(
            Qt.KeepAspectRatioByExpanding if fill else Qt.KeepAspectRatio
        )
        self.setStyleSheet("background:black;")

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setMuted(muted)
        self.audio.setVolume(volume / 100)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self)
        self.player.setLoops(QMediaPlayer.Loops.Infinite)
        self.player.setSource(QUrl.fromLocalFile(str(path)))

        dpr = screen.devicePixelRatio()
        g = screen.geometry()
        x, y = int(g.x() * dpr), int(g.y() * dpr)
        w, h = int(g.width() * dpr), int(g.height() * dpr)
        self.show()
        _attach_to_desktop(self, _find_desktop_host(), x, y, w, h)
        self.player.play()

    def stop(self):
        self.player.stop()
        self.player.setVideoOutput(None)
        self.close()
        self.deleteLater()


# -------------------------------------------------------------- Janela ------
def make_icon():
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QBrush(QColor("#6C5CE7")))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(4, 4, 56, 56, 14, 14)
    p.setBrush(QBrush(QColor("white")))
    from PySide6.QtGui import QPolygon
    from PySide6.QtCore import QPoint
    p.drawPolygon(QPolygon([QPoint(25, 20), QPoint(25, 44), QPoint(45, 32)]))
    p.end()
    return QIcon(pm)


class MainWindow(QMainWindow):
    def __init__(self, start_hidden=False):
        super().__init__()
        self.setWindowTitle("Wallpaper Animado")
        self.setWindowIcon(make_icon())
        self.resize(520, 520)
        self.wallpapers = []
        self.cfg = self.load_config()
        self.build_ui()
        self.build_tray()
        self.refresh_list()

        if self.cfg.get("active") and self.cfg.get("current"):
            QTimer.singleShot(1500, lambda: self.activate(self.cfg["current"]))
        if not start_hidden:
            self.show()

    # ---- config
    def load_config(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        LIB_DIR.mkdir(parents=True, exist_ok=True)
        # copia o(s) vídeo(s) que vêm junto do programa na primeira execução
        bundled = BASE_DIR / "videos"
        if bundled.exists():
            for f in bundled.iterdir():
                if f.is_file() and not (LIB_DIR / f.name).exists():
                    shutil.copy2(f, LIB_DIR / f.name)
        cfg = {"current": None, "active": False, "muted": True, "volume": 50, "fill": True}
        if CONFIG.exists():
            try:
                cfg.update(json.loads(CONFIG.read_text("utf-8")))
            except Exception:
                pass
        return cfg

    def save_config(self):
        CONFIG.write_text(json.dumps(self.cfg, indent=2), "utf-8")

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
        a_quit = QAction("Sair", self, triggered=self.quit_app)
        for a in (a_open, a_off, a_quit):
            menu.addAction(a)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: self.show_normal() if r == QSystemTrayIcon.Trigger else None)
        self.tray.setToolTip("Wallpaper Animado")
        self.tray.show()

    def show_normal(self):
        self.showNormal(); self.activateWindow()

    def closeEvent(self, e):
        # fechar a janela só minimiza para a bandeja; o wallpaper continua tocando
        e.ignore()
        self.hide()
        if self.wallpapers:
            self.tray.showMessage("Wallpaper Animado",
                                  "Continua rodando na bandeja do sistema.",
                                  QSystemTrayIcon.Information, 2500)

    def quit_app(self):
        self.stop_all()
        self.tray.hide()
        QApplication.quit()

    # ---- biblioteca
    def refresh_list(self):
        self.list.clear()
        for f in sorted(LIB_DIR.iterdir()):
            if f.is_file():
                it = QListWidgetItem(("● " if str(f) == self.cfg.get("current") and self.wallpapers else "   ") + f.name)
                it.setData(Qt.UserRole, str(f))
                self.list.addItem(it)
        self.status.setText(
            f"Ativo: {Path(self.cfg['current']).name}" if self.wallpapers and self.cfg.get("current")
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

    # ---- wallpaper
    def stop_all(self):
        for w in self.wallpapers:
            w.stop()
        self.wallpapers = []

    def activate(self, path):
        if not Path(path).exists():
            return
        self.stop_all()
        for s in QApplication.screens():
            self.wallpapers.append(ScreenWallpaper(
                s, path, self.chk_mute.isChecked(), self.vol.value(), self.cfg["fill"]))
        self.cfg["current"], self.cfg["active"] = path, True
        self.save_config()
        self.refresh_list()

    def deactivate(self):
        self.stop_all()
        self.cfg["active"] = False
        self.save_config()
        self.refresh_list()

    def on_audio(self, *_):
        self.cfg["muted"], self.cfg["volume"] = self.chk_mute.isChecked(), self.vol.value()
        for w in self.wallpapers:
            w.audio.setMuted(self.cfg["muted"])
            w.audio.setVolume(self.cfg["volume"] / 100)
        self.save_config()

    def on_fit(self, idx):
        self.cfg["fill"] = idx == 0
        for w in self.wallpapers:
            w.setAspectRatioMode(Qt.KeepAspectRatioByExpanding if self.cfg["fill"] else Qt.KeepAspectRatio)
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
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    win = MainWindow(start_hidden="--hidden" in sys.argv)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
