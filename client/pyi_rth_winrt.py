# Preload stdlib modules that winrt imports dynamically in frozen builds.
import uuid  # noqa: F401

try:
    import _uuid  # noqa: F401
except ImportError:
    pass
