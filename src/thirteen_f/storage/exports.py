"""Export data to CSV and Parquet formats."""

from pathlib import Path

import pandas as pd

from .database import Database
from .models import FilingRecord


def holdings_to_dataframe(db: Database, filing_id: int) -> pd.DataFrame:
    """Convert holdings for a filing to a DataFrame."""
    holdings = db.get_holdings_for_filing(filing_id)
    if not holdings:
        return pd.DataFrame()

    return pd.DataFrame(
        [
            {
                "issuer_name": h.issuer_name,
                "title_of_class": h.title_of_class,
                "cusip": h.cusip,
                "figi": h.figi,
                "value_thousands": h.value_thousands,
                "value_usd": h.value_usd,
                "shares_or_principal": h.shares_or_principal,
                "shares_type": h.shares_type,
                "put_call": h.put_call,
                "investment_discretion": h.investment_discretion,
                "voting_sole": h.voting_sole,
                "voting_shared": h.voting_shared,
                "voting_none": h.voting_none,
            }
            for h in holdings
        ]
    )


def export_to_csv(db: Database, filing: FilingRecord, output_path: Path) -> Path:
    """
    Export holdings for a filing to CSV.

    Args:
        db: Database instance
        filing: The filing to export
        output_path: Directory to write the CSV file

    Returns:
        Path to the created CSV file
    """
    df = holdings_to_dataframe(db, filing.id)
    output_path.mkdir(parents=True, exist_ok=True)

    filename = f"{filing.period_of_report}_{filing.accession_number.replace('-', '_')}.csv"
    csv_path = output_path / filename
    df.to_csv(csv_path, index=False)
    return csv_path


def export_to_parquet(db: Database, filing: FilingRecord, output_path: Path) -> Path:
    """
    Export holdings for a filing to Parquet.

    Args:
        db: Database instance
        filing: The filing to export
        output_path: Directory to write the Parquet file

    Returns:
        Path to the created Parquet file
    """
    df = holdings_to_dataframe(db, filing.id)
    output_path.mkdir(parents=True, exist_ok=True)

    filename = f"{filing.period_of_report}_{filing.accession_number.replace('-', '_')}.parquet"
    parquet_path = output_path / filename
    df.to_parquet(parquet_path, index=False)
    return parquet_path


def export_all_holdings_to_csv(db: Database, fund_id: int, output_path: Path) -> Path:
    """
    Export all holdings for a fund across all periods to a single CSV.

    Args:
        db: Database instance
        fund_id: The fund ID
        output_path: Directory to write the CSV file

    Returns:
        Path to the created CSV file
    """
    filings = db.get_filings_for_fund(fund_id)
    all_data = []

    for filing in filings:
        holdings = db.get_holdings_for_filing(filing.id)
        for h in holdings:
            all_data.append(
                {
                    "period_of_report": filing.period_of_report,
                    "filing_date": filing.filing_date,
                    "accession_number": filing.accession_number,
                    "issuer_name": h.issuer_name,
                    "title_of_class": h.title_of_class,
                    "cusip": h.cusip,
                    "figi": h.figi,
                    "value_thousands": h.value_thousands,
                    "value_usd": h.value_usd,
                    "shares_or_principal": h.shares_or_principal,
                    "shares_type": h.shares_type,
                    "put_call": h.put_call,
                    "investment_discretion": h.investment_discretion,
                    "voting_sole": h.voting_sole,
                    "voting_shared": h.voting_shared,
                    "voting_none": h.voting_none,
                }
            )

    df = pd.DataFrame(all_data)
    output_path.mkdir(parents=True, exist_ok=True)
    csv_path = output_path / "all_holdings.csv"
    df.to_csv(csv_path, index=False)
    return csv_path
