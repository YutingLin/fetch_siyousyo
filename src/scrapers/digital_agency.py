"""
Scraper for デジタル庁 (Digital Agency of Japan) procurement page.

Entry point: https://www.digital.go.jp/procurement/
"""

import logging
import re
from typing import List, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from src.classifier import DocType, classify_url, extract_filename_from_url
from src.scrapers.base import BaseScraper, DocumentLink, ProcurementRecord

logger = logging.getLogger(__name__)

BASE_URL = "https://www.digital.go.jp/procurement/"
AGENCY_NAME = "デジタル庁"

# Pattern to extract ISO date from text like "2024年03月15日" or "2024-03-15"
_DATE_PATTERNS = [
    re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日"),
    re.compile(r"(\d{4})-(\d{2})-(\d{2})"),
    re.compile(r"(\d{4})/(\d{2})/(\d{2})"),
]


def _extract_date(text: str) -> str:
    """Extract the first date found in text and return YYYY-MM-DD."""
    for pat in _DATE_PATTERNS:
        m = pat.search(text)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return ""


def _is_procurement_link(href: str, text: str) -> bool:
    """Heuristic: is this link pointing to an individual procurement page?"""
    if not href:
        return False
    # Skip external links, anchors, javascript
    if href.startswith("#") or href.startswith("javascript"):
        return False
    # Must stay within digital.go.jp
    parsed = urlparse(href)
    if parsed.netloc and "digital.go.jp" not in parsed.netloc:
        return False
    # Procurement detail pages often have these path patterns
    path = parsed.path.lower()
    procurement_patterns = [
        "/procurement/",
        "/chotatsu/",
        "/bid/",
    ]
    for pat in procurement_patterns:
        if pat in path:
            return True
    return False


class DigitalAgencyScraper(BaseScraper):
    """Scraper for デジタル庁 procurement listings."""

    def __init__(self):
        super().__init__(source_name="digital_agency", base_url=BASE_URL)

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
        Scrape the デジタル庁 procurement listing and return matching records.
        """
        records: List[ProcurementRecord] = []

        listing_urls = self._collect_listing_urls()
        logger.info("Found %d procurement listing URLs", len(listing_urls))

        for url in listing_urls:
            try:
                record = self._parse_procurement_page(url)
                if record is None:
                    continue
                if not self._record_matches_keywords(record, keywords):
                    continue
                if not self._record_in_date_range(record, date_from, date_to):
                    continue
                records.append(record)
            except Exception as exc:
                logger.warning("Failed to parse %s: %s", url, exc)

        logger.info("Returning %d matching records from デジタル庁", len(records))
        return records

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _collect_listing_urls(self) -> List[str]:
        """
        Fetch the main procurement page and collect links to individual
        procurement records.  Also follows simple pagination.
        """
        urls: List[str] = []
        visited: set = set()

        pages_to_visit = [self.base_url]

        while pages_to_visit:
            page_url = pages_to_visit.pop(0)
            if page_url in visited:
                continue
            visited.add(page_url)

            try:
                resp = self._rate_limited_get(page_url)
            except Exception as exc:
                logger.warning("Could not fetch listing page %s: %s", page_url, exc)
                continue

            soup = BeautifulSoup(resp.text, "lxml")

            # Collect procurement detail links
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                abs_url = urljoin(page_url, href)
                text = a.get_text(strip=True)

                if abs_url not in visited and _is_procurement_link(abs_url, text):
                    # Only add if it looks like a detail page (deeper path)
                    if abs_url != self.base_url:
                        urls.append(abs_url)

            # Pagination: look for 「次へ」 or 「次のページ」 links
            next_link = soup.find("a", string=re.compile(r"次[へのページ]|next", re.I))
            if next_link and next_link.get("href"):
                next_url = urljoin(page_url, next_link["href"])
                if next_url not in visited:
                    pages_to_visit.append(next_url)

        # Deduplicate while preserving order
        seen: set = set()
        unique: List[str] = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                unique.append(u)
        return unique

    def _parse_procurement_page(self, url: str) -> Optional[ProcurementRecord]:
        """
        Parse an individual procurement detail page and return a ProcurementRecord.
        """
        try:
            resp = self._rate_limited_get(url)
        except Exception as exc:
            logger.warning("Failed to fetch %s: %s", url, exc)
            return None

        soup = BeautifulSoup(resp.text, "lxml")

        # Extract title
        title = ""
        for selector in ["h1", "h2", ".entry-title", ".page-title", "title"]:
            el = soup.select_one(selector)
            if el:
                title = el.get_text(strip=True)
                break
        if not title:
            title = url.split("/")[-2] or url

        # Extract date from page text
        page_text = soup.get_text(" ", strip=True)
        date = _extract_date(page_text)

        record = ProcurementRecord(
            id=ProcurementRecord.make_id(url, title),
            title=title,
            agency=AGENCY_NAME,
            date=date,
            url=url,
        )

        # Find all PDF links on the page
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            abs_url = urljoin(url, href)
            if not abs_url.lower().endswith(".pdf"):
                continue

            link_text = a.get_text(strip=True)
            # Gather surrounding context (parent element text)
            parent = a.parent
            context = parent.get_text(" ", strip=True) if parent else ""

            doc_type = classify_url(abs_url, link_text=link_text, context_text=context)
            if doc_type == DocType.OTHER:
                continue  # Skip unwanted document types

            filename = extract_filename_from_url(abs_url)
            doc = DocumentLink(
                url=abs_url,
                text=link_text,
                doc_type=doc_type.value,
                filename=filename,
                context_text=context[:200],
            )
            record.documents.append(doc)

        return record
