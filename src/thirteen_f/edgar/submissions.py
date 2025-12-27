"""SEC EDGAR submissions lookup and 13F filing discovery."""

import re
from dataclasses import dataclass
from datetime import datetime

from .client import EdgarClient


@dataclass
class FilingInfo:
    """Metadata about a 13F filing."""

    accession_number: str
    form_type: str  # "13F-HR" or "13F-HR/A"
    filing_date: str  # "YYYY-MM-DD"
    period_of_report: str  # "YYYY-MM-DD"
    is_amendment: bool
    primary_document: str  # Main filing document filename


def get_13f_filings(
    client: EdgarClient,
    cik: str,
    periods: int = 5,
    original_only: bool = False,
) -> list[FilingInfo]:
    """
    Get the most recent 13F filings for a CIK.

    Args:
        client: EdgarClient instance
        cik: The CIK number
        periods: Number of reporting periods to retrieve (default: 5 = latest + 4 prior)
        original_only: If True, only return original filings (ignore amendments)

    Returns:
        List of FilingInfo objects, sorted by period_of_report descending
    """
    submissions = client.get_submissions(cik)

    # Extract filing data from recent filings
    recent = submissions.get("filings", {}).get("recent", {})
    if not recent:
        return []

    form_types = recent.get("form", [])
    accession_numbers = recent.get("accessionNumber", [])
    filing_dates = recent.get("filingDate", [])
    primary_documents = recent.get("primaryDocument", [])
    report_dates = recent.get("reportDate", [])

    # Collect all 13F-HR and 13F-HR/A filings
    filings: list[FilingInfo] = []
    for i, form_type in enumerate(form_types):
        if form_type not in ("13F-HR", "13F-HR/A"):
            continue

        if original_only and form_type == "13F-HR/A":
            continue

        filings.append(
            FilingInfo(
                accession_number=accession_numbers[i],
                form_type=form_type,
                filing_date=filing_dates[i],
                period_of_report=report_dates[i],
                is_amendment=form_type == "13F-HR/A",
                primary_document=primary_documents[i],
            )
        )

    # Group by period_of_report and select the latest filing per period
    # (amendments supersede originals)
    by_period: dict[str, FilingInfo] = {}
    for f in filings:
        period = f.period_of_report
        if period not in by_period:
            by_period[period] = f
        else:
            # Prefer amendment over original, or later filing date
            existing = by_period[period]
            if f.is_amendment and not existing.is_amendment:
                by_period[period] = f
            elif f.is_amendment == existing.is_amendment:
                if f.filing_date > existing.filing_date:
                    by_period[period] = f

    # Sort by period descending and take the requested number
    sorted_filings = sorted(by_period.values(), key=lambda x: x.period_of_report, reverse=True)
    return sorted_filings[:periods]


def find_info_table_filename(client: EdgarClient, cik: str, accession_number: str) -> str | None:
    """
    Find the information table XML filename from the filing index.

    Args:
        client: EdgarClient instance
        cik: The CIK number
        accession_number: The accession number

    Returns:
        The info table filename, or None if not found
    """
    try:
        index_html = client.get_filing_index(cik, accession_number)
    except Exception:
        return None

    # Extract all XML file hrefs
    xml_hrefs = re.findall(r'href="([^"]+\.xml)"', index_html, re.IGNORECASE)

    # Extract just filenames (last component of path)
    xml_files = []
    for href in xml_hrefs:
        filename = href.split("/")[-1]
        # Skip duplicates and styled versions in xsl* directories
        if filename not in [f for f, _ in xml_files] and "/xsl" not in href.lower():
            xml_files.append((filename, href))

    # Priority 1: Look for infotable patterns
    for filename, href in xml_files:
        lower = filename.lower()
        if "infotable" in lower or "information" in lower:
            return filename

    # Priority 2: Look for form13f_*.xml (holdings table used by some filers)
    for filename, href in xml_files:
        if filename.lower().startswith("form13f_") and filename.lower().endswith(".xml"):
            return filename

    # Priority 3: Any XML that's not primary_doc
    for filename, href in xml_files:
        lower = filename.lower()
        if "primary" not in lower:
            return filename

    return None


def get_latest_filing_period(client: EdgarClient, cik: str) -> str | None:
    """
    Get the most recent 13F filing period for a CIK.

    Args:
        client: EdgarClient instance
        cik: The CIK number

    Returns:
        Period of report string (e.g., "2024-12-31") or None if no filings
    """
    # Bypass cache to get fresh data
    submissions = client.get_submissions(cik, use_cache=False)

    recent = submissions.get("filings", {}).get("recent", {})
    if not recent:
        return None

    form_types = recent.get("form", [])
    report_dates = recent.get("reportDate", [])

    # Find the most recent 13F-HR or 13F-HR/A
    for i, form_type in enumerate(form_types):
        if form_type in ("13F-HR", "13F-HR/A"):
            return report_dates[i]

    return None


def lookup_cik_by_name(client: EdgarClient, company_name: str) -> list[tuple[str, str]]:
    """
    Best-effort CIK lookup by company name using SEC full-text search.

    Args:
        client: EdgarClient instance
        company_name: Company name to search for

    Returns:
        List of (cik, company_name) tuples for potential matches
    """
    # Use the SEC company search endpoint
    # Note: This is a simplified approach; the actual SEC search is more complex
    search_url = f"https://efts.sec.gov/LATEST/search-index?q={company_name}&dateRange=custom&forms=13F-HR"

    try:
        # This endpoint may not work exactly like this - it's a best-effort lookup
        # In practice, users should verify CIKs manually
        data = client.get_json(search_url, use_cache=False)
        hits = data.get("hits", {}).get("hits", [])
        results = []
        for hit in hits[:10]:
            source = hit.get("_source", {})
            cik = source.get("ciks", [""])[0]
            name = source.get("display_names", [company_name])[0]
            if cik:
                results.append((cik, name))
        return results
    except Exception:
        return []


def period_to_quarter(period_of_report: str) -> str:
    """
    Convert a period of report date to quarter notation.

    Args:
        period_of_report: Date string "YYYY-MM-DD"

    Returns:
        Quarter string like "2025Q3"
    """
    date = datetime.strptime(period_of_report, "%Y-%m-%d")
    quarter = (date.month - 1) // 3 + 1
    return f"{date.year}Q{quarter}"


def quarter_to_period(quarter: str) -> str:
    """
    Convert a quarter notation to period of report date.

    Args:
        quarter: Quarter string like "2025Q3"

    Returns:
        Date string "YYYY-MM-DD" (end of quarter)
    """
    match = re.match(r"(\d{4})Q([1-4])", quarter)
    if not match:
        raise ValueError(f"Invalid quarter format: {quarter}")

    year = int(match.group(1))
    q = int(match.group(2))

    # Quarter end dates
    end_dates = {
        1: f"{year}-03-31",
        2: f"{year}-06-30",
        3: f"{year}-09-30",
        4: f"{year}-12-31",
    }
    return end_dates[q]
