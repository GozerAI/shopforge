"""RFM-based customer segmentation.

Computes Recency, Frequency, Monetary scores for each customer and assigns
them to configurable segments (e.g., VIP, Loyal, At-Risk, New, Dormant).
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class RFMScore:
    """Recency-Frequency-Monetary scores for a customer."""
    customer_id: str
    recency_days: float
    frequency: int
    monetary: float
    r_score: int = 0
    f_score: int = 0
    m_score: int = 0

    @property
    def rfm_score(self) -> int:
        return self.r_score + self.f_score + self.m_score

    def to_dict(self) -> Dict[str, Any]:
        return {
            "customer_id": self.customer_id,
            "recency_days": round(self.recency_days, 1),
            "frequency": self.frequency,
            "monetary": round(self.monetary, 2),
            "r_score": self.r_score,
            "f_score": self.f_score,
            "m_score": self.m_score,
            "rfm_score": self.rfm_score,
        }


@dataclass
class CustomerSegment:
    """Definition of a customer segment."""
    name: str
    min_rfm: int
    max_rfm: int
    description: str = ""

    def contains(self, rfm_score: int) -> bool:
        return self.min_rfm <= rfm_score <= self.max_rfm


@dataclass
class SegmentationResult:
    """Full segmentation output for a customer."""
    customer_id: str
    rfm: RFMScore
    segment: str
    segment_description: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "customer_id": self.customer_id,
            "rfm": self.rfm.to_dict(),
            "segment": self.segment,
            "segment_description": self.segment_description,
        }


DEFAULT_SEGMENTS: List[CustomerSegment] = [
    CustomerSegment("VIP", 13, 15, "High-value power buyers"),
    CustomerSegment("Loyal", 10, 12, "Consistent repeat customers"),
    CustomerSegment("Promising", 7, 9, "Growing engagement"),
    CustomerSegment("At-Risk", 4, 6, "Previously active, declining engagement"),
    CustomerSegment("Dormant", 0, 3, "Inactive or minimal engagement"),
]


class CustomerSegmenter:
    """Segments customers using RFM analysis.

    Divides each metric into quintiles (1-5), sums R+F+M for a composite
    score (3-15), then maps to named segments.
    """

    def __init__(self, segments: Optional[List[CustomerSegment]] = None,
                 quintiles: int = 5):
        self._segments = segments or DEFAULT_SEGMENTS
        self._quintiles = quintiles

    def _assign_quintile(self, values: List[float], reverse: bool = False) -> List[int]:
        """Split sorted values into quintile buckets (1=worst, 5=best).

        For recency, lower is better so reverse=True inverts the scoring.
        """
        if not values:
            return []
        indexed = sorted(enumerate(values), key=lambda x: x[1])
        n = len(indexed)
        scores = [0] * n
        for rank, (orig_idx, _) in enumerate(indexed):
            bucket = int(rank / n * self._quintiles) + 1
            bucket = min(bucket, self._quintiles)
            if reverse:
                bucket = self._quintiles + 1 - bucket
            scores[orig_idx] = bucket
        return scores

    def _find_segment(self, rfm_score: int) -> CustomerSegment:
        for seg in self._segments:
            if seg.contains(rfm_score):
                return seg
        return self._segments[-1]

    def compute_rfm(self, customers: List[Dict[str, Any]],
                    reference_date: Optional[datetime] = None) -> List[RFMScore]:
        """Compute RFM scores for a list of customers.

        Each customer dict must have:
          - customer_id: str
          - last_order_date: datetime
          - order_count: int
          - total_spent: float
        """
        if not customers:
            return []

        if reference_date is None:
            reference_date = datetime.now(timezone.utc)

        rfm_list: List[RFMScore] = []
        for c in customers:
            last_order = c["last_order_date"]
            if last_order.tzinfo is None:
                last_order = last_order.replace(tzinfo=timezone.utc)
            recency = (reference_date - last_order).total_seconds() / 86400.0
            rfm_list.append(RFMScore(
                customer_id=c["customer_id"],
                recency_days=max(0.0, recency),
                frequency=c["order_count"],
                monetary=c["total_spent"],
            ))

        recency_vals = [r.recency_days for r in rfm_list]
        freq_vals = [float(r.frequency) for r in rfm_list]
        monetary_vals = [r.monetary for r in rfm_list]

        r_scores = self._assign_quintile(recency_vals, reverse=True)
        f_scores = self._assign_quintile(freq_vals)
        m_scores = self._assign_quintile(monetary_vals)

        for i, rfm in enumerate(rfm_list):
            rfm.r_score = r_scores[i]
            rfm.f_score = f_scores[i]
            rfm.m_score = m_scores[i]

        return rfm_list

    def segment(self, customers: List[Dict[str, Any]],
                reference_date: Optional[datetime] = None) -> List[SegmentationResult]:
        """Full segmentation pipeline: compute RFM then assign segments."""
        rfm_list = self.compute_rfm(customers, reference_date)
        results: List[SegmentationResult] = []
        for rfm in rfm_list:
            seg = self._find_segment(rfm.rfm_score)
            results.append(SegmentationResult(
                customer_id=rfm.customer_id,
                rfm=rfm,
                segment=seg.name,
                segment_description=seg.description,
            ))
        return results

    def segment_summary(self, results: List[SegmentationResult]) -> Dict[str, int]:
        """Count customers per segment."""
        counts: Dict[str, int] = {}
        for r in results:
            counts[r.segment] = counts.get(r.segment, 0) + 1
        return counts
