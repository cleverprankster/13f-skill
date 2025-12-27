"""Fund report generator."""

from datetime import datetime
from pathlib import Path

from ..analysis.clustering import assign_cluster, cluster_holdings, summarize_clusters
from ..analysis.diff import QuarterDiff, compute_all_diffs
from ..analysis.signals import Signal, detect_signals, detect_starter_to_scale
from ..config import Config
from ..storage.database import Database
from ..storage.models import FilingRecord, HoldingRecord


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


def _format_weight(weight: float | None) -> str:
    """Format a weight as percentage."""
    if weight is None:
        return "N/A"
    return f"{weight * 100:.2f}%"


def _format_change(delta: int) -> str:
    """Format a value change with sign."""
    if delta >= 0:
        return f"+{_format_value(delta)}"
    else:
        return f"-{_format_value(abs(delta))}"


def _format_pct_change(rate: float | None) -> str:
    """Format a percentage change."""
    if rate is None:
        return "N/A"
    if rate >= 0:
        return f"+{rate * 100:.1f}%"
    else:
        return f"{rate * 100:.1f}%"


def _format_issuer_with_option(issuer_name: str, put_call: str | None) -> str:
    """Format issuer name with PUT/CALL suffix if applicable."""
    if put_call:
        return f"{issuer_name} ({put_call.upper()})"
    return issuer_name


def _format_holding_with_option(holding: HoldingRecord) -> str:
    """Format holding name with PUT/CALL suffix if applicable."""
    if holding.put_call:
        return f"{holding.issuer_name} ({holding.put_call.upper()})"
    return holding.issuer_name


def generate_fund_report(
    db: Database,
    fund_id: int,
    fund_name: str,
    config: Config,
    period: str | None = None,
) -> str:
    """
    Generate a comprehensive analysis report for a fund.

    Args:
        db: Database instance
        fund_id: Fund ID
        fund_name: Fund display name
        config: Configuration
        period: Specific period to report on (default: latest)

    Returns:
        Markdown report as string
    """
    filings = db.get_filings_for_fund(fund_id)
    if not filings:
        return f"# {fund_name}\n\nNo filings found."

    # Get the target filing
    if period:
        filing = db.get_filing_by_period(fund_id, period)
        if not filing:
            return f"# {fund_name}\n\nNo filing found for period {period}."
    else:
        filing = filings[0]

    holdings = db.get_holdings_for_filing(filing.id)
    total_value = sum(h.value_usd for h in holdings)

    # Compute diffs
    diffs = compute_all_diffs(db, fund_id, fund_name, config)
    latest_diff = diffs[0] if diffs else None

    # Detect signals
    signals = detect_signals(diffs)
    starter_to_scale = detect_starter_to_scale(diffs)

    # Build report
    lines: list[str] = []

    # Header
    quarter = _period_to_quarter(filing.period_of_report)
    lines.append(f"# {fund_name} - 13F Analysis ({quarter})")
    lines.append("")
    lines.append(f"**Period of Report:** {filing.period_of_report}")
    lines.append(f"**Filing Date:** {filing.filing_date}")
    lines.append(f"**Form Type:** {filing.form_type}")
    if filing.is_amendment:
        lines.append("**Note:** This is an amended filing")
    lines.append(f"**Total Portfolio Value:** {_format_value(total_value)}")
    lines.append(f"**Number of Positions:** {len(holdings)}")
    lines.append("")

    # Portfolio Map
    lines.append("## Portfolio Map")
    lines.append("")

    # Top 10 Holdings
    lines.append("### Top 10 Holdings")
    lines.append("")
    lines.append("| Rank | Issuer | CUSIP | Value | Weight | Cluster |")
    lines.append("|------|--------|-------|-------|--------|---------|")

    for i, h in enumerate(holdings[:10], 1):
        weight = h.value_usd / total_value if total_value else 0
        cluster = assign_cluster(h.issuer_name)
        delta_str = ""
        if latest_diff:
            for pos in latest_diff.increased + latest_diff.decreased + latest_diff.new_positions:
                if pos.cusip == h.cusip and pos.put_call == h.put_call:
                    delta_str = f" ({_format_change(pos.delta_value_usd)})"
                    break
        issuer_display = _format_holding_with_option(h)
        lines.append(
            f"| {i} | {issuer_display}{delta_str} | {h.cusip} | "
            f"{_format_value(h.value_usd)} | {_format_weight(weight)} | {cluster} |"
        )

    lines.append("")

    # Options Positions Section
    options_holdings = [h for h in holdings if h.put_call]
    if options_holdings:
        lines.append("### Options Positions")
        lines.append("")
        lines.append("| Issuer | Type | Value | Weight | Shares/Contracts |")
        lines.append("|--------|------|-------|--------|------------------|")
        for h in sorted(options_holdings, key=lambda x: x.value_usd, reverse=True):
            weight = h.value_usd / total_value if total_value else 0
            lines.append(
                f"| {h.issuer_name} | **{h.put_call.upper()}** | "
                f"{_format_value(h.value_usd)} | {_format_weight(weight)} | "
                f"{h.shares_or_principal:,} |"
            )
        lines.append("")

    # Holdings #11-30 by Cluster
    if len(holdings) > 10:
        lines.append("### Holdings #11-30 by Cluster")
        lines.append("")

        mid_holdings = [
            (_format_holding_with_option(h), h.value_usd, h.value_usd / total_value if total_value else 0)
            for h in holdings[10:30]
        ]
        cluster_summary = summarize_clusters([(h.issuer_name, h.value_usd, h.value_usd / total_value if total_value else 0) for h in holdings[10:30]])

        for cluster, value, weight, count in cluster_summary:
            holdings_in_cluster = [h[0] for h in mid_holdings if assign_cluster(h[0].split(" (")[0]) == cluster]
            names = ", ".join(holdings_in_cluster[:5])
            if len(holdings_in_cluster) > 5:
                names += f" +{len(holdings_in_cluster) - 5} more"
            lines.append(f"- **{cluster}** ({count} positions, {_format_weight(weight)}): {names}")

        lines.append("")

    # Notable Small Positions
    lines.append("### Notable Small Positions")
    lines.append("")
    lines.append("*Positions with weight ≤0.25% that show interesting activity*")
    lines.append("")

    small_positions = []
    if latest_diff:
        # Collect small positions with activity
        for pos in latest_diff.new_starters:
            small_positions.append((pos, "NEW"))
        for pos in latest_diff.increased_starters:
            small_positions.append((pos, "INCREASED"))
        for pos in latest_diff.decreased:
            if pos.is_starter:
                small_positions.append((pos, "TRIMMED"))

    # Sort by value descending and take top 20
    small_positions.sort(key=lambda x: x[0].now_value_usd or 0, reverse=True)

    if small_positions[:20]:
        lines.append("| Issuer | CUSIP | Value | Weight | Status | Δ Value |")
        lines.append("|--------|-------|-------|--------|--------|---------|")
        for pos, status in small_positions[:20]:
            issuer_display = _format_issuer_with_option(pos.issuer_name, pos.put_call)
            lines.append(
                f"| {issuer_display} | {pos.cusip} | {_format_value(pos.now_value_usd or 0)} | "
                f"{_format_weight(pos.now_weight)} | {status} | {_format_change(pos.delta_value_usd)} |"
            )
    else:
        lines.append("*No notable small position activity this quarter.*")

    lines.append("")

    # Changes Section
    if latest_diff:
        prev_quarter = _period_to_quarter(latest_diff.period_from)
        curr_quarter = _period_to_quarter(latest_diff.period_to)
        lines.append(f"## Changes ({prev_quarter} → {curr_quarter})")
        lines.append("")

        # Summary stats
        lines.append("### Summary")
        lines.append("")
        lines.append(f"- **New Positions:** {len(latest_diff.new_positions)}")
        lines.append(f"- **Positions Exited:** {len(latest_diff.sold_out)}")
        lines.append(f"- **Positions Increased:** {len(latest_diff.increased)}")
        lines.append(f"- **Positions Decreased:** {len(latest_diff.decreased)}")
        lines.append(f"- **Gross Adds:** {_format_value(latest_diff.gross_adds_value)}")
        lines.append(f"- **Gross Cuts:** {_format_value(latest_diff.gross_cuts_value)}")
        lines.append("")

        # By Dollar Value
        lines.append("### By Dollar Value")
        lines.append("")
        lines.append("**Top Adds:**")
        lines.append("")
        if latest_diff.top_adds_by_value:
            lines.append("| Issuer | Prev Value | Now Value | Δ Value | Classification |")
            lines.append("|--------|------------|-----------|---------|----------------|")
            for pos in latest_diff.top_adds_by_value[:5]:
                classification = _classify_position(pos)
                issuer_display = _format_issuer_with_option(pos.issuer_name, pos.put_call)
                lines.append(
                    f"| {issuer_display} | {_format_value(pos.prev_value_usd or 0)} | "
                    f"{_format_value(pos.now_value_usd or 0)} | {_format_change(pos.delta_value_usd)} | "
                    f"{classification} |"
                )
        lines.append("")

        lines.append("**Top Cuts:**")
        lines.append("")
        if latest_diff.top_cuts_by_value:
            lines.append("| Issuer | Prev Value | Now Value | Δ Value | Classification |")
            lines.append("|--------|------------|-----------|---------|----------------|")
            for pos in latest_diff.top_cuts_by_value[:5]:
                classification = _classify_position(pos)
                issuer_display = _format_issuer_with_option(pos.issuer_name, pos.put_call)
                lines.append(
                    f"| {issuer_display} | {_format_value(pos.prev_value_usd or 0)} | "
                    f"{_format_value(pos.now_value_usd or 0)} | {_format_change(pos.delta_value_usd)} | "
                    f"{classification} |"
                )
        lines.append("")

        # By Growth Rate
        lines.append("### By Growth Rate")
        lines.append("")
        lines.append("*Excludes new positions (infinite growth)*")
        lines.append("")
        lines.append("**Top Adds:**")
        lines.append("")
        if latest_diff.top_adds_by_growth_rate:
            lines.append("| Issuer | Prev → Now | Growth Rate | Portfolio Impact |")
            lines.append("|--------|------------|-------------|------------------|")
            for pos in latest_diff.top_adds_by_growth_rate[:5]:
                issuer_display = _format_issuer_with_option(pos.issuer_name, pos.put_call)
                lines.append(
                    f"| {issuer_display} | {_format_value(pos.prev_value_usd or 0)} → "
                    f"{_format_value(pos.now_value_usd or 0)} | {_format_pct_change(pos.growth_rate)} | "
                    f"{_format_pct_change(pos.portfolio_impact)} |"
                )
        lines.append("")

        lines.append("**Top Cuts:**")
        lines.append("")
        if latest_diff.top_cuts_by_growth_rate:
            lines.append("| Issuer | Prev → Now | Growth Rate | Portfolio Impact |")
            lines.append("|--------|------------|-------------|------------------|")
            for pos in latest_diff.top_cuts_by_growth_rate[:5]:
                issuer_display = _format_issuer_with_option(pos.issuer_name, pos.put_call)
                lines.append(
                    f"| {issuer_display} | {_format_value(pos.prev_value_usd or 0)} → "
                    f"{_format_value(pos.now_value_usd or 0)} | {_format_pct_change(pos.growth_rate)} | "
                    f"{_format_pct_change(pos.portfolio_impact)} |"
                )
        lines.append("")

        # By Portfolio Impact
        lines.append("### By Portfolio Impact")
        lines.append("")
        lines.append("**Top Adds:**")
        lines.append("")
        if latest_diff.top_adds_by_portfolio_impact:
            lines.append("| Issuer | Prev Weight → Now Weight | Portfolio Impact |")
            lines.append("|--------|--------------------------|------------------|")
            for pos in latest_diff.top_adds_by_portfolio_impact[:5]:
                issuer_display = _format_issuer_with_option(pos.issuer_name, pos.put_call)
                lines.append(
                    f"| {issuer_display} | {_format_weight(pos.prev_weight)} → "
                    f"{_format_weight(pos.now_weight)} | {_format_pct_change(pos.portfolio_impact)} |"
                )
        lines.append("")

        lines.append("**Top Cuts:**")
        lines.append("")
        if latest_diff.top_cuts_by_portfolio_impact:
            lines.append("| Issuer | Prev Weight → Now Weight | Portfolio Impact |")
            lines.append("|--------|--------------------------|------------------|")
            for pos in latest_diff.top_cuts_by_portfolio_impact[:5]:
                issuer_display = _format_issuer_with_option(pos.issuer_name, pos.put_call)
                lines.append(
                    f"| {issuer_display} | {_format_weight(pos.prev_weight)} → "
                    f"{_format_weight(pos.now_weight)} | {_format_pct_change(pos.portfolio_impact)} |"
                )
        lines.append("")

    # Thesis Signals
    lines.append("## Thesis Signals")
    lines.append("")
    lines.append("*Pattern-based signals detected across the last 4 quarters*")
    lines.append("")

    if signals:
        for signal in signals:
            strength_emoji = {"strong": "🔴", "moderate": "🟡", "weak": "⚪"}.get(
                signal.strength, "⚪"
            )
            lines.append(f"### {strength_emoji} {signal.signal_type.replace('_', ' ').title()}")
            lines.append("")
            lines.append(f"**Description:** {signal.description}")
            if signal.holdings:
                lines.append(f"**Holdings:** {', '.join(signal.holdings)}")
            lines.append(f"**Quarters:** {', '.join(_period_to_quarter(q) for q in signal.quarters)}")
            lines.append("")
    else:
        lines.append("*No significant signals detected.*")
        lines.append("")

    # Year-to-Date View
    if len(diffs) >= 2:
        oldest_diff = diffs[-1]
        lines.append("## Year-to-Date View")
        lines.append("")
        oldest_quarter = _period_to_quarter(oldest_diff.period_from)
        latest_quarter = _period_to_quarter(latest_diff.period_to) if latest_diff else "N/A"
        lines.append(f"*Comparing {oldest_quarter} to {latest_quarter}*")
        lines.append("")

        # Net new names
        all_new = set()
        all_exited = set()
        for diff in diffs:
            for pos in diff.new_positions:
                all_new.add(pos.issuer_name)
            for pos in diff.sold_out:
                all_exited.add(pos.issuer_name)

        lines.append(f"- **Net New Names:** {len(all_new)}")
        lines.append(f"- **Names Fully Exited:** {len(all_exited)}")
        lines.append("")

        # Starter to Scale
        if starter_to_scale:
            lines.append("### Starter → Scale Positions")
            lines.append("")
            lines.append("*Positions that started small and grew to meaningful size*")
            lines.append("")
            lines.append("| Issuer | Start Period | Start Value | Current Value | Growth |")
            lines.append("|--------|--------------|-------------|---------------|--------|")
            for pos in starter_to_scale[:10]:
                growth_str = (
                    f"+{pos['growth_rate'] * 100:.0f}%"
                    if pos["growth_rate"] != float("inf")
                    else "NEW"
                )
                lines.append(
                    f"| {pos['issuer_name']} | {_period_to_quarter(pos['start_period'])} | "
                    f"{_format_value(pos['start_value'])} | {_format_value(pos['current_value'])} | "
                    f"{growth_str} |"
                )
            lines.append("")

    # Diagnostics
    if latest_diff:
        lines.append("## Portfolio Diagnostics")
        lines.append("")
        lines.append(f"- **Top 5 Concentration:** {_format_weight(latest_diff.concentration_top5)}")
        lines.append(f"- **Top 10 Concentration:** {_format_weight(latest_diff.concentration_top10)}")
        lines.append(f"- **Herfindahl Index:** {latest_diff.herfindahl_index:.4f}")
        lines.append(f"- **Position Count:** {latest_diff.position_count_now}")
        lines.append("")

    # Footer
    lines.append("---")
    lines.append(f"*Report generated: {datetime.utcnow().isoformat()}*")

    return "\n".join(lines)


def _period_to_quarter(period: str) -> str:
    """Convert YYYY-MM-DD to YYYYQN format."""
    try:
        date = datetime.strptime(period, "%Y-%m-%d")
        quarter = (date.month - 1) // 3 + 1
        return f"{date.year}Q{quarter}"
    except ValueError:
        return period


def _classify_position(pos) -> str:
    """Classify a position change."""
    if pos.change_type == "NEW":
        if pos.is_starter:
            return "STARTER"
        return "NEW"
    elif pos.change_type == "EXIT":
        return "EXIT"
    elif pos.change_type == "INCREASE":
        if pos.is_starter and pos.growth_rate and pos.growth_rate >= 1.0:
            return "SCALE-UP"
        return "ADD"
    elif pos.change_type == "DECREASE":
        return "TRIM"
    return pos.change_type
