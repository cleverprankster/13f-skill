"""Ticker to CUSIP lookup and mapping."""

import csv
import io
import json
import zipfile
from pathlib import Path

import httpx

from ..config import Config


# Well-known ticker to CUSIP mappings (common stocks)
# This is a starting point - gets extended as users query stocks
KNOWN_MAPPINGS = {
    # Mega caps
    "AAPL": ("037833100", "APPLE INC"),
    "MSFT": ("594918104", "MICROSOFT CORP"),
    "GOOGL": ("02079K305", "ALPHABET INC"),
    "GOOG": ("02079K107", "ALPHABET INC"),
    "AMZN": ("023135106", "AMAZON COM INC"),
    "NVDA": ("67066G104", "NVIDIA CORP"),
    "META": ("30303M102", "META PLATFORMS INC"),
    "TSLA": ("88160R101", "TESLA INC"),
    "BRK.A": ("084670108", "BERKSHIRE HATHAWAY INC"),
    "BRK.B": ("084670702", "BERKSHIRE HATHAWAY INC"),
    # Tech
    "TSM": ("874039100", "TAIWAN SEMICONDUCTOR MFG CO LTD"),
    "AVGO": ("11135F101", "BROADCOM INC"),
    "ORCL": ("68389X105", "ORACLE CORP"),
    "CRM": ("79466L302", "SALESFORCE INC"),
    "AMD": ("007903107", "ADVANCED MICRO DEVICES INC"),
    "INTC": ("458140100", "INTEL CORP"),
    "QCOM": ("747525103", "QUALCOMM INC"),
    "TXN": ("882508104", "TEXAS INSTRUMENTS INC"),
    "MU": ("595112103", "MICRON TECHNOLOGY INC"),
    "AMAT": ("038222105", "APPLIED MATERIALS INC"),
    "LRCX": ("512807108", "LAM RESEARCH CORP"),
    "ASML": ("N07059210", "ASML HOLDING NV"),
    "KLAC": ("482480100", "KLA CORP"),
    # Consumer/Media
    "NFLX": ("64110L106", "NETFLIX INC"),
    "DIS": ("254687106", "WALT DISNEY CO"),
    "CMCSA": ("20030N101", "COMCAST CORP"),
    "SBUX": ("855244109", "STARBUCKS CORP"),
    "NKE": ("654106103", "NIKE INC"),
    "MCD": ("580135101", "MCDONALDS CORP"),
    "PEP": ("713448108", "PEPSICO INC"),
    "KO": ("191216100", "COCA COLA CO"),
    # Finance
    "V": ("92826C839", "VISA INC"),
    "MA": ("57636Q104", "MASTERCARD INC"),
    "JPM": ("46625H100", "JPMORGAN CHASE & CO"),
    "BAC": ("060505104", "BANK OF AMERICA CORP"),
    "WFC": ("949746101", "WELLS FARGO & CO"),
    "GS": ("38141G104", "GOLDMAN SACHS GROUP INC"),
    "MS": ("617446448", "MORGAN STANLEY"),
    "AXP": ("025816109", "AMERICAN EXPRESS CO"),
    # Healthcare
    "UNH": ("91324P102", "UNITEDHEALTH GROUP INC"),
    "JNJ": ("478160104", "JOHNSON & JOHNSON"),
    "PFE": ("717081103", "PFIZER INC"),
    "ABBV": ("00287Y109", "ABBVIE INC"),
    "MRK": ("58933Y105", "MERCK & CO INC"),
    "LLY": ("532457108", "ELI LILLY & CO"),
    # Energy
    "XOM": ("30231G102", "EXXON MOBIL CORP"),
    "CVX": ("166764100", "CHEVRON CORP"),
    # ETFs (common ones used in options)
    "SPY": ("78462F103", "SPDR S&P 500 ETF TR"),
    "QQQ": ("46090E103", "INVESCO QQQ TR"),
    "IWM": ("464287655", "ISHARES RUSSELL 2000 ETF"),
    "DIA": ("25490K109", "SPDR DJIA TR"),
    # AI/Data
    "PLTR": ("69608A108", "PALANTIR TECHNOLOGIES INC"),
    "SNOW": ("833445109", "SNOWFLAKE INC"),
    "DDOG": ("23804L103", "DATADOG INC"),
    "CRWD": ("22788C105", "CROWDSTRIKE HOLDINGS INC"),
    # Gaming/Advertising
    "APP": ("03831W108", "APPLOVIN CORP"),
    "RBLX": ("771049103", "ROBLOX CORP"),
    "EA": ("285512109", "ELECTRONIC ARTS INC"),
    "TTWO": ("874054109", "TAKE TWO INTERACTIVE SOFTWARE"),
}


def get_cusip_mapping_path(config: Config) -> Path:
    """Get path to the user's CUSIP mapping cache."""
    return config.data_dir / "cusip_mappings.json"


def load_cusip_mappings(config: Config) -> dict[str, tuple[str, str]]:
    """Load CUSIP mappings from cache file.

    Returns dict of ticker -> (cusip, issuer_name)
    """
    mappings = dict(KNOWN_MAPPINGS)

    cache_path = get_cusip_mapping_path(config)
    if cache_path.exists():
        with open(cache_path) as f:
            user_mappings = json.load(f)
            for ticker, data in user_mappings.items():
                mappings[ticker.upper()] = (data["cusip"], data["name"])

    return mappings


def save_cusip_mapping(
    config: Config,
    ticker: str,
    cusip: str,
    issuer_name: str,
) -> None:
    """Save a new CUSIP mapping to the cache file."""
    cache_path = get_cusip_mapping_path(config)

    # Load existing
    if cache_path.exists():
        with open(cache_path) as f:
            mappings = json.load(f)
    else:
        mappings = {}

    # Add new mapping
    mappings[ticker.upper()] = {"cusip": cusip, "name": issuer_name}

    # Save
    with open(cache_path, "w") as f:
        json.dump(mappings, f, indent=2)


def ticker_to_cusip(ticker: str, config: Config) -> tuple[str, str] | None:
    """Look up CUSIP for a ticker symbol.

    Args:
        ticker: Stock ticker symbol (e.g., "TSM")
        config: Config object

    Returns:
        Tuple of (cusip, issuer_name) or None if not found
    """
    mappings = load_cusip_mappings(config)
    return mappings.get(ticker.upper())


def search_issuer_in_quarterly_data(
    search_term: str,
    quarter: str,
    config: Config,
    limit: int = 10,
) -> list[dict]:
    """Search for issuers by name in quarterly data.

    This is useful when we don't have a ticker mapping.

    Args:
        search_term: Partial issuer name to search for
        quarter: Quarter to search (e.g., "2024Q3")
        config: Config object
        limit: Maximum results to return

    Returns:
        List of dicts with cusip, issuer_name, sample_value
    """
    from .quarterly_data import download_quarterly_data

    zip_path = download_quarterly_data(quarter, config)
    search_upper = search_term.upper()

    results = {}  # cusip -> {name, max_value}

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        infotable_name = next((n for n in names if "INFOTABLE" in n.upper()), None)

        if not infotable_name:
            return []

        with zf.open(infotable_name) as f:
            reader = csv.DictReader(
                io.TextIOWrapper(f, encoding="utf-8", errors="replace"),
                delimiter="\t",
            )
            for row in reader:
                issuer = row.get("NAMEOFISSUER", "").strip()
                if search_upper in issuer.upper():
                    cusip = row.get("CUSIP", "").strip()
                    if cusip:
                        try:
                            value = int(row.get("VALUE", "0").strip() or "0") * 1000
                        except ValueError:
                            value = 0

                        if cusip not in results or value > results[cusip]["max_value"]:
                            results[cusip] = {
                                "cusip": cusip,
                                "issuer_name": issuer,
                                "max_value": value,
                            }

    # Sort by max_value descending and limit
    sorted_results = sorted(
        results.values(), key=lambda x: x["max_value"], reverse=True
    )
    return sorted_results[:limit]


def resolve_ticker_or_cusip(
    query: str,
    config: Config,
) -> tuple[str, str] | None:
    """Resolve a ticker or CUSIP to (cusip, issuer_name).

    Args:
        query: Either a ticker symbol or a CUSIP

    Returns:
        Tuple of (cusip, issuer_name) or None
    """
    query = query.strip().upper()

    # Check if it looks like a CUSIP (9 characters, alphanumeric)
    if len(query) == 9 and query.isalnum():
        # It's likely a CUSIP - search for issuer name in data
        # For now, return it with unknown name
        return (query, "Unknown Issuer")

    # Try ticker lookup
    result = ticker_to_cusip(query, config)
    if result:
        return result

    return None
