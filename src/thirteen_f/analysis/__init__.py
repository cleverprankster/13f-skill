"""Analysis tools: diff engine, signals, clustering."""

from .clustering import assign_cluster
from .diff import compute_quarter_diff
from .signals import detect_signals

__all__ = [
    "compute_quarter_diff",
    "detect_signals",
    "assign_cluster",
]
