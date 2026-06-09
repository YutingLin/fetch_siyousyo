"""
Abstract base class and shared dataclasses for procurement scrapers.
"""

import hashlib
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import (
    ENCODING_CANDIDATES,
    MAX_RETRIES,
    REQUEST_DELAY,
    REQUEST_TIMEOUT,
    RETRY_BACKOFF_FACTOR,
    USER_AGENT,
)

logger = logging.getLogger(__name__)


@dataclass
class DocumentLink:
    """Represents a single document (PDF) link found on a procurement page."""

    url: str
    text: str
    doc_type: str          # '仕様書', '提案書', or 'OTHER'
    filename: str = ""
    context_text: str = ""


@dataclass
class ProcurementRecord:
    """Represents a single procurement listing with its associated documents."""

    id: str
    title: str
    agency: str
    date: str              # ISO date string YYYY-MM-DD or empty
    url: str
    documents: List[DocumentLink] = field(default_factory=list)

    @classmethod
    def make_id(cls, url: str, title: str) -> str:
        """Generate a stable ID from URL and title."""
        key = f"{url}|{title}"
        return hashlib.md5(key.encode("utf-8")).hexdigest()[:12]


class BaseScraper(ABC):
    """Abstract base class for procurement scrapers."""

    def __init__(self, source_name: str, base_url: str):
        self.source_name = source_name
        self.base_url = base_url
        self.session = self._build_session()
        self._last_request_time: float = 0.0

    # ------------------------------------------------------------------
    # Session / HTTP helpers
    # ------------------------------------------------------------------

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=MAX_RETRIES,
            backoff_factor=RETRY_BACKOFF_FACTOR,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update({"User-Agent": USER_AGENT})
        return session

    def _rate_limited_get(self, url: str, **kwargs) -> requests.Response:
        """GET with rate limiting and encoding detection."""
        elapsed = time.time() - self._last_request_time
        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)

        logger.debug("GET %s", url)
        kwargs.setdefault("timeout", REQUEST_TIMEOUT)
        response = self.session.get(url, **kwargs)
        self._last_request_time = time.time()
        response.raise_for_status()

        # Fix encoding for Japanese government sites
        if response.encoding and response.encoding.lower() in ("iso-8859-1", ""):
            response.encoding = self._detect_encoding(response.content)

        return response

    @staticmethod
    def _detect_encoding(content: bytes) -> str:
        """Detect encoding from byte content using chardet or fallback list."""
        try:
            import chardet
            result = chardet.detect(content)
            if result and result.get("confidence", 0) > 0.7:
                return result["encoding"]
        except ImportError:
            pass

        # Try BOM
        if content.startswith(b"\xef\xbb\xbf"):
            return "utf-8-sig"
        if content.startswith(b"\xff\xfe") or content.startswith(b"\xfe\xff"):
            return "utf-16"

        # Try each candidate
        for enc in ENCODING_CANDIDATES:
            try:
                content.decode(enc)
                return enc
            except (UnicodeDecodeError, LookupError):
                continue

        return "utf-8"

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def search(
        self,
        keywords: List[str],
        date_from: str,
        date_to: str,
    ) -> List[ProcurementRecord]:
        """
        Search for procurement records matching the given criteria.

        Parameters
        ----------
        keywords : list[str]
            Keywords to filter records by title or content.
        date_from : str
            Start date in YYYY-MM-DD format (inclusive).
        date_to : str
            End date in YYYY-MM-DD format (inclusive).

        Returns
        -------
        list[ProcurementRecord]
            Matching procurement records with their document links.
        """
        ...

    # ------------------------------------------------------------------
    # Shared utility methods
    # ------------------------------------------------------------------

    @staticmethod
    def _record_matches_keywords(record: ProcurementRecord, keywords: List[str]) -> bool:
        """Return True if any keyword appears in the record title (case-insensitive)."""
        if not keywords:
            return True
        title_lower = record.title.lower()
        for kw in keywords:
            if kw.lower() in title_lower:
                return True
        return False

    @staticmethod
    def _record_in_date_range(record: ProcurementRecord, date_from: str, date_to: str) -> bool:
        """Return True if the record date falls within [date_from, date_to]."""
        if not record.date:
            return True  # No date info → include by default
        if date_from and record.date < date_from:
            return False
        if date_to and record.date > date_to:
            return False
        return True
