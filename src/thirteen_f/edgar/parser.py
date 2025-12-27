"""Parser for 13F information table XML files."""

from dataclasses import dataclass

from lxml import etree


@dataclass
class Holding:
    """A single holding from a 13F filing."""

    issuer_name: str
    title_of_class: str
    cusip: str
    figi: str | None
    value_thousands: int  # as reported
    value_usd: int  # derived: value_thousands * 1000
    shares_or_principal: int
    shares_type: str  # "SH" or "PRN"
    put_call: str | None  # "Put", "Call", or None
    investment_discretion: str  # "SOLE", "SHARED", "DFND"
    voting_sole: int
    voting_shared: int
    voting_none: int

    def holding_key(self) -> str:
        """Generate a unique key for this holding within a filing."""
        put_call_str = self.put_call or "NONE"
        return f"{self.cusip}|{self.title_of_class}|{put_call_str}|{self.shares_type}"


# XML namespaces used in 13F filings
NAMESPACES = {
    "ns": "http://www.sec.gov/edgar/document/thirteenf/informationtable",
    "ns1": "http://www.sec.gov/edgar/document/thirteenf/informationtable",
}


def _get_text(element: etree._Element, xpath: str, default: str = "") -> str:
    """Extract text from an element using xpath, with namespace handling."""
    # Try with namespace
    for prefix in ["ns:", "ns1:", ""]:
        try:
            result = element.xpath(f"{prefix}{xpath}", namespaces=NAMESPACES)
            if result:
                if isinstance(result[0], etree._Element):
                    return (result[0].text or "").strip()
                return str(result[0]).strip()
        except Exception:
            continue

    # Try direct child lookup
    for child in element:
        local_name = etree.QName(child).localname
        if local_name.lower() == xpath.lower():
            return (child.text or "").strip()

    return default


def _get_int(element: etree._Element, xpath: str, default: int = 0) -> int:
    """Extract integer from an element using xpath."""
    text = _get_text(element, xpath)
    if not text:
        return default
    # Remove commas and other formatting
    text = text.replace(",", "").replace(" ", "")
    try:
        return int(text)
    except ValueError:
        return default


def _normalize_text(text: str) -> str:
    """Normalize text: strip whitespace, consistent casing."""
    return " ".join(text.split()).strip()


def _normalize_cusip(cusip: str) -> str:
    """Normalize CUSIP to 9 uppercase characters."""
    return cusip.strip().upper()[:9].ljust(9)


def parse_13f_info_table(xml_content: bytes) -> list[Holding]:
    """
    Parse a 13F information table XML file.

    Args:
        xml_content: Raw XML content as bytes

    Returns:
        List of Holding objects
    """
    holdings: list[Holding] = []

    try:
        # Use secure parser to prevent XXE attacks
        # - resolve_entities=False: Don't resolve external entities
        # - no_network=True: Don't fetch external resources
        # - dtd_validation=False: Don't process DTD
        parser = etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            dtd_validation=False,
        )
        root = etree.fromstring(xml_content, parser=parser)
    except etree.XMLSyntaxError as e:
        raise ValueError(f"Failed to parse XML: {e}")

    # Find all infoTable entries - try different namespace patterns
    info_tables = []

    # Try various XPath patterns to find the info table entries
    patterns = [
        ".//ns:infoTable",
        ".//ns1:infoTable",
        ".//{http://www.sec.gov/edgar/document/thirteenf/informationtable}infoTable",
        ".//infoTable",
    ]

    for pattern in patterns:
        try:
            info_tables = root.xpath(pattern, namespaces=NAMESPACES)
            if info_tables:
                break
        except Exception:
            continue

    # Fallback: iterate through all children
    if not info_tables:
        for child in root.iter():
            if etree.QName(child).localname == "infoTable":
                info_tables.append(child)

    for info_table in info_tables:
        holding = _parse_info_table_entry(info_table)
        if holding:
            holdings.append(holding)

    return holdings


def _parse_info_table_entry(entry: etree._Element) -> Holding | None:
    """Parse a single infoTable entry."""
    try:
        # Extract basic fields
        issuer_name = _get_text(entry, "nameOfIssuer")
        title_of_class = _get_text(entry, "titleOfClass")
        cusip = _get_text(entry, "cusip")

        if not cusip:
            return None

        # FIGI is optional
        figi = _get_text(entry, "figi") or None

        # Value - SEC reports in thousands of dollars
        value_raw = _get_int(entry, "value")
        value_thousands = value_raw
        value_usd = value_raw * 1000  # Convert from thousands to actual USD

        # Shares/principal amount - look in shrsOrPrnAmt sub-element
        shares_or_principal = 0
        shares_type = "SH"

        for child in entry.iter():
            local_name = etree.QName(child).localname
            if local_name == "shrsOrPrnAmt":
                shares_or_principal = _get_int(child, "sshPrnamt")
                shares_type = _get_text(child, "sshPrnamtType", "SH").upper()
                break
            elif local_name == "sshPrnamt":
                shares_or_principal = _get_int(entry, "sshPrnamt")
            elif local_name == "sshPrnamtType":
                shares_type = _get_text(entry, "sshPrnamtType", "SH").upper()

        # Put/Call
        put_call_raw = _get_text(entry, "putCall")
        put_call = None
        if put_call_raw:
            put_call_upper = put_call_raw.upper()
            if "PUT" in put_call_upper:
                put_call = "Put"
            elif "CALL" in put_call_upper:
                put_call = "Call"

        # Investment discretion
        investment_discretion = _get_text(entry, "investmentDiscretion", "SOLE").upper()

        # Voting authority - look in votingAuthority sub-element
        voting_sole = 0
        voting_shared = 0
        voting_none = 0

        for child in entry.iter():
            local_name = etree.QName(child).localname
            if local_name == "votingAuthority":
                voting_sole = _get_int(child, "Sole")
                voting_shared = _get_int(child, "Shared")
                voting_none = _get_int(child, "None")
                break

        return Holding(
            issuer_name=_normalize_text(issuer_name),
            title_of_class=_normalize_text(title_of_class),
            cusip=_normalize_cusip(cusip),
            figi=figi,
            value_thousands=value_thousands,
            value_usd=value_usd,
            shares_or_principal=shares_or_principal,
            shares_type=shares_type,
            put_call=put_call,
            investment_discretion=investment_discretion,
            voting_sole=voting_sole,
            voting_shared=voting_shared,
            voting_none=voting_none,
        )

    except Exception:
        return None


def compute_filing_totals(holdings: list[Holding]) -> tuple[int, int]:
    """
    Compute filing totals from holdings.

    Returns:
        Tuple of (total_value_usd, position_count)
    """
    total_value = sum(h.value_usd for h in holdings)
    position_count = len(holdings)
    return total_value, position_count
