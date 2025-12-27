"""SEC EDGAR HTTP client with rate limiting and caching."""

import hashlib
import json
import time
from pathlib import Path

import httpx

from ..config import Config


class EdgarClient:
    """HTTP client for SEC EDGAR with rate limiting and disk caching."""

    BASE_URL = "https://data.sec.gov"
    ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"

    def __init__(self, config: Config) -> None:
        self.config = config
        self.cache_dir = config.cache_dir
        self._last_request_time: float = 0.0
        self._min_request_interval = 1.0 / config.rate_limit_per_second

        self._client = httpx.Client(
            headers={
                "User-Agent": config.user_agent,
                "Accept-Encoding": "gzip, deflate",
            },
            timeout=30.0,
            follow_redirects=True,
        )

    def _rate_limit(self) -> None:
        """Enforce rate limiting between requests."""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

    def _cache_key(self, url: str) -> str:
        """Generate a cache key for a URL."""
        return hashlib.sha256(url.encode()).hexdigest()[:16]

    def _get_cache_path(self, url: str, suffix: str = ".json") -> Path:
        """Get the cache file path for a URL."""
        return self.cache_dir / f"{self._cache_key(url)}{suffix}"

    def _read_cache(self, url: str, suffix: str = ".json") -> bytes | None:
        """Read cached response if it exists."""
        cache_path = self._get_cache_path(url, suffix)
        if cache_path.exists():
            return cache_path.read_bytes()
        return None

    def _write_cache(self, url: str, data: bytes, suffix: str = ".json") -> None:
        """Write response to cache."""
        cache_path = self._get_cache_path(url, suffix)
        cache_path.write_bytes(data)

    def get(self, url: str, use_cache: bool = True, cache_suffix: str = ".json") -> bytes:
        """
        Fetch a URL with rate limiting and optional caching.

        Args:
            url: The URL to fetch
            use_cache: Whether to use disk cache
            cache_suffix: File suffix for cache file

        Returns:
            Response content as bytes
        """
        # Check cache first
        if use_cache:
            cached = self._read_cache(url, cache_suffix)
            if cached is not None:
                return cached

        # Rate limit and fetch
        self._rate_limit()
        response = self._client.get(url)
        response.raise_for_status()

        # Cache the response
        if use_cache:
            self._write_cache(url, response.content, cache_suffix)

        return response.content

    def get_json(self, url: str, use_cache: bool = True) -> dict:
        """Fetch and parse JSON from a URL."""
        data = self.get(url, use_cache=use_cache, cache_suffix=".json")
        return json.loads(data)

    def get_submissions(self, cik: str, use_cache: bool = True) -> dict:
        """
        Fetch the submissions JSON for a CIK.

        Args:
            cik: The CIK number (with or without leading zeros)
            use_cache: Whether to use disk cache (default True)

        Returns:
            Submissions data as dict
        """
        # Normalize CIK to 10 digits with leading zeros
        cik_normalized = cik.lstrip("0").zfill(10)
        url = f"{self.BASE_URL}/submissions/CIK{cik_normalized}.json"
        return self.get_json(url, use_cache=use_cache)

    def get_filing_index(self, cik: str, accession_number: str) -> str:
        """
        Fetch the filing index page to find the info table file.

        Args:
            cik: The CIK number
            accession_number: The accession number (e.g., "0001104659-24-123456")

        Returns:
            Index page HTML as string
        """
        cik_normalized = cik.lstrip("0")
        accession_clean = accession_number.replace("-", "")
        url = f"{self.ARCHIVES_URL}/{cik_normalized}/{accession_clean}/{accession_number}-index.htm"
        data = self.get(url, cache_suffix=".html")
        return data.decode("utf-8")

    def get_info_table_xml(self, cik: str, accession_number: str, filename: str) -> bytes:
        """
        Fetch the 13F information table XML file.

        Args:
            cik: The CIK number
            accession_number: The accession number
            filename: The info table filename (e.g., "infotable.xml")

        Returns:
            XML content as bytes
        """
        cik_normalized = cik.lstrip("0")
        accession_clean = accession_number.replace("-", "")
        url = f"{self.ARCHIVES_URL}/{cik_normalized}/{accession_clean}/{filename}"
        return self.get(url, cache_suffix=".xml")

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self) -> "EdgarClient":
        return self

    def __exit__(self, *args) -> None:
        self.close()
