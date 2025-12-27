"""Thesis signal detection across multiple quarters."""

from dataclasses import dataclass, field

from .diff import QuarterDiff


@dataclass
class Signal:
    """A detected thesis signal."""

    signal_type: str
    description: str
    holdings: list[str]  # List of issuer names
    quarters: list[str]  # List of periods involved
    strength: str  # "weak", "moderate", "strong"
    details: dict = field(default_factory=dict)


def detect_signals(diffs: list[QuarterDiff]) -> list[Signal]:
    """
    Detect thesis signals across multiple quarters.

    Args:
        diffs: List of QuarterDiff objects, ordered from most recent to oldest

    Returns:
        List of detected Signal objects
    """
    if not diffs:
        return []

    signals: list[Signal] = []

    # Build position history: cusip -> list of (period, value, weight, change_type)
    position_history: dict[str, list[tuple[str, int | None, float | None, str]]] = {}

    for diff in reversed(diffs):  # Process oldest to newest
        period = diff.period_to

        # Track all positions in this period
        all_positions = (
            diff.new_positions
            + diff.increased
            + diff.decreased
            + diff.unchanged
            + diff.sold_out
        )

        for pos in all_positions:
            key = pos.cusip
            if key not in position_history:
                position_history[key] = []
            position_history[key].append(
                (period, pos.now_value_usd, pos.now_weight, pos.change_type)
            )

    # Get issuer names mapping
    cusip_to_name: dict[str, str] = {}
    for diff in diffs:
        for pos in diff.new_positions + diff.increased + diff.decreased:
            cusip_to_name[pos.cusip] = pos.issuer_name

    # 1. Consistent Accumulator: increased 3+ consecutive quarters
    for cusip, history in position_history.items():
        consecutive_increases = 0
        max_consecutive = 0
        increase_quarters = []

        for period, value, weight, change_type in history:
            if change_type == "INCREASE":
                consecutive_increases += 1
                increase_quarters.append(period)
            else:
                max_consecutive = max(max_consecutive, consecutive_increases)
                consecutive_increases = 0
                increase_quarters = []

        max_consecutive = max(max_consecutive, consecutive_increases)

        if max_consecutive >= 3:
            name = cusip_to_name.get(cusip, cusip)
            strength = "strong" if max_consecutive >= 4 else "moderate"
            signals.append(
                Signal(
                    signal_type="consistent_accumulator",
                    description=f"{name} increased {max_consecutive} consecutive quarters",
                    holdings=[name],
                    quarters=increase_quarters[-max_consecutive:],
                    strength=strength,
                    details={"consecutive_increases": max_consecutive},
                )
            )

    # 2. Build then Trim: increased 2+ quarters, then decreased
    for cusip, history in position_history.items():
        if len(history) < 3:
            continue

        # Look for pattern: INCREASE, INCREASE, ..., DECREASE
        build_quarters = []
        in_build_phase = False

        for i, (period, value, weight, change_type) in enumerate(history):
            if change_type == "INCREASE":
                build_quarters.append(period)
                in_build_phase = True
            elif change_type == "DECREASE" and in_build_phase and len(build_quarters) >= 2:
                name = cusip_to_name.get(cusip, cusip)
                signals.append(
                    Signal(
                        signal_type="build_then_trim",
                        description=f"{name} built for {len(build_quarters)} quarters then trimmed",
                        holdings=[name],
                        quarters=build_quarters + [period],
                        strength="moderate",
                        details={"build_quarters": len(build_quarters)},
                    )
                )
                break
            else:
                build_quarters = []
                in_build_phase = False

    # 3. One-Quarter Probe: opened and closed within 2 quarters
    for cusip, history in position_history.items():
        for i, (period, value, weight, change_type) in enumerate(history):
            if change_type == "NEW":
                # Check if exited within next 2 quarters
                for j in range(i + 1, min(i + 3, len(history))):
                    if history[j][3] == "EXIT":
                        name = cusip_to_name.get(cusip, cusip)
                        quarters_held = j - i + 1
                        signals.append(
                            Signal(
                                signal_type="one_quarter_probe",
                                description=f"{name} opened and closed within {quarters_held} quarters",
                                holdings=[name],
                                quarters=[history[i][0], history[j][0]],
                                strength="weak",
                                details={"quarters_held": quarters_held},
                            )
                        )
                        break

    # 4. Concentration Shift: top-5 weight changed >5% between oldest and newest
    if len(diffs) >= 2:
        newest = diffs[0]
        oldest = diffs[-1]

        conc_change = abs(newest.concentration_top5 - oldest.concentration_top5)
        if conc_change >= 0.05:  # 5%
            direction = "increased" if newest.concentration_top5 > oldest.concentration_top5 else "decreased"
            signals.append(
                Signal(
                    signal_type="concentration_shift",
                    description=f"Top-5 concentration {direction} by {conc_change:.1%}",
                    holdings=[],
                    quarters=[oldest.period_to, newest.period_to],
                    strength="moderate" if conc_change < 0.10 else "strong",
                    details={
                        "concentration_change": conc_change,
                        "direction": direction,
                        "from": oldest.concentration_top5,
                        "to": newest.concentration_top5,
                    },
                )
            )

    # 5. Theme Emergence: 3+ new starters with same cluster in a quarter
    from .clustering import assign_cluster

    for diff in diffs:
        cluster_starters: dict[str, list[str]] = {}
        for pos in diff.new_starters:
            cluster = assign_cluster(pos.issuer_name)
            if cluster != "Other":
                if cluster not in cluster_starters:
                    cluster_starters[cluster] = []
                cluster_starters[cluster].append(pos.issuer_name)

        for cluster, starters in cluster_starters.items():
            if len(starters) >= 3:
                signals.append(
                    Signal(
                        signal_type="theme_emergence",
                        description=f"{len(starters)} new starters in {cluster}",
                        holdings=starters,
                        quarters=[diff.period_to],
                        strength="moderate" if len(starters) < 5 else "strong",
                        details={"cluster": cluster, "count": len(starters)},
                    )
                )

    # Sort by strength (strong > moderate > weak)
    strength_order = {"strong": 0, "moderate": 1, "weak": 2}
    signals.sort(key=lambda s: strength_order.get(s.strength, 3))

    return signals


def detect_starter_to_scale(diffs: list[QuarterDiff]) -> list[dict]:
    """
    Find positions that started as starters and grew to meaningful size.

    Returns:
        List of dicts with position details
    """
    if len(diffs) < 2:
        return []

    # Track positions that were ever starters
    starter_positions: dict[str, tuple[str, str, int, float]] = {}  # cusip -> (name, period, value, weight)

    for diff in reversed(diffs):
        for pos in diff.new_starters:
            if pos.cusip not in starter_positions:
                starter_positions[pos.cusip] = (
                    pos.issuer_name,
                    diff.period_to,
                    pos.now_value_usd or 0,
                    pos.now_weight or 0,
                )

    # Check current state
    latest_diff = diffs[0]
    all_current = {
        pos.cusip: pos
        for pos in (
            latest_diff.new_positions
            + latest_diff.increased
            + latest_diff.decreased
            + latest_diff.unchanged
        )
    }

    scaled_positions = []
    for cusip, (name, start_period, start_value, start_weight) in starter_positions.items():
        if cusip in all_current:
            current = all_current[cusip]
            now_weight = current.now_weight or 0
            now_value = current.now_value_usd or 0

            # Consider "scaled" if weight is now > 0.5% or value > $20M
            if now_weight > 0.005 or now_value > 20_000_000:
                growth = (now_value - start_value) / start_value if start_value > 0 else float("inf")
                scaled_positions.append(
                    {
                        "issuer_name": name,
                        "cusip": cusip,
                        "start_period": start_period,
                        "start_value": start_value,
                        "start_weight": start_weight,
                        "current_value": now_value,
                        "current_weight": now_weight,
                        "growth_rate": growth,
                    }
                )

    # Sort by growth rate descending
    scaled_positions.sort(key=lambda x: x["growth_rate"], reverse=True)
    return scaled_positions
