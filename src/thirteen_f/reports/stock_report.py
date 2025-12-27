"""Stock-centric report generator."""

from collections import defaultdict
from datetime import datetime

from ..config import Config, load_funds
from ..sec.quarterly_data import HoldingRecord
from ..storage.stock_storage import (
    get_stock_quarters,
    load_stock_holdings,
    load_tracked_stocks,
)


def _format_value(value: int) -> str:
    """Format a USD value for display."""
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    elif value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    elif value >= 1_000:
        return f"${value / 1_000:.0f}K"
    else:
        return f"${value}"


def _format_weight(weight: float) -> str:
    """Format a weight as percentage."""
    return f"{weight * 100:.2f}%"


def _format_shares(shares: int) -> str:
    """Format shares with K/M suffix."""
    if shares >= 1_000_000:
        return f"{shares / 1_000_000:.1f}M"
    elif shares >= 1_000:
        return f"{shares / 1_000:.0f}K"
    else:
        return str(shares)


def _format_change_pct(old_value: int, new_value: int) -> str:
    """Format percentage change."""
    if old_value == 0:
        return "NEW"
    change = (new_value - old_value) / old_value * 100
    if change >= 0:
        return f"+{change:.0f}%"
    else:
        return f"{change:.0f}%"


def _quarter_to_display(quarter: str) -> str:
    """Convert 2024Q3 to Q3 2024."""
    year = quarter[:4]
    q = quarter[4:]
    return f"{q} {year}"


def _format_position_type(put_call: str | None) -> str:
    """Format position type with emoji indicator."""
    if not put_call:
        return "Equity"
    elif put_call.upper() == "PUT":
        return "🔻 PUT"
    elif put_call.upper() == "CALL":
        return "📈 CALL"
    else:
        return put_call.upper()


def _load_passive_ciks(config: Config) -> set[str]:
    """Load CIKs of passive funds to exclude."""
    passive_path = config.data_dir / "passive_funds.yaml"
    if not passive_path.exists():
        # Default passive fund CIKs
        return {
            "0000102909",  # Vanguard
            "0001364742",  # BlackRock
            "0000093751",  # State Street
            "0000315066",  # Fidelity
            "0000034066",  # Capital Group
        }

    import yaml

    with open(passive_path) as f:
        data = yaml.safe_load(f) or {}

    return set(pf.get("cik", "") for pf in data.get("passive_funds", []))


def _get_tracked_fund_ciks(config: Config) -> dict[str, str]:
    """Get mapping of CIK -> fund name for tracked funds."""
    funds = load_funds(config)
    return {f.cik: f.display_name for f in funds}


def generate_stock_report(
    ticker: str,
    cusip: str,
    issuer_name: str,
    holdings: list[HoldingRecord],
    config: Config,
    exclude_passive: bool = True,
) -> str:
    """Generate a report showing institutional holders of a stock.

    Args:
        ticker: Stock ticker symbol
        cusip: CUSIP of the stock
        issuer_name: Name of the issuer
        holdings: List of holdings for the stock
        config: Config object
        exclude_passive: Whether to exclude passive funds

    Returns:
        Markdown report string
    """
    lines: list[str] = []

    # Load filters
    passive_ciks = _load_passive_ciks(config) if exclude_passive else set()
    tracked_fund_ciks = _get_tracked_fund_ciks(config)

    # Filter out passive funds
    active_holdings = [
        h for h in holdings if h.filer_cik not in passive_ciks
    ]

    # Header
    lines.append(f"# {issuer_name} ({ticker})")
    lines.append("")
    lines.append(f"**CUSIP:** {cusip}")
    lines.append(f"**Holders (>$50M, excl. passive):** {len(active_holdings)}")

    if holdings:
        total_value = sum(h.value_usd for h in active_holdings)
        lines.append(f"**Total Active Holdings:** {_format_value(total_value)}")
        lines.append(f"**Report Period:** {holdings[0].report_period}")

    lines.append("")

    if not active_holdings:
        lines.append("*No active institutional holders found above threshold.*")
        return "\n".join(lines)

    # Top Holders Table
    lines.append("## Top Institutional Holders")
    lines.append("")
    lines.append("| Holder | Value | Shares | Position |")
    lines.append("|--------|-------|--------|----------|")

    for h in active_holdings[:30]:  # Top 30
        # Determine holder name (highlight tracked funds)
        if h.filer_cik in tracked_fund_ciks:
            holder_name = f"**{tracked_fund_ciks[h.filer_cik]}**"
        else:
            holder_name = h.filer_name[:40]

        pos_type = _format_position_type(h.put_call)

        lines.append(
            f"| {holder_name} | {_format_value(h.value_usd)} | "
            f"{_format_shares(h.shares)} | {pos_type} |"
        )

    lines.append("")

    # Tracked Funds Section
    tracked_holdings = [h for h in active_holdings if h.filer_cik in tracked_fund_ciks]
    if tracked_holdings:
        lines.append("## Your Tracked Funds")
        lines.append("")
        lines.append("| Fund | Value | Shares | Position |")
        lines.append("|------|-------|--------|----------|")

        for h in tracked_holdings:
            fund_name = tracked_fund_ciks[h.filer_cik]
            pos_type = _format_position_type(h.put_call)
            lines.append(
                f"| {fund_name} | {_format_value(h.value_usd)} | "
                f"{_format_shares(h.shares)} | {pos_type} |"
            )
        lines.append("")

    # Summary Stats
    lines.append("## Summary")
    lines.append("")

    # Count by position type
    equity_count = len([h for h in active_holdings if not h.put_call])
    put_count = len([h for h in active_holdings if h.put_call and h.put_call.upper() == "PUT"])
    call_count = len([h for h in active_holdings if h.put_call and h.put_call.upper() == "CALL"])

    lines.append(f"- **Equity Holders:** {equity_count}")
    if put_count > 0:
        lines.append(f"- **🔻 PUT Holders (bearish):** {put_count}")
    if call_count > 0:
        lines.append(f"- **📈 CALL Holders (bullish):** {call_count}")

    # Count tracked funds
    hedge_count = len(tracked_holdings)
    if hedge_count > 0:
        lines.append(f"- **Your Tracked Funds Holding:** {hedge_count}")

    if passive_ciks:
        passive_count = len([h for h in holdings if h.filer_cik in passive_ciks])
        lines.append(f"- **Passive Funds (excluded):** {passive_count}")

    lines.append("")

    # Footer
    lines.append("---")
    lines.append(f"*Report generated: {datetime.utcnow().isoformat()}*")

    return "\n".join(lines)


def generate_stock_history_report(
    ticker: str,
    cusip: str,
    issuer_name: str,
    config: Config,
    exclude_passive: bool = True,
) -> str:
    """Generate a quarterly history report for a stock.

    Shows who's buying and selling over time.
    """
    lines: list[str] = []

    # Load data
    quarters = get_stock_quarters(ticker, config)
    if not quarters:
        return f"# {issuer_name} ({ticker})\n\nNo historical data found."

    passive_ciks = _load_passive_ciks(config) if exclude_passive else set()
    tracked_fund_ciks = _get_tracked_fund_ciks(config)

    # Load holdings for all quarters
    holdings_by_quarter: dict[str, list[HoldingRecord]] = {}
    for quarter in quarters:
        holdings = load_stock_holdings(ticker, quarter, config)
        if holdings:
            # Filter passive
            holdings_by_quarter[quarter] = [
                h for h in holdings if h.filer_cik not in passive_ciks
            ]

    if not holdings_by_quarter:
        return f"# {issuer_name} ({ticker})\n\nNo historical data found."

    # Header
    lines.append(f"# {issuer_name} ({ticker}) - Quarterly History")
    lines.append("")
    lines.append(f"**CUSIP:** {cusip}")
    lines.append(f"**Quarters:** {len(quarters)}")
    lines.append("")

    # Movement Analysis
    if len(quarters) >= 2:
        lines.append("## Movement Analysis")
        lines.append("")

        latest_q = quarters[0]
        prev_q = quarters[1]

        latest = {h.filer_cik: h for h in holdings_by_quarter.get(latest_q, [])}
        prev = {h.filer_cik: h for h in holdings_by_quarter.get(prev_q, [])}

        # New positions
        new_ciks = set(latest.keys()) - set(prev.keys())
        exited_ciks = set(prev.keys()) - set(latest.keys())

        # Increased/decreased
        increased = []
        decreased = []
        for cik in latest.keys() & prev.keys():
            delta_shares = latest[cik].shares - prev[cik].shares
            delta_value = latest[cik].value_usd - prev[cik].value_usd
            if delta_shares > 0:
                increased.append((latest[cik], delta_shares, delta_value))
            elif delta_shares < 0:
                decreased.append((latest[cik], delta_shares, delta_value))

        lines.append(f"**{_quarter_to_display(prev_q)} → {_quarter_to_display(latest_q)}:**")
        lines.append("")

        if new_ciks:
            new_names = [latest[cik].filer_name[:30] for cik in list(new_ciks)[:5]]
            lines.append(f"- **New Positions ({len(new_ciks)}):** {', '.join(new_names)}")

        if exited_ciks:
            exited_names = [prev[cik].filer_name[:30] for cik in list(exited_ciks)[:5]]
            lines.append(f"- **Exited ({len(exited_ciks)}):** {', '.join(exited_names)}")

        if increased:
            increased.sort(key=lambda x: x[2], reverse=True)
            top_increases = [
                f"{h.filer_name[:20]} (+{_format_shares(delta)})"
                for h, delta, _ in increased[:5]
            ]
            lines.append(f"- **Added Shares ({len(increased)}):** {', '.join(top_increases)}")

        if decreased:
            decreased.sort(key=lambda x: x[2])
            top_decreases = [
                f"{h.filer_name[:20]} ({_format_shares(delta)})"
                for h, delta, _ in decreased[:5]
            ]
            lines.append(f"- **Trimmed Shares ({len(decreased)}):** {', '.join(top_decreases)}")

        lines.append("")

    # Tracked Funds Activity
    lines.append("## Tracked Funds Activity")
    lines.append("")

    # Build history for tracked funds
    tracked_history: dict[str, dict[str, HoldingRecord]] = defaultdict(dict)
    for quarter, holdings in holdings_by_quarter.items():
        for h in holdings:
            if h.filer_cik in tracked_fund_ciks:
                fund_name = tracked_fund_ciks[h.filer_cik]
                tracked_history[fund_name][quarter] = h

    if tracked_history:
        # Header row - show value and position type for each quarter
        header = "| Fund | " + " | ".join(_quarter_to_display(q) for q in quarters[:4]) + " |"
        separator = "|------|" + "|".join(["------"] * min(4, len(quarters))) + "|"
        lines.append(header)
        lines.append(separator)

        for fund_name, quarter_data in sorted(tracked_history.items()):
            row = f"| {fund_name} |"
            for quarter in quarters[:4]:
                if quarter in quarter_data:
                    h = quarter_data[quarter]
                    # Include position type indicator
                    if h.put_call:
                        pos_indicator = " 🔻" if h.put_call.upper() == "PUT" else " 📈"
                    else:
                        pos_indicator = ""
                    row += f" {_format_value(h.value_usd)}{pos_indicator} |"
                else:
                    row += " — |"
            lines.append(row)

        lines.append("")
    else:
        lines.append("*None of your tracked funds hold this stock.*")
        lines.append("")

    # Quarterly Detail
    lines.append("## Quarterly Holdings")
    lines.append("")

    for quarter in quarters[:4]:
        holdings = holdings_by_quarter.get(quarter, [])
        if not holdings:
            continue

        total_value = sum(h.value_usd for h in holdings)
        lines.append(f"### {_quarter_to_display(quarter)}")
        lines.append("")
        lines.append(f"*{len(holdings)} holders, {_format_value(total_value)} total*")
        lines.append("")

        lines.append("| Holder | Value | Shares | Position |")
        lines.append("|--------|-------|--------|----------|")

        for h in holdings[:15]:  # Top 15 per quarter
            name = h.filer_name[:35]
            if h.filer_cik in tracked_fund_ciks:
                name = f"**{tracked_fund_ciks[h.filer_cik]}**"
            pos_type = _format_position_type(h.put_call)
            lines.append(
                f"| {name} | {_format_value(h.value_usd)} | {_format_shares(h.shares)} | {pos_type} |"
            )

        lines.append("")

    # Footer
    lines.append("---")
    lines.append(f"*Report generated: {datetime.utcnow().isoformat()}*")

    return "\n".join(lines)
