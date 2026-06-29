"""BRT3: post-processing bug reproduction test generation."""

from pathlib import Path
import sys

__version__ = "0.1.0"

_PACKAGE_ROOT = str(Path(__file__).resolve().parent)
if _PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, _PACKAGE_ROOT)
