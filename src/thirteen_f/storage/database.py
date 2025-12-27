"""SQLite database management."""

import json
import sqlite3
from pathlib import Path

from ..config import Config
from ..edgar.parser import Holding
from .models import FilingRecord, FundRecord, HoldingRecord

SCHEMA_VERSION = 1

SCHEMA = """
-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

-- Funds table
CREATE TABLE IF NOT EXISTS funds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name TEXT UNIQUE NOT NULL,
    cik TEXT NOT NULL,
    tags TEXT,
    created_at TEXT NOT NULL
);

-- Filings table
CREATE TABLE IF NOT EXISTS filings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_id INTEGER NOT NULL REFERENCES funds(id),
    accession_number TEXT UNIQUE NOT NULL,
    form_type TEXT NOT NULL,
    filing_date TEXT NOT NULL,
    period_of_report TEXT NOT NULL,
    is_amendment INTEGER NOT NULL,
    total_value_usd INTEGER,
    position_count INTEGER,
    created_at TEXT NOT NULL,
    UNIQUE(fund_id, period_of_report, accession_number)
);

-- Holdings table
CREATE TABLE IF NOT EXISTS holdings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filing_id INTEGER NOT NULL REFERENCES filings(id),
    issuer_name TEXT NOT NULL,
    title_of_class TEXT NOT NULL,
    cusip TEXT NOT NULL,
    figi TEXT,
    value_thousands INTEGER NOT NULL,
    value_usd INTEGER NOT NULL,
    shares_or_principal INTEGER NOT NULL,
    shares_type TEXT NOT NULL,
    put_call TEXT,
    investment_discretion TEXT,
    voting_sole INTEGER,
    voting_shared INTEGER,
    voting_none INTEGER,
    UNIQUE(filing_id, cusip, title_of_class, put_call, shares_type)
);

-- Optional enrichment table
CREATE TABLE IF NOT EXISTS cusip_enrichment (
    cusip TEXT PRIMARY KEY,
    ticker TEXT,
    company_name TEXT,
    sector TEXT,
    updated_at TEXT
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_filings_fund_id ON filings(fund_id);
CREATE INDEX IF NOT EXISTS idx_filings_period ON filings(period_of_report);
CREATE INDEX IF NOT EXISTS idx_holdings_filing_id ON holdings(filing_id);
CREATE INDEX IF NOT EXISTS idx_holdings_cusip ON holdings(cusip);
"""


class Database:
    """SQLite database manager."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.db_path = config.db_path
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> None:
        """Open database connection and ensure schema exists."""
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self) -> None:
        """Run schema migrations."""
        cursor = self._conn.cursor()

        # Check if schema_version table exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        if not cursor.fetchone():
            # Fresh database - create all tables
            cursor.executescript(SCHEMA)
            cursor.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
            self._conn.commit()
            return

        # Check current version
        cursor.execute("SELECT MAX(version) FROM schema_version")
        current_version = cursor.fetchone()[0] or 0

        if current_version < SCHEMA_VERSION:
            # Run migrations as needed
            # For now, just update version
            cursor.execute(
                "INSERT OR REPLACE INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,)
            )
            self._conn.commit()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.connect()
        return self._conn

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "Database":
        self.connect()
        return self

    def __exit__(self, *args) -> None:
        self.close()

    # Fund operations

    def get_fund_by_name(self, display_name: str) -> FundRecord | None:
        """Get a fund by display name."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM funds WHERE display_name = ?", (display_name,))
        row = cursor.fetchone()
        if not row:
            return None
        return FundRecord(
            id=row["id"],
            display_name=row["display_name"],
            cik=row["cik"],
            tags=json.loads(row["tags"]) if row["tags"] else [],
            created_at=row["created_at"],
        )

    def get_fund_by_cik(self, cik: str) -> FundRecord | None:
        """Get a fund by CIK."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM funds WHERE cik = ?", (cik,))
        row = cursor.fetchone()
        if not row:
            return None
        return FundRecord(
            id=row["id"],
            display_name=row["display_name"],
            cik=row["cik"],
            tags=json.loads(row["tags"]) if row["tags"] else [],
            created_at=row["created_at"],
        )

    def upsert_fund(self, fund: FundRecord) -> int:
        """Insert or update a fund, returning its ID."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO funds (display_name, cik, tags, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(display_name) DO UPDATE SET
                cik = excluded.cik,
                tags = excluded.tags
            RETURNING id
            """,
            (fund.display_name, fund.cik, json.dumps(fund.tags), fund.created_at),
        )
        result = cursor.fetchone()[0]
        self.conn.commit()
        return result

    def get_all_funds(self) -> list[FundRecord]:
        """Get all funds."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM funds ORDER BY display_name")
        return [
            FundRecord(
                id=row["id"],
                display_name=row["display_name"],
                cik=row["cik"],
                tags=json.loads(row["tags"]) if row["tags"] else [],
                created_at=row["created_at"],
            )
            for row in cursor.fetchall()
        ]

    def delete_fund(self, display_name: str) -> bool:
        """Delete a fund and all its filings/holdings."""
        fund = self.get_fund_by_name(display_name)
        if not fund:
            return False

        cursor = self.conn.cursor()
        # Delete holdings for all filings of this fund
        cursor.execute(
            """
            DELETE FROM holdings WHERE filing_id IN (
                SELECT id FROM filings WHERE fund_id = ?
            )
            """,
            (fund.id,),
        )
        # Delete filings
        cursor.execute("DELETE FROM filings WHERE fund_id = ?", (fund.id,))
        # Delete fund
        cursor.execute("DELETE FROM funds WHERE id = ?", (fund.id,))
        self.conn.commit()
        return True

    # Filing operations

    def get_filing(self, accession_number: str) -> FilingRecord | None:
        """Get a filing by accession number."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM filings WHERE accession_number = ?", (accession_number,))
        row = cursor.fetchone()
        if not row:
            return None
        return FilingRecord(
            id=row["id"],
            fund_id=row["fund_id"],
            accession_number=row["accession_number"],
            form_type=row["form_type"],
            filing_date=row["filing_date"],
            period_of_report=row["period_of_report"],
            is_amendment=bool(row["is_amendment"]),
            total_value_usd=row["total_value_usd"],
            position_count=row["position_count"],
            created_at=row["created_at"],
        )

    def filing_exists(self, accession_number: str) -> bool:
        """Check if a filing already exists."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT 1 FROM filings WHERE accession_number = ?", (accession_number,)
        )
        return cursor.fetchone() is not None

    def upsert_filing(self, filing: FilingRecord) -> int:
        """Insert or update a filing, returning its ID."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO filings (
                fund_id, accession_number, form_type, filing_date,
                period_of_report, is_amendment, total_value_usd, position_count, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(accession_number) DO UPDATE SET
                total_value_usd = excluded.total_value_usd,
                position_count = excluded.position_count
            RETURNING id
            """,
            (
                filing.fund_id,
                filing.accession_number,
                filing.form_type,
                filing.filing_date,
                filing.period_of_report,
                int(filing.is_amendment),
                filing.total_value_usd,
                filing.position_count,
                filing.created_at,
            ),
        )
        result = cursor.fetchone()[0]
        self.conn.commit()
        return result

    def get_filings_for_fund(
        self, fund_id: int, periods: int | None = None
    ) -> list[FilingRecord]:
        """Get filings for a fund, ordered by period descending."""
        cursor = self.conn.cursor()
        query = """
            SELECT * FROM filings
            WHERE fund_id = ?
            ORDER BY period_of_report DESC
        """
        if periods:
            # Use parameterized query to prevent SQL injection
            query += " LIMIT ?"
            cursor.execute(query, (fund_id, int(periods)))
        else:
            cursor.execute(query, (fund_id,))
        return [
            FilingRecord(
                id=row["id"],
                fund_id=row["fund_id"],
                accession_number=row["accession_number"],
                form_type=row["form_type"],
                filing_date=row["filing_date"],
                period_of_report=row["period_of_report"],
                is_amendment=bool(row["is_amendment"]),
                total_value_usd=row["total_value_usd"],
                position_count=row["position_count"],
                created_at=row["created_at"],
            )
            for row in cursor.fetchall()
        ]

    def get_latest_filing_for_fund(self, fund_id: int) -> FilingRecord | None:
        """Get the most recent filing for a fund."""
        filings = self.get_filings_for_fund(fund_id, periods=1)
        return filings[0] if filings else None

    # Holdings operations

    def insert_holdings(self, filing_id: int, holdings: list[Holding]) -> int:
        """Insert holdings for a filing, returning count inserted."""
        cursor = self.conn.cursor()
        count = 0
        for h in holdings:
            try:
                cursor.execute(
                    """
                    INSERT INTO holdings (
                        filing_id, issuer_name, title_of_class, cusip, figi,
                        value_thousands, value_usd, shares_or_principal, shares_type,
                        put_call, investment_discretion, voting_sole, voting_shared, voting_none
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        filing_id,
                        h.issuer_name,
                        h.title_of_class,
                        h.cusip,
                        h.figi,
                        h.value_thousands,
                        h.value_usd,
                        h.shares_or_principal,
                        h.shares_type,
                        h.put_call,
                        h.investment_discretion,
                        h.voting_sole,
                        h.voting_shared,
                        h.voting_none,
                    ),
                )
                if cursor.rowcount > 0:
                    count += 1
            except sqlite3.IntegrityError:
                pass
        self.conn.commit()
        return count

    def get_holdings_for_filing(self, filing_id: int) -> list[HoldingRecord]:
        """Get all holdings for a filing."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM holdings WHERE filing_id = ? ORDER BY value_usd DESC",
            (filing_id,),
        )
        return [
            HoldingRecord(
                id=row["id"],
                filing_id=row["filing_id"],
                issuer_name=row["issuer_name"],
                title_of_class=row["title_of_class"],
                cusip=row["cusip"],
                figi=row["figi"],
                value_thousands=row["value_thousands"],
                value_usd=row["value_usd"],
                shares_or_principal=row["shares_or_principal"],
                shares_type=row["shares_type"],
                put_call=row["put_call"],
                investment_discretion=row["investment_discretion"],
                voting_sole=row["voting_sole"],
                voting_shared=row["voting_shared"],
                voting_none=row["voting_none"],
            )
            for row in cursor.fetchall()
        ]

    # Query helpers

    def get_filing_by_period(self, fund_id: int, period: str) -> FilingRecord | None:
        """Get a filing for a specific period."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT * FROM filings
            WHERE fund_id = ? AND period_of_report = ?
            ORDER BY filing_date DESC
            LIMIT 1
            """,
            (fund_id, period),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return FilingRecord(
            id=row["id"],
            fund_id=row["fund_id"],
            accession_number=row["accession_number"],
            form_type=row["form_type"],
            filing_date=row["filing_date"],
            period_of_report=row["period_of_report"],
            is_amendment=bool(row["is_amendment"]),
            total_value_usd=row["total_value_usd"],
            position_count=row["position_count"],
            created_at=row["created_at"],
        )

    def execute_query(self, query: str, params: tuple = ()) -> list[sqlite3.Row]:
        """Execute a raw SQL query."""
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()
