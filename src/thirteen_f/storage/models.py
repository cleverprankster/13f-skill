"""Data models for storage."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class FundRecord:
    """A fund stored in the database."""

    id: int | None
    display_name: str
    cik: str
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class FilingRecord:
    """A 13F filing stored in the database."""

    id: int | None
    fund_id: int
    accession_number: str
    form_type: str
    filing_date: str
    period_of_report: str
    is_amendment: bool
    total_value_usd: int
    position_count: int
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class HoldingRecord:
    """A holding stored in the database."""

    id: int | None
    filing_id: int
    issuer_name: str
    title_of_class: str
    cusip: str
    figi: str | None
    value_thousands: int
    value_usd: int
    shares_or_principal: int
    shares_type: str
    put_call: str | None
    investment_discretion: str
    voting_sole: int
    voting_shared: int
    voting_none: int
