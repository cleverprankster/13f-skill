"""SEC Form 13F quarterly data set download and parsing."""

import csv
import io
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx

from ..config import Config


# Base URL for SEC 13F data sets
SEC_DATA_URL = "https://www.sec.gov/files/structureddata/data/form-13f-data-sets"

# Mapping of reporting quarters to data set date ranges
# 13F filings are due 45 days after quarter end, so:
# Q1 (Mar 31) → filings due May 15 → data in Mar-May set
# Q2 (Jun 30) → filings due Aug 14 → data in Jun-Aug set
# Q3 (Sep 30) → filings due Nov 14 → data in Sep-Nov set
# Q4 (Dec 31) → filings due Feb 14 → data in Dec-Feb set
QUARTER_TO_DATE_RANGE = {
    # 2025 quarters (use new date range format)
    "2025Q3": "01sep2025-30nov2025",
    "2025Q2": "01jun2025-31aug2025",
    "2025Q1": "01mar2025-31may2025",
    # 2024 quarters
    "2024Q4": "01dec2024-28feb2025",
    "2024Q3": "01sep2024-30nov2024",
    "2024Q2": "01jun2024-31aug2024",
    "2024Q1": "01mar2024-31may2024",
    # 2023 quarters
    "2023Q4": "01dec2023-29feb2024",
    "2023Q3": "01sep2023-30nov2023",
    "2023Q2": "01jun2023-31aug2023",
    "2023Q1": "01mar2023-31may2023",
}

# Alternative format for older quarters
QUARTER_TO_LEGACY = {
    "2022Q4": "2022q4",
    "2022Q3": "2022q3",
    "2022Q2": "2022q2",
    "2022Q1": "2022q1",
}


@dataclass
class HoldingRecord:
    """A single holding from the 13F data set."""

    accession_number: str
    filer_cik: str
    filer_name: str
    cusip: str
    issuer_name: str
    title_of_class: str
    value_thousands: int
    value_usd: int
    shares: int
    shares_type: str  # SH or PRN
    put_call: str | None
    investment_discretion: str
    voting_sole: int
    voting_shared: int
    voting_none: int
    report_period: str  # e.g., "2024-09-30"


@dataclass
class QuarterlyDataSet:
    """Represents a downloaded and parsed quarterly data set."""

    quarter: str  # e.g., "2024Q3"
    holdings: list[HoldingRecord]
    filer_count: int
    total_holdings: int
    download_path: Path | None = None


def get_available_quarters() -> list[str]:
    """Return list of quarters that have data sets available.

    Returns most recent quarters first.
    """
    all_quarters = list(QUARTER_TO_DATE_RANGE.keys()) + list(QUARTER_TO_LEGACY.keys())
    return sorted(all_quarters, reverse=True)


def _quarter_to_url(quarter: str) -> str:
    """Convert a quarter string to the SEC download URL."""
    if quarter in QUARTER_TO_DATE_RANGE:
        date_range = QUARTER_TO_DATE_RANGE[quarter]
        return f"{SEC_DATA_URL}/{date_range}_form13f.zip"
    elif quarter in QUARTER_TO_LEGACY:
        legacy = QUARTER_TO_LEGACY[quarter]
        return f"{SEC_DATA_URL}/{legacy}_form13f.zip"
    else:
        raise ValueError(f"Unknown quarter: {quarter}")


def _quarter_to_report_period(quarter: str) -> str:
    """Convert quarter string to report period date.

    e.g., "2024Q3" -> "2024-09-30"
    """
    year = int(quarter[:4])
    q = int(quarter[-1])

    month_day = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}
    return f"{year}-{month_day[q]}"


def download_quarterly_data(
    quarter: str,
    config: Config,
    force: bool = False,
) -> Path:
    """Download SEC 13F quarterly data set.

    Args:
        quarter: Quarter string like "2024Q3"
        config: Config with cache directory
        force: Force re-download even if cached

    Returns:
        Path to downloaded zip file
    """
    cache_dir = config.cache_dir / "sec_quarterly"
    cache_dir.mkdir(parents=True, exist_ok=True)

    zip_path = cache_dir / f"{quarter}_form13f.zip"

    if zip_path.exists() and not force:
        return zip_path

    url = _quarter_to_url(quarter)

    print(f"Downloading {quarter} data from SEC...")

    with httpx.Client(
        headers={"User-Agent": config.user_agent},
        timeout=120.0,
        follow_redirects=True,
    ) as client:
        response = client.get(url)
        response.raise_for_status()
        zip_path.write_bytes(response.content)

    print(f"Downloaded {len(response.content) / 1024 / 1024:.1f} MB")
    return zip_path


def _parse_coverpage(content: str) -> dict[str, dict]:
    """Parse COVERPAGE.tsv to get filer info by accession number."""
    filers = {}
    reader = csv.DictReader(io.StringIO(content), delimiter="\t")

    for row in reader:
        accession = row.get("ACCESSION_NUMBER", "").strip()
        if accession:
            # Extract CIK from accession number (first 10 digits, format: XXXXXXXXXX-YY-ZZZZZZ)
            cik = accession.split("-")[0] if "-" in accession else ""
            filers[accession] = {
                "cik": cik,
                "name": row.get("FILINGMANAGER_NAME", row.get("NAME", "")).strip(),
            }

    return filers


def _parse_infotable(
    content: str,
    filers: dict[str, dict],
    cusip_filter: str | None = None,
    min_value: int = 0,
    report_period: str = "",
) -> list[HoldingRecord]:
    """Parse INFOTABLE.tsv to get holdings.

    Args:
        content: TSV file content
        filers: Filer info by accession number
        cusip_filter: Optional CUSIP to filter by
        min_value: Minimum value in USD (not thousands)
        report_period: The reporting period date

    Returns:
        List of HoldingRecord objects
    """
    holdings = []
    reader = csv.DictReader(io.StringIO(content), delimiter="\t")

    for row in reader:
        cusip = row.get("CUSIP", "").strip()

        # Filter by CUSIP if specified
        if cusip_filter and cusip != cusip_filter:
            continue

        # Parse shares first (needed for value normalization)
        try:
            shares = int(row.get("SSHPRNAMT", "0").strip() or "0")
        except ValueError:
            shares = 0

        # Parse value - SEC bulk data has inconsistent formats:
        # Some filers report in dollars, others in thousands.
        # We detect format by computing per-share price.
        try:
            raw_value = int(row.get("VALUE", "0").strip() or "0")
        except ValueError:
            raw_value = 0

        # Normalize value: detect if reported in dollars or thousands
        if shares > 0 and raw_value > 0:
            per_share = raw_value / shares
            # If per-share price is unreasonably low (<$1), value is in thousands
            # Most stocks trade between $1 and $50,000 per share
            if per_share < 1.0:
                # Value reported in thousands - convert to dollars
                value_usd = raw_value * 1000
            else:
                # Value already in dollars
                value_usd = raw_value
        else:
            value_usd = raw_value

        # Store thousands for compatibility
        value_thousands = value_usd // 1000

        # Filter by minimum value
        if value_usd < min_value:
            continue

        # Get filer info
        accession = row.get("ACCESSION_NUMBER", "").strip()
        filer = filers.get(accession, {"cik": "", "name": "Unknown"})

        # Parse voting authority
        try:
            voting_sole = int(row.get("VOTINGAUTHORITY_SOLE", "0").strip() or "0")
            voting_shared = int(row.get("VOTINGAUTHORITY_SHARED", "0").strip() or "0")
            voting_none = int(row.get("VOTINGAUTHORITY_NONE", "0").strip() or "0")
        except ValueError:
            voting_sole = voting_shared = voting_none = 0

        # Handle PUT/CALL
        put_call_raw = row.get("PUTCALL", "").strip().upper()
        put_call = put_call_raw if put_call_raw in ("PUT", "CALL") else None

        holding = HoldingRecord(
            accession_number=accession,
            filer_cik=filer["cik"],
            filer_name=filer["name"],
            cusip=cusip,
            issuer_name=row.get("NAMEOFISSUER", "").strip(),
            title_of_class=row.get("TITLEOFCLASS", "").strip(),
            value_thousands=value_thousands,
            value_usd=value_usd,
            shares=shares,
            shares_type=row.get("SSHPRNAMTTYPE", "SH").strip(),
            put_call=put_call,
            investment_discretion=row.get("INVESTMENTDISCRETION", "").strip(),
            voting_sole=voting_sole,
            voting_shared=voting_shared,
            voting_none=voting_none,
            report_period=report_period,
        )
        holdings.append(holding)

    return holdings


def extract_cusip_holdings(
    quarter: str,
    cusip: str,
    config: Config,
    min_value: int = 50_000_000,
) -> list[HoldingRecord]:
    """Extract all holdings for a specific CUSIP from a quarterly data set.

    Args:
        quarter: Quarter string like "2024Q3"
        cusip: 9-character CUSIP to search for
        config: Config object
        min_value: Minimum position value in USD (default $50M)

    Returns:
        List of HoldingRecord objects for the CUSIP
    """
    # Download data if needed
    zip_path = download_quarterly_data(quarter, config)

    # Parse the zip file
    report_period = _quarter_to_report_period(quarter)

    with zipfile.ZipFile(zip_path, "r") as zf:
        # Find the file names (they might have different cases)
        names = zf.namelist()
        coverpage_name = next((n for n in names if "COVERPAGE" in n.upper()), None)
        infotable_name = next((n for n in names if "INFOTABLE" in n.upper()), None)

        if not coverpage_name or not infotable_name:
            raise ValueError(f"Could not find COVERPAGE or INFOTABLE in {zip_path}")

        # Parse coverpage for filer info
        with zf.open(coverpage_name) as f:
            coverpage_content = f.read().decode("utf-8", errors="replace")
        filers = _parse_coverpage(coverpage_content)

        # Parse infotable for holdings
        with zf.open(infotable_name) as f:
            infotable_content = f.read().decode("utf-8", errors="replace")

        holdings = _parse_infotable(
            infotable_content,
            filers,
            cusip_filter=cusip,
            min_value=min_value,
            report_period=report_period,
        )

    # Sort by value descending
    holdings.sort(key=lambda h: h.value_usd, reverse=True)

    return holdings


def get_all_cusips_for_quarter(
    quarter: str,
    config: Config,
) -> set[str]:
    """Get all unique CUSIPs in a quarterly data set.

    This is useful for validating a CUSIP exists.
    """
    zip_path = download_quarterly_data(quarter, config)

    cusips = set()
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        infotable_name = next((n for n in names if "INFOTABLE" in n.upper()), None)

        if not infotable_name:
            return cusips

        with zf.open(infotable_name) as f:
            reader = csv.DictReader(
                io.TextIOWrapper(f, encoding="utf-8", errors="replace"),
                delimiter="\t",
            )
            for row in reader:
                cusip = row.get("CUSIP", "").strip()
                if cusip:
                    cusips.add(cusip)

    return cusips


def estimate_storage_for_cusip(
    cusip: str,
    quarters: int = 4,
    avg_holders_per_quarter: int = 150,
    bytes_per_holding: int = 300,
) -> int:
    """Estimate storage needed for a CUSIP.

    Returns estimated bytes.
    """
    # Rough estimate: ~300 bytes per holding record in JSON
    return quarters * avg_holders_per_quarter * bytes_per_holding
