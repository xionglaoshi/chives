"""Local A-share daily bar store (T154).

The package is the single data source for the surge rule engine (T155).
Standard library only: SQLite storage, ``urllib`` HTTP, no third-party runtime
dependency.
"""

from .store import Bar, DailyStore

__all__ = ["Bar", "DailyStore"]
__version__ = "0.1.0"
