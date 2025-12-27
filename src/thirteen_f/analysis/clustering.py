"""Deterministic keyword-based clustering for holdings."""

# Cluster definitions: keyword rules for assigning holdings to clusters
CLUSTERS: dict[str, list[str]] = {
    "AI/Semiconductors": [
        "NVIDIA",
        "AMD",
        "ADVANCED MICRO",
        "INTEL",
        "ASML",
        "TSMC",
        "TAIWAN SEMI",
        "SEMICONDUCTOR",
        "BROADCOM",
        "QUALCOMM",
        "MARVELL",
        "MICRON",
        "APPLIED MATERIAL",
        "LAM RESEARCH",
        "KLA",
        "SYNOPSYS",
        "CADENCE",
        "ARM HOLDINGS",
        "LATTICE",
    ],
    "Cloud/SaaS": [
        "SALESFORCE",
        "SERVICENOW",
        "WORKDAY",
        "SNOWFLAKE",
        "DATADOG",
        "MONGODB",
        "CLOUDFLARE",
        "ATLASSIAN",
        "HUBSPOT",
        "ZSCALER",
        "CROWDSTRIKE",
        "OKTA",
        "SPLUNK",
        "TWILIO",
        "DOCUSIGN",
        "ZOOM",
        "DROPBOX",
        "BOX INC",
    ],
    "Fintech/Payments": [
        "VISA",
        "MASTERCARD",
        "PAYPAL",
        "SQUARE",
        "BLOCK INC",
        "STRIPE",
        "ADYEN",
        "AFFIRM",
        "SOFI",
        "ROBINHOOD",
        "COINBASE",
        "MARQETA",
        "TOAST",
        "BILL.COM",
        "BILL HOLDINGS",
    ],
    "E-commerce/Retail": [
        "AMAZON",
        "SHOPIFY",
        "MERCADOLIBRE",
        "ETSY",
        "EBAY",
        "WAYFAIR",
        "CHEWY",
        "COUPANG",
        "PINDUODUO",
        "JD.COM",
        "ALIBABA",
        "WALMART",
        "TARGET",
        "COSTCO",
        "HOME DEPOT",
        "LOWE",
    ],
    "Social/Advertising": [
        "META",
        "FACEBOOK",
        "GOOGLE",
        "ALPHABET",
        "SNAP",
        "PINTEREST",
        "TWITTER",
        "LINKEDIN",
        "REDDIT",
        "TRADE DESK",
        "PUBMATIC",
        "DIGITAL TURBINE",
    ],
    "Streaming/Media": [
        "NETFLIX",
        "SPOTIFY",
        "DISNEY",
        "WARNER",
        "PARAMOUNT",
        "ROKU",
        "ROBLOX",
        "UNITY",
        "TAKE-TWO",
        "ELECTRONIC ARTS",
        "ACTIVISION",
        "LIVE NATION",
        "IMAX",
    ],
    "Healthcare/Biotech": [
        "UNITEDHEALTH",
        "CVS",
        "HUMANA",
        "CIGNA",
        "ANTHEM",
        "ELEVANCE",
        "PFIZER",
        "LILLY",
        "ELI LILLY",
        "MERCK",
        "JOHNSON & JOHNSON",
        "ABBVIE",
        "AMGEN",
        "GILEAD",
        "REGENERON",
        "MODERNA",
        "BIONTECH",
        "VERTEX",
        "ILLUMINA",
        "DEXCOM",
        "INTUITIVE SURGICAL",
        "THERMO FISHER",
        "DANAHER",
        "ABBOTT",
    ],
    "Energy": [
        "EXXON",
        "CHEVRON",
        "MARATHON",
        "OCCIDENTAL",
        "CONOCOPHILLIPS",
        "SCHLUMBERGER",
        "HALLIBURTON",
        "PIONEER",
        "DEVON",
        "EOG",
        "DIAMONDBACK",
        "COTERRA",
        "HESS",
        "VALERO",
        "PHILLIPS 66",
    ],
    "Clean Energy": [
        "TESLA",
        "RIVIAN",
        "LUCID",
        "ENPHASE",
        "SOLAREDGE",
        "FIRST SOLAR",
        "SUNRUN",
        "PLUG POWER",
        "BLOOM ENERGY",
        "CHARGEPOINT",
        "EVGO",
        "NEXTERA",
    ],
    "Financials/Banks": [
        "JPMORGAN",
        "JP MORGAN",
        "BANK OF AMERICA",
        "WELLS FARGO",
        "CITIGROUP",
        "GOLDMAN",
        "MORGAN STANLEY",
        "CHARLES SCHWAB",
        "BLACKROCK",
        "BLACKSTONE",
        "KKR",
        "APOLLO",
        "CARLYLE",
        "STATE STREET",
        "NORTHERN TRUST",
        "BANK OF NEW YORK",
        "US BANCORP",
        "PNC",
        "TRUIST",
        "CAPITAL ONE",
        "AMERICAN EXPRESS",
        "DISCOVER",
        "SYNCHRONY",
    ],
    "Industrials": [
        "CATERPILLAR",
        "DEERE",
        "JOHN DEERE",
        "BOEING",
        "LOCKHEED",
        "RAYTHEON",
        "RTX",
        "NORTHROP",
        "GENERAL DYNAMICS",
        "L3HARRIS",
        "HONEYWELL",
        "3M",
        "GENERAL ELECTRIC",
        "UNION PACIFIC",
        "CSX",
        "NORFOLK",
        "FEDEX",
        "UPS",
        "UNITED PARCEL",
    ],
    "Consumer": [
        "COCA-COLA",
        "PEPSI",
        "PROCTER",
        "P&G",
        "UNILEVER",
        "COLGATE",
        "KIMBERLY",
        "CLOROX",
        "ESTEE LAUDER",
        "NIKE",
        "LULULEMON",
        "STARBUCKS",
        "MCDONALD",
        "CHIPOTLE",
        "YUM",
        "DOMINO",
    ],
    "Telecom": [
        "AT&T",
        "VERIZON",
        "T-MOBILE",
        "COMCAST",
        "CHARTER",
        "DISH",
        "LUMEN",
        "VONAGE",
    ],
    "Real Estate": [
        "PROLOGIS",
        "AMERICAN TOWER",
        "CROWN CASTLE",
        "EQUINIX",
        "DIGITAL REALTY",
        "PUBLIC STORAGE",
        "REALTY INCOME",
        "SIMON PROPERTY",
        "WELLTOWER",
        "VENTAS",
        "AVALONBAY",
        "EQUITY RESIDENTIAL",
    ],
}


def assign_cluster(issuer_name: str) -> str:
    """
    Assign a holding to a cluster based on issuer name.

    Args:
        issuer_name: The issuer name from the 13F

    Returns:
        Cluster name, or "Other" if no match
    """
    name_upper = issuer_name.upper()

    for cluster, keywords in CLUSTERS.items():
        for keyword in keywords:
            if keyword in name_upper:
                return cluster

    return "Other"


def cluster_holdings(
    holdings: list[tuple[str, int, float]]
) -> dict[str, list[tuple[str, int, float]]]:
    """
    Group holdings by cluster.

    Args:
        holdings: List of (issuer_name, value_usd, weight) tuples

    Returns:
        Dict mapping cluster name to list of holdings
    """
    clusters: dict[str, list[tuple[str, int, float]]] = {}

    for issuer_name, value_usd, weight in holdings:
        cluster = assign_cluster(issuer_name)
        if cluster not in clusters:
            clusters[cluster] = []
        clusters[cluster].append((issuer_name, value_usd, weight))

    # Sort each cluster by value descending
    for cluster in clusters:
        clusters[cluster].sort(key=lambda x: x[1], reverse=True)

    return clusters


def summarize_clusters(
    holdings: list[tuple[str, int, float]]
) -> list[tuple[str, int, float, int]]:
    """
    Summarize holdings by cluster.

    Args:
        holdings: List of (issuer_name, value_usd, weight) tuples

    Returns:
        List of (cluster_name, total_value, total_weight, position_count) tuples,
        sorted by total_value descending
    """
    clusters = cluster_holdings(holdings)

    summaries = []
    for cluster, cluster_holdings_list in clusters.items():
        total_value = sum(h[1] for h in cluster_holdings_list)
        total_weight = sum(h[2] for h in cluster_holdings_list)
        count = len(cluster_holdings_list)
        summaries.append((cluster, total_value, total_weight, count))

    # Sort by total value descending
    summaries.sort(key=lambda x: x[1], reverse=True)
    return summaries
