"""
Generic procurement scraper.

Takes a configurable base_url and crawls pages looking for procurement records,
detecting PDFs and classifying them.  Supports paginated listings.
"""

import logging
import re
from typing import List, Optional, Set
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from src.classifier import DocType, classify_url, extract_filename_from_url
from src.scrapers.base import BaseScraper, DocumentLink, ProcurementRecord

logger = logging.getLogger(__name__)

# Date patterns used to extract publication dates from page text
_DATE_PATTERNS = [
    re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日"),
    re.compile(r"(\d{4})-(\d{2})-(\d{2})"),
    re.compile(r"(\d{4})/(\d{2})/(\d{2})"),
]

# Heuristic keywords that suggest a link leads to a procurement detail page
_PROCUREMENT_HINT_WORDS = [
    "調達", "入札", "公告", "仕様書", "提案", "案件", "業務", "委託",
    "procurement", "bid", "rfp", "tender",
]


def _extract_date(text: str) -> str:
    """Extract the first date found in text and return YYYY-MM-DD."""
    for pat in _DATE_PATTERNS:
        m = pat.search(text)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return ""


def _looks_like_procurement_link(href: str, text: str, base_netloc: str) -> bool:
    """
    Heuristic: decide if (href, text) looks like a procurement detail page link.
    """
    if not href:
        return False
    if href.startswith("#") or href.startswith("javascript"):
        return False
    # Skip direct PDF links (those are documents, not listing pages)
    if href.lower().endswith(".pdf"):
        return False

    parsed = urlparse(href)
    # If absolute, must share the same netloc
    if parsed.netloc and parsed.netloc != base_netloc:
        return False

    combined = (href + " " + text).lower()
    for hint in _PROCUREMENT_HINT_WORDS:
        if hint in combined:
            return True
    return False


class GenericScraper(BaseScraper):
    """
    Generic scraper that can be pointed at any procurement listing page.

    Parameters
    ----------
    base_url : str
        The procurement listing page URL.
    agency_name : str
        Human-readable name of the agency (used in ProcurementRecord.agency).
    source_name : str
        Short identifier used for file paths (e.g., 'soumu').
    max_detail_pages : int
        Maximum number of detail pages to visit per scrape run.
    max_listing_pages : int
        Maximum number of paginated listing pages to follow.
    """

    def __init__(
        self,
        base_url: str,
        agency_name: str = "",
        source_name: str = "generic",
        max_detail_pages: int = 100,
        max_listing_pages: int = 10,
    ):
        super().__init__(source_name=source_name, base_url=base_url)
        self.agency_name = agency_name or base_url
        self.max_detail_pages = max_detail_pages
        self.max_listing_pages = max_listing_pages
        self._base_netloc = urlparse(base_url).netloc

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def search(
        self,
        keywords: List[str],
        date_from: str,
        date_to: str,
    ) -> List[ProcurementRecord]:
        """
        Crawl the base_url for procurement records matching the given criteria.
        """
        records: List[ProcurementRecord] = []

        detail_urls = self._collect_detail_urls()
        logger.info(
            "[%s] Found %d candidate detail URLs", self.agency_name, len(detail_urls)
        )

        for url in detail_urls[: self.max_detail_pages]:
            try:
                record = self._parse_detail_page(url)
                if record is None:
                    continue
                if not self._record_matches_keywords(record, keywords):
                    continue
                if not self._record_in_date_range(record, date_from, date_to):
                    continue
                # Only keep records that have at least one relevant PDF
                if record.documents:
                    records.append(record)
            except Exception as exc:
                logger.warning("[%s] Failed to parse %s: %s", self.agency_name, url, exc)

        logger.info(
            "[%s] Returning %d matching records", self.agency_name, len(records)
        )
        return records

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _collect_detail_urls(self) -> List[str]:
        """
        Walk the listing page(s) and collect URLs that look like individual
        procurement detail pages.  Follows simple pagination up to
        ``max_listing_pages``.
        """
        detail_urls: List[str] = []
        visited_listing: Set[str] = set()
        pages_to_visit = [self.base_url]
        listing_pages_visited = 0

        while pages_to_visit and listing_pages_visited < self.max_listing_pages:
            page_url = pages_to_visit.pop(0)
            if page_url in visited_listing:
                continue
            visited_listing.add(page_url)
            listing_pages_visited += 1

            try:
                resp = self._rate_limited_get(page_url)
            except Exception as exc:
                logger.warning(
                    "[%s] Could not fetch listing page %s: %s",
                    self.agency_name,
                    page_url,
                    exc,
                )
                continue

            soup = BeautifulSoup(resp.text, "lxml")

            # Collect candidate detail links
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                abs_url = urljoin(page_url, href)
                text = a.get_text(strip=True)
                if (
                    abs_url not in visited_listing
                    and abs_url not in detail_urls
                    and _looks_like_procurement_link(href, text, self._base_netloc)
                ):
                    detail_urls.append(abs_url)

            # Follow pagination: look for 「次へ」 / 「次のページ」 / "next" links
            next_link = soup.find(
                "a", string=re.compile(r"次[へのページ]|next", re.IGNORECASE)
            )
            if not next_link:
                # Also check common CSS patterns
                next_link = soup.select_one("a.next, a[rel='next'], .pagination a.active + a")
            if next_link and next_link.get("href"):
                next_url = urljoin(page_url, next_link["href"])
                if next_url not in visited_listing:
                    pages_to_visit.append(next_url)

        # Deduplicate preserving order
        seen: Set[str] = set()
        unique: List[str] = []
        for u in detail_urls:
            if u not in seen:
                seen.add(u)
                unique.append(u)
        return unique

    def _parse_detail_page(self, url: str) -> Optional[ProcurementRecord]:
        """
        Fetch a detail page and extract a ProcurementRecord with PDF links.
        Returns None if the page cannot be fetched or yields no useful data.
        """
        try:
            resp = self._rate_limited_get(url)
        except Exception as exc:
            logger.warning("[%s] Failed to fetch %s: %s", self.agency_name, url, exc)
            return None

        soup = BeautifulSoup(resp.text, "lxml")

        # Title: try common selectors
        title = ""
        for selector in ["h1", "h2", ".entry-title", ".page-title", "title"]:
            el = soup.select_one(selector)
            if el:
                title = el.get_text(strip=True)
                break
        if not title:
            title = url.rstrip("/").split("/")[-1] or url

        # Date from page text
        page_text = soup.get_text(" ", strip=True)
        date = _extract_date(page_text)

        record = ProcurementRecord(
            id=ProcurementRecord.make_id(url, title),
            title=title,
            agency=self.agency_name,
            date=date,
            url=url,
        )

        # Collect PDF links and classify them
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            abs_url = urljoin(url, href)
            if not abs_url.lower().endswith(".pdf"):
                continue

            link_text = a.get_text(strip=True)
            parent = a.parent
            context = parent.get_text(" ", strip=True) if parent else ""

            doc_type = classify_url(abs_url, link_text=link_text, context_text=context)
            if doc_type == DocType.OTHER:
                continue

            filename = extract_filename_from_url(abs_url)
            record.documents.append(
                DocumentLink(
                    url=abs_url,
                    text=link_text,
                    doc_type=doc_type.value,
                    filename=filename,
                    context_text=context[:200],
                )
            )

        return record
