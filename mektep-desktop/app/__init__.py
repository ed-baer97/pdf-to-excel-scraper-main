"""Mektep Desktop Application Package"""

try:
    from ..version import APP_VERSION as __version__
except ImportError:
    from version import APP_VERSION as __version__  # type: ignore[no-redef]
