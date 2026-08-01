"""Always-on-top SCUM map overlay (Edge WebView2 via pywebview)."""

from __future__ import annotations

import logging
import threading
from typing import Callable

logger = logging.getLogger(__name__)


def _screen_geometry(frac: float = 0.85) -> tuple[int, int, int, int]:
    """Return width, height, x, y centered on the primary monitor."""
    try:
        import ctypes

        user32 = ctypes.windll.user32
        sw = int(user32.GetSystemMetrics(0))
        sh = int(user32.GetSystemMetrics(1))
    except Exception:
        sw, sh = 1600, 900
    w = max(960, int(sw * frac))
    h = max(640, int(sh * frac))
    x = max(0, (sw - w) // 2)
    y = max(0, (sh - h) // 2)
    return w, h, x, y


class ScumMapOverlay:
    """Singleton-ish overlay controller safe to drive from the Tk UI thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._window = None
        self._visible = False
        self._closing = False
        self._pending_url = "about:blank"

    @property
    def visible(self) -> bool:
        return self._visible and self._window is not None

    def toggle(self, url_factory: Callable[[], str | None]) -> bool:
        """
        Show or hide the overlay.
        url_factory() is called when opening / re-showing (fresh handoff URL).
        Returns True if overlay is now visible.
        """
        with self._lock:
            alive = self._thread is not None and self._thread.is_alive()
            if alive and self._window is not None and self._visible:
                self._hide_unlocked()
                return False
            need_url = True

        url = (url_factory() or "").strip() if need_url else ""
        if not url:
            raise RuntimeError("Не удалось получить ссылку для оверлея карты")

        with self._lock:
            alive = self._thread is not None and self._thread.is_alive()
            if alive and self._window is not None:
                # Hidden existing window — show again with fresh session URL.
                if self._visible:
                    self._hide_unlocked()
                    return False
                self._show_unlocked(url)
                return True

            self._pending_url = url
            self._closing = False
            self._visible = True
            self._thread = threading.Thread(
                target=self._run_webview, daemon=True, name="scum-map-overlay"
            )
            self._thread.start()
            return True

    def hide(self) -> None:
        with self._lock:
            self._hide_unlocked()

    def destroy(self) -> None:
        with self._lock:
            self._closing = True
            win = self._window
            self._visible = False
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass

    def _hide_unlocked(self) -> None:
        self._visible = False
        win = self._window
        if win is None:
            return
        try:
            win.hide()
        except Exception as exc:
            logger.debug("overlay hide failed: %s", exc)

    def _show_unlocked(self, url: str) -> None:
        win = self._window
        if win is None:
            return
        try:
            win.load_url(url)
        except Exception:
            pass
        try:
            win.show()
        except Exception:
            pass
        try:
            win.restore()
        except Exception:
            pass
        try:
            win.on_top = True
        except Exception:
            pass
        self._visible = True

    def _run_webview(self) -> None:
        try:
            import webview
        except ImportError:
            self._visible = False
            logger.exception("pywebview is not installed")
            return

        w, h, x, y = _screen_geometry(0.85)
        try:
            window = webview.create_window(
                title="GTO Map · SCUM",
                url=self._pending_url,
                width=w,
                height=h,
                x=x,
                y=y,
                on_top=True,
                frameless=False,
                easy_drag=False,
                background_color="#0b1220",
                text_select=True,
            )
        except TypeError:
            # Older pywebview without some kwargs
            window = webview.create_window(
                title="GTO Map · SCUM",
                url=self._pending_url,
                width=w,
                height=h,
                on_top=True,
            )

        def on_closed() -> None:
            with self._lock:
                self._visible = False
                self._window = None

        try:
            window.events.closed += on_closed
        except Exception:
            pass

        with self._lock:
            self._window = window

        try:
            webview.start(gui="edgechromium")
        except Exception:
            try:
                webview.start()
            except Exception:
                logger.exception("webview.start failed")
        finally:
            with self._lock:
                self._window = None
                self._visible = False
                self._thread = None
