"""Report generation."""

from .fund_report import generate_fund_report
from .stock_report import generate_stock_report, generate_stock_history_report
from .universe import generate_universe_report

__all__ = [
    "generate_fund_report",
    "generate_universe_report",
    "generate_stock_report",
    "generate_stock_history_report",
]
