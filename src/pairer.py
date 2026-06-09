"""
Pairs 仕様書 and 提案書 documents within each ProcurementRecord.

For each record:
- Collect all SHIYOUSHO documents → 仕様書 list
- Collect all TEIAN documents   → 提案書 list
- A "complete pair" has at least one of each.
- An "incomplete pair" has only 仕様書 (no 提案書 found yet).
- Records with neither are excluded from output.

Returns a list of PairedRecord dataclasses.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from src.scrapers.base import DocumentLink, ProcurementRecord


@dataclass
class PairedRecord:
    """
    A procurement record with its 仕様書 / 提案書 documents grouped.

    Attributes
    ----------
    record : ProcurementRecord
        The source procurement record (id, title, agency, date, url).
    shiyousho : list[DocumentLink]
        All classified 仕様書 documents.
    teian : list[DocumentLink]
        All classified 提案書 documents.
    is_complete_pair : bool
        True if both 仕様書 and 提案書 are present.
    """

    record: ProcurementRecord
    shiyousho: List[DocumentLink] = field(default_factory=list)
    teian: List[DocumentLink] = field(default_factory=list)
    is_complete_pair: bool = False

    def to_dict(self) -> dict:
        """Serialise to a plain dict (JSON-compatible)."""
        return {
            "id": self.record.id,
            "title": self.record.title,
            "agency": self.record.agency,
            "date": self.record.date,
            "url": self.record.url,
            "is_complete_pair": self.is_complete_pair,
            "shiyousho": [_doc_to_dict(d) for d in self.shiyousho],
            "teian": [_doc_to_dict(d) for d in self.teian],
        }


def _doc_to_dict(doc: DocumentLink) -> dict:
    return {
        "url": doc.url,
        "text": doc.text,
        "doc_type": doc.doc_type,
        "filename": doc.filename,
        "context_text": doc.context_text,
    }


def pair_documents(records: List[ProcurementRecord]) -> List[PairedRecord]:
    """
    Group documents in each ProcurementRecord into 仕様書 / 提案書 pairs.

    Parameters
    ----------
    records : list[ProcurementRecord]
        Raw procurement records from a scraper.

    Returns
    -------
    list[PairedRecord]
        Records that have at least one 仕様書 document.
        Records with only 提案書 (no 仕様書) are excluded — those are
        typically standalone response documents without a spec.
    """
    paired: List[PairedRecord] = []

    for record in records:
        shiyousho = [d for d in record.documents if d.doc_type == "仕様書"]
        teian = [d for d in record.documents if d.doc_type == "提案書"]

        # Only include records that have at least a 仕様書
        if not shiyousho:
            continue

        paired.append(
            PairedRecord(
                record=record,
                shiyousho=shiyousho,
                teian=teian,
                is_complete_pair=len(teian) > 0,
            )
        )

    return paired


def summarise_pairs(paired_records: List[PairedRecord]) -> dict:
    """
    Return a summary dict suitable for display or logging.
    """
    total = len(paired_records)
    complete = sum(1 for p in paired_records if p.is_complete_pair)
    incomplete = total - complete
    shiyousho_count = sum(len(p.shiyousho) for p in paired_records)
    teian_count = sum(len(p.teian) for p in paired_records)

    return {
        "total_records": total,
        "complete_pairs": complete,
        "shiyousho_only": incomplete,
        "total_shiyousho_docs": shiyousho_count,
        "total_teian_docs": teian_count,
    }
