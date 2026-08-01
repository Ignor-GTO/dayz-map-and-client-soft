"""Always-on-top SCUM map overlay (Edge WebView2 via pywebview).

Runs in a separate process so WebView2 has its own UI thread (tkinter already
owns the main loop in ScumMapClient).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

OVERLAY_TITLE = "GTO Map · SCUM"
OVERLAY_FLAG = "--map-overlay"


def _screen_geometry(frac: float = 0.85) -> tuple[int, int, int, int]:
    try:
        import ctypes

        user32 = ctypes.windll.user32
        sw = int(user32.GetSystemMetrics(0))
        sh = int(user32.GetSystemMetrics(1))
    except Exception:
        sw, sh = 1600, 900
    w = max(1100, int(sw * frac))
    h = max(700, int(sh * frac))
    x = max(0, (sw - w) // 2)
    y = max(0, (sh - h) // 2)
    return w, h, x, y


def force_window_topmost(title: str = OVERLAY_TITLE) -> bool:
    """Win32: pin named window above others (helps vs borderless games)."""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, title)
        if not hwnd:
            return False

        HWND_TOPMOST = -1
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_SHOWWINDOW = 0x0040
        SW_RESTORE = 9

        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetWindowPos(
            hwnd,
            HWND_TOPMOST,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
        )
        user32.BringWindowToTop(hwnd)
        # Allow SetForegroundWindow from background process helpers.
        try:
            user32.AllowSetForegroundWindow(-1)
        except Exception:
            pass
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception as exc:
        logger.debug("force_window_topmost failed: %s", exc)
        return False


def run_overlay_process(url: str) -> int:
    """Entry point for the child process. Blocks until the window closes."""
    url = (url or "").strip()
    if not url:
        return 2

    try:
        import webview
    except ImportError:
        print("pywebview is not installed", file=sys.stderr)
        return 3

    w, h, x, y = _screen_geometry(0.88)

    stop = threading.Event()

    def keep_topmost() -> None:
        # Give WebView a moment to create the HWND, then pin it.
        time.sleep(0.6)
        for _ in range(8):
            if stop.is_set():
                return
            force_window_topmost(OVERLAY_TITLE)
            time.sleep(0.35)
        while not stop.wait(1.5):
            force_window_topmost(OVERLAY_TITLE)

    threading.Thread(target=keep_topmost, daemon=True, name="overlay-topmost").start()

    try:
        webview.create_window(
            title=OVERLAY_TITLE,
            url=url,
            width=w,
            height=h,
            x=x,
            y=y,
            on_top=True,
            frameless=False,
            easy_drag=False,
            background_color="#0b1220",
            text_select=True,
            focus=True,
        )
    except TypeError:
        webview.create_window(
            title=OVERLAY_TITLE,
            url=url,
            width=w,
            height=h,
            on_top=True,
        )

    try:
        webview.start(gui="edgechromium")
    except Exception:
        try:
            webview.start()
        except Exception as exc:
            print(f"webview.start failed: {exc}", file=sys.stderr)
            stop.set()
            return 4
    stop.set()
    return 0


class ScumMapOverlay:
    """Controller in the Tk app: spawn/kill a dedicated overlay process."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    @property
    def visible(self) -> bool:
        proc = self._proc
        return proc is not None and proc.poll() is None

    def toggle(self, url_factory: Callable[[], str | None]) -> bool:
        with self._lock:
            if self.visible:
                self._kill_unlocked()
                return False

        url = (url_factory() or "").strip()
        if not url:
            raise RuntimeError("Не удалось получить ссылку для оверлея карты")

        with self._lock:
            if self.visible:
                self._kill_unlocked()
                return False
            self._proc = self._spawn(url)

        # Confirm the child actually stayed up (common failure: missing WebView2).
        time.sleep(0.9)
        proc = self._proc
        if proc is None:
            raise RuntimeError("Не удалось запустить процесс оверлея")
        code = proc.poll()
        if code is not None:
            self._proc = None
            raise RuntimeError(
                f"Оверлей сразу закрылся (код {code}). "
                "Проверьте Edge WebView2 Runtime и что клиент собран с pywebview. "
                "В SCUM лучше режим «Borderless windowed» — exclusive fullscreen "
                "прячет обычные окна поверх игры."
            )

        # Extra nudge from parent process too.
        force_window_topmost(OVERLAY_TITLE)
        return True

    def hide(self) -> None:
        with self._lock:
            self._kill_unlocked()

    def destroy(self) -> None:
        self.hide()

    def _spawn(self, url: str) -> subprocess.Popen:
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, OVERLAY_FLAG, url]
        else:
            worker = Path(__file__).resolve().parent / "map_overlay_worker.py"
            cmd = [sys.executable, str(worker), url]

        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        env = os.environ.copy()
        # Onefile PyInstaller: child must reuse parent's unpacked dir.
        # (We previously cleared this and got "_PYI_APPLICATION_HOME_DIR not set".)
        if getattr(sys, "frozen", False):
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                env["_PYI_APPLICATION_HOME_DIR"] = str(meipass)
            # Keep as worker of this app instance — do NOT reset environment.
            env.pop("PYINSTALLER_RESET_ENVIRONMENT", None)

        return subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )

    def _kill_unlocked(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        if proc.poll() is not None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except Exception:
                proc.kill()
        except Exception as exc:
            logger.debug("overlay kill failed: %s", exc)
