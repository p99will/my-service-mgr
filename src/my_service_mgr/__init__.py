"""my_service_mgr package.

This package is a starting point for managing custom services/scripts on Linux.
"""

__all__ = ["__version__"]

from importlib.metadata import PackageNotFoundError, version

try:
    # Keep the version sourced from package metadata when installed.
    __version__ = version("my-service-mgr")
except PackageNotFoundError:
    # Fallback for local source usage (e.g. running without installation).
    __version__ = "0.1.4"

