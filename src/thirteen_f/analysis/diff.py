"""Quarter-over-quarter diff engine."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..config import Config
from ..storage.database import Database
from ..storage.models import FilingRecord, HoldingRecord


@dataclass
class PositionDiff:
    """Diff for a single position between two quarters."""

    cusip: str
    issuer_name: str
    title_of_class: str

    # Values
    prev_value_usd: int | None
    now_value_usd: int | None
    delta_value_usd: int

    # Shares
    prev_shares: int | None
    now_shares: int | None
    delta_shares: int

    # Weights (as decimals, e.g., 0.05 = 5%)
    prev_weight: float | None
    now_weight: float | None

    # % metrics
    growth_rate: float | None  # (now - prev) / prev, None if prev=0
    portfolio_impact: float | None  # (now - prev) / total_portfolio_prev

    # Classification
    change_type: str  # "NEW", "EXIT", "INCREASE", "DECREASE", "UNCHANGED"
    is_starter: bool  # weight 0.01%-0.25% OR value < $5M

    # Options
    put_call: str | None = None  # "Put", "Call", or None for shares

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class QuarterDiff:
    """Complete diff between two quarters for a fund."""

    fund_id: int
    fund_name: str
    period_from: str
    period_to: str

    total_portfolio_prev: int
    total_portfolio_now: int

    # All positions by category
    new_positions: list[PositionDiff] = field(default_factory=list)
    sold_out: list[PositionDiff] = field(default_factory=list)
    increased: list[PositionDiff] = field(default_factory=list)
    decreased: list[PositionDiff] = field(default_factory=list)
    unchanged: list[PositionDiff] = field(default_factory=list)

    # Ranked lists (top 10 each)
    top_adds_by_value: list[PositionDiff] = field(default_factory=list)
    top_cuts_by_value: list[PositionDiff] = field(default_factory=list)
    top_adds_by_growth_rate: list[PositionDiff] = field(default_factory=list)
    top_cuts_by_growth_rate: list[PositionDiff] = field(default_factory=list)
    top_adds_by_portfolio_impact: list[PositionDiff] = field(default_factory=list)
    top_cuts_by_portfolio_impact: list[PositionDiff] = field(default_factory=list)

    # Starters
    new_starters: list[PositionDiff] = field(default_factory=list)
    increased_starters: list[PositionDiff] = field(default_factory=list)

    # Diagnostics
    concentration_top5: float = 0.0
    concentration_top10: float = 0.0
    herfindahl_index: float = 0.0
    position_count_prev: int = 0
    position_count_now: int = 0
    gross_adds_value: int = 0
    gross_cuts_value: int = 0

    def to_dict(self) -> dict:
        """Convert to a JSON-serializable dict."""
        return {
            "fund_id": self.fund_id,
            "fund_name": self.fund_name,
            "period_from": self.period_from,
            "period_to": self.period_to,
            "total_portfolio_prev": self.total_portfolio_prev,
            "total_portfolio_now": self.total_portfolio_now,
            "new_positions": [p.to_dict() for p in self.new_positions],
            "sold_out": [p.to_dict() for p in self.sold_out],
            "increased": [p.to_dict() for p in self.increased],
            "decreased": [p.to_dict() for p in self.decreased],
            "top_adds_by_value": [p.to_dict() for p in self.top_adds_by_value],
            "top_cuts_by_value": [p.to_dict() for p in self.top_cuts_by_value],
            "top_adds_by_growth_rate": [p.to_dict() for p in self.top_adds_by_growth_rate],
            "top_cuts_by_growth_rate": [p.to_dict() for p in self.top_cuts_by_growth_rate],
            "top_adds_by_portfolio_impact": [p.to_dict() for p in self.top_adds_by_portfolio_impact],
            "top_cuts_by_portfolio_impact": [p.to_dict() for p in self.top_cuts_by_portfolio_impact],
            "new_starters": [p.to_dict() for p in self.new_starters],
            "increased_starters": [p.to_dict() for p in self.increased_starters],
            "concentration_top5": self.concentration_top5,
            "concentration_top10": self.concentration_top10,
            "herfindahl_index": self.herfindahl_index,
            "position_count_prev": self.position_count_prev,
            "position_count_now": self.position_count_now,
            "gross_adds_value": self.gross_adds_value,
            "gross_cuts_value": self.gross_cuts_value,
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    def save(self, path: Path) -> None:
        """Save to a JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json())


def _holding_key(h: HoldingRecord) -> str:
    """Generate a key for matching holdings across periods."""
    # Match on CUSIP + title + put/call to handle options correctly
    put_call = h.put_call or "NONE"
    return f"{h.cusip}|{h.title_of_class}|{put_call}"


def _is_starter(weight: float | None, value: int | None, config: Config) -> bool:
    """Determine if a position qualifies as a starter."""
    if value is not None and value < config.starter_value_threshold:
        return True
    if weight is not None:
        if config.starter_weight_min <= weight <= config.starter_weight_max:
            return True
    return False


def compute_quarter_diff(
    db: Database,
    fund_id: int,
    fund_name: str,
    filing_prev: FilingRecord,
    filing_now: FilingRecord,
    config: Config,
) -> QuarterDiff:
    """
    Compute the diff between two quarters.

    Args:
        db: Database instance
        fund_id: Fund ID
        fund_name: Fund display name
        filing_prev: Previous quarter's filing
        filing_now: Current quarter's filing
        config: Configuration

    Returns:
        QuarterDiff with all computed metrics
    """
    holdings_prev = db.get_holdings_for_filing(filing_prev.id)
    holdings_now = db.get_holdings_for_filing(filing_now.id)

    total_prev = sum(h.value_usd for h in holdings_prev)
    total_now = sum(h.value_usd for h in holdings_now)

    # Build lookup dicts
    prev_by_key = {_holding_key(h): h for h in holdings_prev}
    now_by_key = {_holding_key(h): h for h in holdings_now}

    all_keys = set(prev_by_key.keys()) | set(now_by_key.keys())

    diffs: list[PositionDiff] = []

    for key in all_keys:
        h_prev = prev_by_key.get(key)
        h_now = now_by_key.get(key)

        prev_value = h_prev.value_usd if h_prev else None
        now_value = h_now.value_usd if h_now else None
        prev_shares = h_prev.shares_or_principal if h_prev else None
        now_shares = h_now.shares_or_principal if h_now else None

        delta_value = (now_value or 0) - (prev_value or 0)
        delta_shares = (now_shares or 0) - (prev_shares or 0)

        prev_weight = (prev_value / total_prev) if prev_value and total_prev else None
        now_weight = (now_value / total_now) if now_value and total_now else None

        # Growth rate
        growth_rate = None
        if prev_value and prev_value > 0 and now_value is not None:
            growth_rate = (now_value - prev_value) / prev_value

        # Portfolio impact
        portfolio_impact = None
        if total_prev > 0:
            portfolio_impact = delta_value / total_prev

        # Classification
        if h_prev is None and h_now is not None:
            change_type = "NEW"
        elif h_prev is not None and h_now is None:
            change_type = "EXIT"
        elif delta_value > 0:
            change_type = "INCREASE"
        elif delta_value < 0:
            change_type = "DECREASE"
        else:
            change_type = "UNCHANGED"

        # Starter detection
        is_starter = _is_starter(now_weight, now_value, config)

        # Use the available holding for name/cusip
        ref = h_now or h_prev
        diff = PositionDiff(
            cusip=ref.cusip,
            issuer_name=ref.issuer_name,
            title_of_class=ref.title_of_class,
            prev_value_usd=prev_value,
            now_value_usd=now_value,
            delta_value_usd=delta_value,
            prev_shares=prev_shares,
            now_shares=now_shares,
            delta_shares=delta_shares,
            prev_weight=prev_weight,
            now_weight=now_weight,
            growth_rate=growth_rate,
            portfolio_impact=portfolio_impact,
            change_type=change_type,
            is_starter=is_starter,
            put_call=ref.put_call,
        )
        diffs.append(diff)

    # Categorize
    new_positions = [d for d in diffs if d.change_type == "NEW"]
    sold_out = [d for d in diffs if d.change_type == "EXIT"]
    increased = [d for d in diffs if d.change_type == "INCREASE"]
    decreased = [d for d in diffs if d.change_type == "DECREASE"]
    unchanged = [d for d in diffs if d.change_type == "UNCHANGED"]

    # Ranked lists (top 10)
    # Adds by value (positive delta)
    adds = [d for d in diffs if d.delta_value_usd > 0]
    cuts = [d for d in diffs if d.delta_value_usd < 0]

    top_adds_by_value = sorted(adds, key=lambda d: d.delta_value_usd, reverse=True)[:10]
    top_cuts_by_value = sorted(cuts, key=lambda d: d.delta_value_usd)[:10]

    # Adds/cuts by growth rate (exclude NEW positions for growth rate)
    adds_with_growth = [d for d in adds if d.growth_rate is not None and d.change_type != "NEW"]
    cuts_with_growth = [d for d in cuts if d.growth_rate is not None]

    top_adds_by_growth_rate = sorted(
        adds_with_growth, key=lambda d: d.growth_rate or 0, reverse=True
    )[:10]
    top_cuts_by_growth_rate = sorted(cuts_with_growth, key=lambda d: d.growth_rate or 0)[:10]

    # Adds/cuts by portfolio impact
    adds_with_impact = [d for d in adds if d.portfolio_impact is not None]
    cuts_with_impact = [d for d in cuts if d.portfolio_impact is not None]

    top_adds_by_portfolio_impact = sorted(
        adds_with_impact, key=lambda d: d.portfolio_impact or 0, reverse=True
    )[:10]
    top_cuts_by_portfolio_impact = sorted(
        cuts_with_impact, key=lambda d: d.portfolio_impact or 0
    )[:10]

    # Starters
    new_starters = [d for d in new_positions if d.is_starter]
    # Increased starters: growth_rate >= 100% OR portfolio_impact >= 0.05%
    increased_starters = [
        d
        for d in increased
        if d.is_starter
        and (
            (d.growth_rate is not None and d.growth_rate >= 1.0)
            or (d.portfolio_impact is not None and d.portfolio_impact >= 0.0005)
        )
    ]

    # Diagnostics
    # Concentration
    weights_now = sorted(
        [(h.value_usd / total_now) for h in holdings_now if total_now > 0], reverse=True
    )
    concentration_top5 = sum(weights_now[:5]) if len(weights_now) >= 5 else sum(weights_now)
    concentration_top10 = sum(weights_now[:10]) if len(weights_now) >= 10 else sum(weights_now)

    # Herfindahl index
    herfindahl = sum(w * w for w in weights_now) if weights_now else 0.0

    # Gross adds/cuts
    gross_adds = sum(d.delta_value_usd for d in adds)
    gross_cuts = sum(abs(d.delta_value_usd) for d in cuts)

    return QuarterDiff(
        fund_id=fund_id,
        fund_name=fund_name,
        period_from=filing_prev.period_of_report,
        period_to=filing_now.period_of_report,
        total_portfolio_prev=total_prev,
        total_portfolio_now=total_now,
        new_positions=new_positions,
        sold_out=sold_out,
        increased=increased,
        decreased=decreased,
        unchanged=unchanged,
        top_adds_by_value=top_adds_by_value,
        top_cuts_by_value=top_cuts_by_value,
        top_adds_by_growth_rate=top_adds_by_growth_rate,
        top_cuts_by_growth_rate=top_cuts_by_growth_rate,
        top_adds_by_portfolio_impact=top_adds_by_portfolio_impact,
        top_cuts_by_portfolio_impact=top_cuts_by_portfolio_impact,
        new_starters=new_starters,
        increased_starters=increased_starters,
        concentration_top5=concentration_top5,
        concentration_top10=concentration_top10,
        herfindahl_index=herfindahl,
        position_count_prev=len(holdings_prev),
        position_count_now=len(holdings_now),
        gross_adds_value=gross_adds,
        gross_cuts_value=gross_cuts,
    )


def compute_all_diffs(
    db: Database,
    fund_id: int,
    fund_name: str,
    config: Config,
) -> list[QuarterDiff]:
    """
    Compute diffs for all adjacent quarter pairs for a fund.

    Returns:
        List of QuarterDiff objects, ordered from most recent to oldest
    """
    filings = db.get_filings_for_fund(fund_id)
    if len(filings) < 2:
        return []

    diffs = []
    for i in range(len(filings) - 1):
        filing_now = filings[i]
        filing_prev = filings[i + 1]
        diff = compute_quarter_diff(db, fund_id, fund_name, filing_prev, filing_now, config)
        diffs.append(diff)

    return diffs
