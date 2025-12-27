"""Cross-fund universe report generator."""

from collections import defaultdict
from datetime import datetime

from ..analysis.clustering import assign_cluster
from ..analysis.diff import compute_all_diffs
from ..config import Config
from ..storage.database import Database
from .fund_report import _format_value, _format_weight, _period_to_quarter, _format_issuer_with_option, _format_holding_with_option


def generate_universe_report(
    db: Database,
    fund_ids: list[int],
    fund_names: list[str],
    config: Config,
) -> str:
    """
    Generate a cross-fund comparison report.

    Args:
        db: Database instance
        fund_ids: List of fund IDs to compare
        fund_names: Corresponding fund names
        config: Configuration

    Returns:
        Markdown report as string
    """
    if not fund_ids:
        return "# Universe Report\n\nNo funds specified."

    lines: list[str] = []
    lines.append("# 13F Universe Report")
    lines.append("")
    lines.append(f"**Funds Analyzed:** {', '.join(fund_names)}")
    lines.append(f"**Generated:** {datetime.utcnow().isoformat()}")
    lines.append("")

    # Collect data for each fund
    fund_data: dict[int, dict] = {}
    for fund_id, fund_name in zip(fund_ids, fund_names):
        filings = db.get_filings_for_fund(fund_id, periods=1)
        if not filings:
            continue

        filing = filings[0]
        holdings = db.get_holdings_for_filing(filing.id)
        total_value = sum(h.value_usd for h in holdings)

        diffs = compute_all_diffs(db, fund_id, fund_name, config)
        latest_diff = diffs[0] if diffs else None

        fund_data[fund_id] = {
            "name": fund_name,
            "filing": filing,
            "holdings": holdings,
            "total_value": total_value,
            "diff": latest_diff,
            "holdings_by_key": {f"{h.cusip}|{h.put_call or ''}": h for h in holdings},
            "options": [h for h in holdings if h.put_call],
        }

    if not fund_data:
        return "# Universe Report\n\nNo filing data available for specified funds."

    # Portfolio Overview
    lines.append("## Portfolio Overview")
    lines.append("")
    lines.append("| Fund | Total Value | Positions | Top 5 Conc. | Period |")
    lines.append("|------|-------------|-----------|-------------|--------|")

    for fund_id, data in fund_data.items():
        top5_conc = data["diff"].concentration_top5 if data["diff"] else 0
        quarter = _period_to_quarter(data["filing"].period_of_report)
        lines.append(
            f"| {data['name']} | {_format_value(data['total_value'])} | "
            f"{len(data['holdings'])} | {_format_weight(top5_conc)} | {quarter} |"
        )

    lines.append("")

    # Options Summary
    all_options = []
    for fund_id, data in fund_data.items():
        for h in data["options"]:
            weight = h.value_usd / data["total_value"] if data["total_value"] else 0
            all_options.append((data["name"], h, weight))

    if all_options:
        lines.append("## Options Positions")
        lines.append("")
        lines.append("*PUT and CALL options held by funds*")
        lines.append("")
        lines.append("| Fund | Issuer | Type | Value | Weight | Contracts |")
        lines.append("|------|--------|------|-------|--------|-----------|")
        all_options.sort(key=lambda x: x[1].value_usd, reverse=True)
        for fund_name, h, weight in all_options[:20]:
            lines.append(
                f"| {fund_name} | {h.issuer_name} | **{h.put_call.upper()}** | "
                f"{_format_value(h.value_usd)} | {_format_weight(weight)} | {h.shares_or_principal:,} |"
            )
        lines.append("")

    # Overlapping Holdings
    lines.append("## Overlapping Holdings")
    lines.append("")
    lines.append("*Holdings present in multiple funds*")
    lines.append("")

    # Find overlaps using key that includes put_call
    holding_funds: dict[str, list[tuple[int, str, int, float, str | None]]] = defaultdict(list)
    for fund_id, data in fund_data.items():
        for h in data["holdings"]:
            weight = h.value_usd / data["total_value"] if data["total_value"] else 0
            key = f"{h.cusip}|{h.put_call or ''}"
            holding_funds[key].append((fund_id, data["name"], h.value_usd, weight, h.put_call))

    # Filter to overlaps (2+ funds)
    overlaps = [(key, funds) for key, funds in holding_funds.items() if len(funds) >= 2]
    overlaps.sort(key=lambda x: sum(f[2] for f in x[1]), reverse=True)  # Sort by total value

    if overlaps[:20]:
        # Get issuer names and put_call
        key_to_info: dict[str, tuple[str, str | None]] = {}
        for fund_id, data in fund_data.items():
            for h in data["holdings"]:
                key = f"{h.cusip}|{h.put_call or ''}"
                key_to_info[key] = (h.issuer_name, h.put_call)

        lines.append("| Issuer | CUSIP | # Funds | Total Value | Funds |")
        lines.append("|--------|-------|---------|-------------|-------|")

        for key, funds in overlaps[:20]:
            issuer, put_call = key_to_info.get(key, (key.split("|")[0], None))
            cusip = key.split("|")[0]
            issuer_display = _format_issuer_with_option(issuer, put_call)
            total_val = sum(f[2] for f in funds)
            fund_list = ", ".join(f"{f[1]} ({_format_weight(f[3])})" for f in funds)
            lines.append(
                f"| {issuer_display} | {cusip} | {len(funds)} | {_format_value(total_val)} | {fund_list} |"
            )
    else:
        lines.append("*No overlapping holdings found.*")

    lines.append("")

    # Shared Adds
    lines.append("## Shared Adds (This Quarter)")
    lines.append("")
    lines.append("*Positions that multiple funds increased*")
    lines.append("")

    # Find shared adds using key with put_call
    add_funds: dict[str, list[tuple[str, int, float]]] = defaultdict(list)
    for fund_id, data in fund_data.items():
        if not data["diff"]:
            continue
        for pos in data["diff"].top_adds_by_value + data["diff"].new_positions:
            key = f"{pos.cusip}|{pos.put_call or ''}"
            add_funds[key].append((data["name"], pos.delta_value_usd, pos.portfolio_impact or 0))

    shared_adds = [(key, funds) for key, funds in add_funds.items() if len(funds) >= 2]
    shared_adds.sort(key=lambda x: sum(f[1] for f in x[1]), reverse=True)

    if shared_adds[:10]:
        key_to_info: dict[str, tuple[str, str | None]] = {}
        for fund_id, data in fund_data.items():
            if data["diff"]:
                for pos in data["diff"].new_positions + data["diff"].increased:
                    key = f"{pos.cusip}|{pos.put_call or ''}"
                    key_to_info[key] = (pos.issuer_name, pos.put_call)

        lines.append("| Issuer | # Funds | Total Δ$ | Funds Adding |")
        lines.append("|--------|---------|----------|--------------|")

        for key, funds in shared_adds[:10]:
            issuer, put_call = key_to_info.get(key, (key.split("|")[0], None))
            issuer_display = _format_issuer_with_option(issuer, put_call)
            total_delta = sum(f[1] for f in funds)
            fund_list = ", ".join(f"{f[0]} (+{_format_value(f[1])})" for f in funds)
            lines.append(f"| {issuer_display} | {len(funds)} | +{_format_value(total_delta)} | {fund_list} |")
    else:
        lines.append("*No shared adds found.*")

    lines.append("")

    # Divergent Bets
    lines.append("## Divergent Bets")
    lines.append("")
    lines.append("*Positions where funds are moving in opposite directions*")
    lines.append("")

    # Find divergent bets using key with put_call
    position_changes: dict[str, dict[str, tuple[str, int]]] = defaultdict(dict)
    for fund_id, data in fund_data.items():
        if not data["diff"]:
            continue
        for pos in data["diff"].increased + data["diff"].new_positions:
            key = f"{pos.cusip}|{pos.put_call or ''}"
            position_changes[key][data["name"]] = ("ADD", pos.delta_value_usd)
        for pos in data["diff"].decreased + data["diff"].sold_out:
            key = f"{pos.cusip}|{pos.put_call or ''}"
            position_changes[key][data["name"]] = ("CUT", pos.delta_value_usd)

    divergent = []
    for key, fund_changes in position_changes.items():
        adds = [(f, d) for f, (t, d) in fund_changes.items() if t == "ADD"]
        cuts = [(f, d) for f, (t, d) in fund_changes.items() if t == "CUT"]
        if adds and cuts:
            divergent.append((key, adds, cuts))

    divergent.sort(key=lambda x: abs(sum(a[1] for a in x[1])) + abs(sum(c[1] for c in x[2])), reverse=True)

    if divergent[:10]:
        key_to_info: dict[str, tuple[str, str | None]] = {}
        for fund_id, data in fund_data.items():
            if data["diff"]:
                for pos in (
                    data["diff"].new_positions
                    + data["diff"].increased
                    + data["diff"].decreased
                    + data["diff"].sold_out
                ):
                    key = f"{pos.cusip}|{pos.put_call or ''}"
                    key_to_info[key] = (pos.issuer_name, pos.put_call)

        lines.append("| Issuer | Adding | Cutting |")
        lines.append("|--------|--------|---------|")

        for key, adds, cuts in divergent[:10]:
            issuer, put_call = key_to_info.get(key, (key.split("|")[0], None))
            issuer_display = _format_issuer_with_option(issuer, put_call)
            add_str = ", ".join(f"{f} (+{_format_value(d)})" for f, d in adds)
            cut_str = ", ".join(f"{f} ({_format_value(d)})" for f, d in cuts)
            lines.append(f"| {issuer_display} | {add_str} | {cut_str} |")
    else:
        lines.append("*No divergent bets found.*")

    lines.append("")

    # Common Starter Probes
    lines.append("## Common Starter Probes")
    lines.append("")
    lines.append("*New small positions opened by multiple funds*")
    lines.append("")

    starter_funds: dict[str, list[tuple[str, int, float]]] = defaultdict(list)
    for fund_id, data in fund_data.items():
        if not data["diff"]:
            continue
        for pos in data["diff"].new_starters:
            key = f"{pos.cusip}|{pos.put_call or ''}"
            starter_funds[key].append((data["name"], pos.now_value_usd or 0, pos.now_weight or 0))

    common_starters = [(key, funds) for key, funds in starter_funds.items() if len(funds) >= 2]
    common_starters.sort(key=lambda x: len(x[1]), reverse=True)

    if common_starters[:10]:
        key_to_info: dict[str, tuple[str, str | None]] = {}
        for fund_id, data in fund_data.items():
            if data["diff"]:
                for pos in data["diff"].new_starters:
                    key = f"{pos.cusip}|{pos.put_call or ''}"
                    key_to_info[key] = (pos.issuer_name, pos.put_call)

        lines.append("| Issuer | # Funds | Funds |")
        lines.append("|--------|---------|-------|")

        for key, funds in common_starters[:10]:
            issuer, put_call = key_to_info.get(key, (key.split("|")[0], None))
            issuer_display = _format_issuer_with_option(issuer, put_call)
            fund_list = ", ".join(f"{f[0]} ({_format_weight(f[2])})" for f in funds)
            lines.append(f"| {issuer_display} | {len(funds)} | {fund_list} |")
    else:
        lines.append("*No common starter probes found.*")

    lines.append("")

    # Concentration Comparison
    lines.append("## Concentration Comparison")
    lines.append("")
    lines.append("| Fund | Top 5 | Top 10 | Herfindahl | Positions |")
    lines.append("|------|-------|--------|------------|-----------|")

    for fund_id, data in fund_data.items():
        if data["diff"]:
            lines.append(
                f"| {data['name']} | {_format_weight(data['diff'].concentration_top5)} | "
                f"{_format_weight(data['diff'].concentration_top10)} | "
                f"{data['diff'].herfindahl_index:.4f} | {data['diff'].position_count_now} |"
            )

    lines.append("")

    # Cluster Exposure Comparison
    lines.append("## Cluster Exposure Comparison")
    lines.append("")

    # Compute cluster weights for each fund
    all_clusters = set()
    fund_clusters: dict[str, dict[str, float]] = {}

    for fund_id, data in fund_data.items():
        cluster_values: dict[str, int] = defaultdict(int)
        for h in data["holdings"]:
            cluster = assign_cluster(h.issuer_name)
            cluster_values[cluster] += h.value_usd
            all_clusters.add(cluster)

        fund_clusters[data["name"]] = {
            c: v / data["total_value"] if data["total_value"] else 0
            for c, v in cluster_values.items()
        }

    # Build comparison table
    sorted_clusters = sorted(all_clusters - {"Other"})
    if "Other" in all_clusters:
        sorted_clusters.append("Other")

    header = "| Cluster | " + " | ".join(fund_names) + " |"
    separator = "|---------|" + "|".join(["-------"] * len(fund_names)) + "|"
    lines.append(header)
    lines.append(separator)

    for cluster in sorted_clusters[:15]:  # Top 15 clusters
        weights = [fund_clusters.get(name, {}).get(cluster, 0) for name in fund_names]
        if max(weights) < 0.01:  # Skip clusters with <1% exposure in all funds
            continue
        weight_strs = [_format_weight(w) for w in weights]
        lines.append(f"| {cluster} | " + " | ".join(weight_strs) + " |")

    lines.append("")

    # Footer
    lines.append("---")
    lines.append(f"*Report generated: {datetime.utcnow().isoformat()}*")

    return "\n".join(lines)
