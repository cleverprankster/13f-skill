"""Stock holdings storage management."""

import json
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import yaml

from ..config import Config
from ..sec.quarterly_data import HoldingRecord


def _validate_path_component(value: str, name: str) -> str:
    """Validate a value is safe to use as a path component.

    Prevents path traversal attacks by rejecting:
    - Path separators (/, \\)
    - Parent directory references (..)
    - Null bytes
    - Empty strings

    Args:
        value: The value to validate
        name: Name of the field for error messages

    Returns:
        The validated value (uppercase for consistency)

    Raises:
        ValueError: If the value contains unsafe characters
    """
    if not value:
        raise ValueError(f"{name} cannot be empty")

    # Check for path traversal attempts
    if '/' in value or '\\' in value:
        raise ValueError(f"{name} contains invalid path separator")
    if '..' in value:
        raise ValueError(f"{name} contains invalid path reference")
    if '\x00' in value:
        raise ValueError(f"{name} contains null byte")

    # Only allow alphanumeric, dash, underscore for safety
    if not re.match(r'^[\w\-]+$', value):
        raise ValueError(f"{name} contains invalid characters")

    return value.upper()


@dataclass
class TrackedStock:
    """A stock being tracked."""

    ticker: str
    cusip: str
    name: str
    added_at: str  # ISO timestamp
    quarters_stored: int = 0
    total_holders: int = 0


def get_tracked_stocks_path(config: Config) -> Path:
    """Get path to tracked stocks YAML file."""
    return config.data_dir / "tracked_stocks.yaml"


def get_stock_data_dir(config: Config) -> Path:
    """Get directory for stock holdings data."""
    data_dir = config.data_dir / "stock_holdings"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def load_tracked_stocks(config: Config) -> list[TrackedStock]:
    """Load list of tracked stocks from YAML file."""
    path = get_tracked_stocks_path(config)
    if not path.exists():
        return []

    with open(path) as f:
        data = yaml.safe_load(f) or {}

    stocks_data = data.get("stocks", [])
    return [
        TrackedStock(
            ticker=s["ticker"],
            cusip=s["cusip"],
            name=s["name"],
            added_at=s.get("added_at", ""),
            quarters_stored=s.get("quarters_stored", 0),
            total_holders=s.get("total_holders", 0),
        )
        for s in stocks_data
    ]


def save_tracked_stocks(config: Config, stocks: list[TrackedStock]) -> None:
    """Save list of tracked stocks to YAML file."""
    path = get_tracked_stocks_path(config)

    data = {
        "stocks": [
            {
                "ticker": s.ticker,
                "cusip": s.cusip,
                "name": s.name,
                "added_at": s.added_at,
                "quarters_stored": s.quarters_stored,
                "total_holders": s.total_holders,
            }
            for s in stocks
        ]
    }

    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def get_tracked_stock(ticker: str, config: Config) -> TrackedStock | None:
    """Get a specific tracked stock by ticker."""
    stocks = load_tracked_stocks(config)
    ticker_upper = ticker.upper()
    for stock in stocks:
        if stock.ticker.upper() == ticker_upper:
            return stock
    return None


def add_tracked_stock(
    ticker: str,
    cusip: str,
    name: str,
    config: Config,
) -> TrackedStock:
    """Add a new stock to the tracked list.

    Returns the new TrackedStock object.
    """
    # Validate ticker for safe path usage
    safe_ticker = _validate_path_component(ticker, "ticker")

    stocks = load_tracked_stocks(config)

    # Check if already tracked
    for s in stocks:
        if s.ticker.upper() == safe_ticker:
            raise ValueError(f"{ticker} is already being tracked")

    # Create new tracked stock
    stock = TrackedStock(
        ticker=safe_ticker,
        cusip=cusip,
        name=name,
        added_at=datetime.utcnow().isoformat(),
        quarters_stored=0,
        total_holders=0,
    )

    stocks.append(stock)
    save_tracked_stocks(config, stocks)

    # Create data directory for this stock
    stock_dir = get_stock_data_dir(config) / safe_ticker
    stock_dir.mkdir(parents=True, exist_ok=True)

    return stock


def remove_tracked_stock(ticker: str, config: Config) -> int:
    """Remove a stock from tracking and delete its data.

    Returns the number of bytes freed.
    """
    # Validate ticker for safe path usage
    safe_ticker = _validate_path_component(ticker, "ticker")

    stocks = load_tracked_stocks(config)

    # Find and remove the stock
    new_stocks = [s for s in stocks if s.ticker.upper() != safe_ticker]
    if len(new_stocks) == len(stocks):
        raise ValueError(f"{ticker} is not being tracked")

    save_tracked_stocks(config, new_stocks)

    # Delete data directory
    stock_dir = get_stock_data_dir(config) / safe_ticker
    bytes_freed = 0
    if stock_dir.exists():
        bytes_freed = sum(f.stat().st_size for f in stock_dir.rglob("*") if f.is_file())
        shutil.rmtree(stock_dir)

    return bytes_freed


def get_stock_holdings_path(ticker: str, quarter: str, config: Config) -> Path:
    """Get path to a stock's holdings JSON file for a quarter."""
    # Validate path components to prevent path traversal
    safe_ticker = _validate_path_component(ticker, "ticker")
    safe_quarter = _validate_path_component(quarter, "quarter")

    stock_dir = get_stock_data_dir(config) / safe_ticker
    stock_dir.mkdir(parents=True, exist_ok=True)
    return stock_dir / f"{safe_quarter}.json"


def save_stock_holdings(
    ticker: str,
    quarter: str,
    holdings: list[HoldingRecord],
    config: Config,
) -> int:
    """Save holdings data for a stock/quarter.

    Returns bytes written.
    """
    path = get_stock_holdings_path(ticker, quarter, config)

    # Convert to serializable dicts
    data = {
        "ticker": ticker.upper(),
        "quarter": quarter,
        "saved_at": datetime.utcnow().isoformat(),
        "holder_count": len(holdings),
        "holdings": [asdict(h) for h in holdings],
    }

    content = json.dumps(data, indent=2)
    path.write_text(content)

    # Update tracked stock metadata
    _update_stock_metadata(ticker, config)

    return len(content.encode("utf-8"))


def load_stock_holdings(
    ticker: str,
    quarter: str,
    config: Config,
) -> list[HoldingRecord] | None:
    """Load holdings data for a stock/quarter.

    Returns None if not found.
    """
    path = get_stock_holdings_path(ticker, quarter, config)
    if not path.exists():
        return None

    with open(path) as f:
        data = json.load(f)

    return [
        HoldingRecord(
            accession_number=h["accession_number"],
            filer_cik=h["filer_cik"],
            filer_name=h["filer_name"],
            cusip=h["cusip"],
            issuer_name=h["issuer_name"],
            title_of_class=h["title_of_class"],
            value_thousands=h["value_thousands"],
            value_usd=h["value_usd"],
            shares=h["shares"],
            shares_type=h["shares_type"],
            put_call=h.get("put_call"),
            investment_discretion=h["investment_discretion"],
            voting_sole=h["voting_sole"],
            voting_shared=h["voting_shared"],
            voting_none=h["voting_none"],
            report_period=h["report_period"],
        )
        for h in data["holdings"]
    ]


def get_stock_quarters(ticker: str, config: Config) -> list[str]:
    """Get list of quarters that have data for a stock."""
    # Validate ticker for safe path usage
    safe_ticker = _validate_path_component(ticker, "ticker")

    stock_dir = get_stock_data_dir(config) / safe_ticker
    if not stock_dir.exists():
        return []

    quarters = []
    for path in stock_dir.glob("*.json"):
        quarter = path.stem
        quarters.append(quarter)

    return sorted(quarters, reverse=True)


def get_stock_storage_bytes(ticker: str, config: Config) -> int:
    """Get total storage used by a stock in bytes."""
    # Validate ticker for safe path usage
    safe_ticker = _validate_path_component(ticker, "ticker")

    stock_dir = get_stock_data_dir(config) / safe_ticker
    if not stock_dir.exists():
        return 0

    return sum(f.stat().st_size for f in stock_dir.rglob("*") if f.is_file())


def get_total_stock_storage(config: Config) -> dict:
    """Get total storage used by all tracked stocks.

    Returns dict with total_bytes, stock_count, and per_stock breakdown.
    """
    stocks = load_tracked_stocks(config)
    total_bytes = 0
    breakdown = {}

    for stock in stocks:
        bytes_used = get_stock_storage_bytes(stock.ticker, config)
        breakdown[stock.ticker] = bytes_used
        total_bytes += bytes_used

    return {
        "total_bytes": total_bytes,
        "stock_count": len(stocks),
        "breakdown": breakdown,
    }


def _update_stock_metadata(ticker: str, config: Config) -> None:
    """Update metadata for a tracked stock after data changes."""
    stocks = load_tracked_stocks(config)
    ticker_upper = ticker.upper()

    for stock in stocks:
        if stock.ticker.upper() == ticker_upper:
            quarters = get_stock_quarters(ticker, config)
            stock.quarters_stored = len(quarters)

            # Count unique holders across all quarters
            all_holders = set()
            for quarter in quarters:
                holdings = load_stock_holdings(ticker, quarter, config)
                if holdings:
                    for h in holdings:
                        all_holders.add(h.filer_cik)
            stock.total_holders = len(all_holders)
            break

    save_tracked_stocks(config, stocks)


def format_bytes(num_bytes: int) -> str:
    """Format bytes as human-readable string."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    else:
        return f"{num_bytes / 1024 / 1024:.1f} MB"
