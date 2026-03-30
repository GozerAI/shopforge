"""Batch import for bulk product and order ingestion.

Processes large datasets in configurable chunks with validation,
progress callbacks, and detailed error reporting.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class ImportJobStatus(Enum):
    """Status of a batch import job."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"


@dataclass
class ImportJob:
    """Tracks a batch import operation."""
    id: str = field(default_factory=lambda: str(uuid4()))
    job_type: str = ""  # "products" or "orders"
    status: ImportJobStatus = ImportJobStatus.PENDING
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    errors: List[Dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    imported_ids: List[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        return (self.succeeded / self.total * 100) if self.total > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "job_type": self.job_type,
            "status": self.status.value,
            "total": self.total,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "error_count": len(self.errors),
            "success_rate": round(self.success_rate, 2),
            "duration_seconds": round(self.duration_seconds, 4),
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


@dataclass
class ExportJob:
    """Tracks a batch export operation."""
    id: str = field(default_factory=lambda: str(uuid4()))
    job_type: str = ""
    status: ImportJobStatus = ImportJobStatus.PENDING
    total: int = 0
    exported: int = 0
    errors: List[Dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    output_records: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "job_type": self.job_type,
            "status": self.status.value,
            "total": self.total,
            "exported": self.exported,
            "error_count": len(self.errors),
            "duration_seconds": round(self.duration_seconds, 4),
        }


# Required fields for validation
_PRODUCT_REQUIRED = ["title"]
_ORDER_REQUIRED = ["customer_email", "line_items"]


def _validate_product(item: Dict[str, Any], index: int) -> Optional[str]:
    """Validate a product dict. Returns error message or None."""
    for fld in _PRODUCT_REQUIRED:
        if fld not in item or not item[fld]:
            return f"Item {index}: missing required field '{fld}'"
    title = item.get("title", "")
    if not isinstance(title, str) or len(title.strip()) == 0:
        return f"Item {index}: 'title' must be a non-empty string"
    price = item.get("price")
    if price is not None:
        try:
            p = float(price)
            if p < 0:
                return f"Item {index}: 'price' cannot be negative"
        except (ValueError, TypeError):
            return f"Item {index}: 'price' must be a number"
    return None


def _validate_order(item: Dict[str, Any], index: int) -> Optional[str]:
    """Validate an order dict. Returns error message or None."""
    for fld in _ORDER_REQUIRED:
        if fld not in item or not item[fld]:
            return f"Item {index}: missing required field '{fld}'"
    email = item.get("customer_email", "")
    if not isinstance(email, str) or "@" not in email:
        return f"Item {index}: 'customer_email' must be a valid email"
    line_items = item.get("line_items", [])
    if not isinstance(line_items, list) or len(line_items) == 0:
        return f"Item {index}: 'line_items' must be a non-empty list"
    for li_idx, li in enumerate(line_items):
        if "product_id" not in li:
            return f"Item {index}: line_items[{li_idx}] missing 'product_id'"
    return None


class BatchImporter:
    """Bulk importer for products and orders with chunked processing.

    Validates each item, skips invalid ones, and reports errors.
    Supports progress callbacks for monitoring long-running imports.
    """

    def __init__(
        self,
        on_progress: Optional[Callable[[int, int, int], None]] = None,
        transform_product: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        transform_order: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    ):
        """
        Args:
            on_progress: Callback(processed, succeeded, total) called after each batch.
            transform_product: Optional transform applied to each valid product before import.
            transform_order: Optional transform applied to each valid order before import.
        """
        self._on_progress = on_progress
        self._transform_product = transform_product
        self._transform_order = transform_order
        self._jobs: Dict[str, ImportJob] = {}
        self._export_jobs: Dict[str, ExportJob] = {}

    def import_products(
        self,
        items: List[Dict[str, Any]],
        batch_size: int = 100,
    ) -> ImportJob:
        """Import products in batches with validation.

        Args:
            items: List of product dicts to import.
            batch_size: Number of items per processing chunk.

        Returns:
            ImportJob with results and error details.
        """
        job = ImportJob(job_type="products", total=len(items))
        job.status = ImportJobStatus.RUNNING
        self._jobs[job.id] = job
        start = time.monotonic()

        for batch_start in range(0, len(items), batch_size):
            batch = items[batch_start: batch_start + batch_size]
            for offset, item in enumerate(batch):
                idx = batch_start + offset
                error = _validate_product(item, idx)
                if error:
                    job.failed += 1
                    job.errors.append({"index": idx, "error": error})
                    continue

                # Apply optional transform
                if self._transform_product:
                    try:
                        item = self._transform_product(item)
                    except Exception as e:
                        job.failed += 1
                        job.errors.append({"index": idx, "error": f"Transform failed: {e}"})
                        continue

                # "Import" the item — assign an ID if missing
                item_id = item.get("id") or str(uuid4())
                item["id"] = item_id
                job.succeeded += 1
                job.imported_ids.append(item_id)

            if self._on_progress:
                processed = min(batch_start + batch_size, len(items))
                self._on_progress(processed, job.succeeded, job.total)

        job.duration_seconds = time.monotonic() - start
        job.completed_at = datetime.now(timezone.utc)
        job.status = (
            ImportJobStatus.COMPLETED if job.failed == 0
            else ImportJobStatus.COMPLETED_WITH_ERRORS
        )
        return job

    def import_orders(
        self,
        items: List[Dict[str, Any]],
        batch_size: int = 50,
    ) -> ImportJob:
        """Import orders in batches with validation.

        Args:
            items: List of order dicts to import.
            batch_size: Number of items per processing chunk.

        Returns:
            ImportJob with results and error details.
        """
        job = ImportJob(job_type="orders", total=len(items))
        job.status = ImportJobStatus.RUNNING
        self._jobs[job.id] = job
        start = time.monotonic()

        for batch_start in range(0, len(items), batch_size):
            batch = items[batch_start: batch_start + batch_size]
            for offset, item in enumerate(batch):
                idx = batch_start + offset
                error = _validate_order(item, idx)
                if error:
                    job.failed += 1
                    job.errors.append({"index": idx, "error": error})
                    continue

                if self._transform_order:
                    try:
                        item = self._transform_order(item)
                    except Exception as e:
                        job.failed += 1
                        job.errors.append({"index": idx, "error": f"Transform failed: {e}"})
                        continue

                item_id = item.get("id") or str(uuid4())
                item["id"] = item_id
                job.succeeded += 1
                job.imported_ids.append(item_id)

            if self._on_progress:
                processed = min(batch_start + batch_size, len(items))
                self._on_progress(processed, job.succeeded, job.total)

        job.duration_seconds = time.monotonic() - start
        job.completed_at = datetime.now(timezone.utc)
        job.status = (
            ImportJobStatus.COMPLETED if job.failed == 0
            else ImportJobStatus.COMPLETED_WITH_ERRORS
        )
        return job

    def export_products(
        self,
        products: List[Dict[str, Any]],
        fields: Optional[List[str]] = None,
    ) -> ExportJob:
        """Export products, optionally filtering to specific fields.

        Args:
            products: List of product dicts to export.
            fields: If provided, only include these keys in output.

        Returns:
            ExportJob with output records.
        """
        export = ExportJob(job_type="products", total=len(products))
        export.status = ImportJobStatus.RUNNING
        self._export_jobs[export.id] = export
        start = time.monotonic()

        for item in products:
            try:
                if fields:
                    record = {k: item.get(k) for k in fields}
                else:
                    record = dict(item)
                export.output_records.append(record)
                export.exported += 1
            except Exception as e:
                export.errors.append({"error": str(e)})

        export.duration_seconds = time.monotonic() - start
        export.completed_at = datetime.now(timezone.utc)
        export.status = ImportJobStatus.COMPLETED
        return export

    def get_job(self, job_id: str) -> Optional[ImportJob]:
        """Retrieve an import job by ID."""
        return self._jobs.get(job_id)

    def get_export_job(self, job_id: str) -> Optional[ExportJob]:
        """Retrieve an export job by ID."""
        return self._export_jobs.get(job_id)
