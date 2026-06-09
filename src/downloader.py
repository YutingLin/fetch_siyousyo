"""
Downloads PDFs from procurement pages and stores them with structured paths.

Save structure:
  output_dir/<source>/<project_id>/<doc_type>_<filename>.pdf

Returns a metadata dict per download.
"""

import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import (
    MAX_RETRIES,
    REQUEST_DELAY,
    REQUEST_TIMEOUT,
    RETRY_BACKOFF_FACTOR,
    USER_AGENT,
)

logger = logging.getLogger(__name__)


def _build_session() -> requests.Session:
    """Build a requests.Session with retry logic."""
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


# Module-level shared session
_session: Optional[requests.Session] = None


def get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = _build_session()
    return _session


def _sanitize_path_component(s: str) -> str:
    """Remove characters unsafe for file/directory names."""
    s = re.sub(r'[\\/:*?"<>|]', "_", s)
    s = re.sub(r"\s+", "_", s)
    return s[:80]  # cap length


def download_pdf(
    url: str,
    source: str,
    project_id: str,
    doc_type: str,
    output_dir: str,
    referer: str = "",
    delay: float = REQUEST_DELAY,
) -> dict:
    """
    Download a PDF to output_dir/<source>/<project_id>/<doc_type>_<filename>.pdf.

    Parameters
    ----------
    url : str
        Full URL of the PDF.
    source : str
        Source identifier (e.g., 'digital_agency').
    project_id : str
        Procurement record identifier used as sub-directory.
    doc_type : str
        '仕様書' or '提案書' — prepended to the filename.
    output_dir : str
        Root directory for downloads.
    referer : str
        Referer URL to set in request headers.
    delay : float
        Seconds to sleep before the request (rate limiting).

    Returns
    -------
    dict
        Metadata: url, local_path, size, downloaded_at, success, error.
    """
    session = get_session()

    parsed = urlparse(url)
    filename = os.path.basename(parsed.path) or "document.pdf"
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"

    safe_source = _sanitize_path_component(source)
    safe_project = _sanitize_path_component(project_id)
    safe_type = _sanitize_path_component(doc_type)
    safe_filename = _sanitize_path_component(filename)

    dest_dir = os.path.join(output_dir, safe_source, safe_project)
    os.makedirs(dest_dir, exist_ok=True)

    local_filename = f"{safe_type}_{safe_filename}"
    local_path = os.path.join(dest_dir, local_filename)

    meta = {
        "url": url,
        "local_path": local_path,
        "size": 0,
        "downloaded_at": None,
        "success": False,
        "error": None,
    }

    # Rate limiting
    if delay > 0:
        time.sleep(delay)

    headers = {}
    if referer:
        headers["Referer"] = referer

    try:
        response = session.get(
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
            stream=True,
        )
        response.raise_for_status()

        total = 0
        with open(local_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    total += len(chunk)

        meta["size"] = total
        meta["downloaded_at"] = datetime.now(timezone.utc).isoformat()
        meta["success"] = True
        logger.info("Downloaded %s -> %s (%d bytes)", url, local_path, total)

    except requests.RequestException as exc:
        meta["error"] = str(exc)
        logger.error("Failed to download %s: %s", url, exc)

    return meta
