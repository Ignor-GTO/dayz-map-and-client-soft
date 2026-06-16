# Preload stdlib and winrt modules used via dynamic imports in frozen builds.
import uuid  # noqa: F401

try:
    import _uuid  # noqa: F401
except ImportError:
    pass

for _mod in (
    "winrt.windows.foundation.collections",
    "winrt.windows.foundation",
    "winrt.windows.globalization",
    "winrt.windows.graphics.imaging",
    "winrt.windows.media.ocr",
    "winrt.windows.storage.streams",
):
    try:
        __import__(_mod)
    except ImportError:
        pass
