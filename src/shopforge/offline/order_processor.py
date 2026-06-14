"""Offline order processing with queue and sync.

Queues orders locally when connectivity is unavailable, then syncs them
in batch when connection is restored. Supports conflict detection.
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class OfflineOrderStatus(str, Enum):
    QUEUED = "queued"
    SYNCING = "syncing"
    SYNCED = "synced"
    CONFLICT = "conflict"
    FAILED = "failed"


@dataclass
class OfflineOrder:
    """An order captured offline."""
    order_id: str = field(default_factory=lambda: str(uuid4()))
    customer_id: str = ""
    items: List[Dict[str, Any]] = field(default_factory=list)
    total: float = 0.0
    status: OfflineOrderStatus = OfflineOrderStatus.QUEUED
    created_at: float = field(default_factory=time.time)
    synced_at: Optional[float] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order_id": self.order_id,
            "customer_id": self.customer_id,
            "items": self.items,
            "total": round(self.total, 2),
            "status": self.status.value,
            "created_at": self.created_at,
            "synced_at": self.synced_at,
            "error": self.error,
        }


@dataclass
class SyncResult:
    """Result of syncing offline orders."""
    total: int = 0
    synced: int = 0
    conflicts: int = 0
    failed: int = 0
    errors: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "synced": self.synced,
            "conflicts": self.conflicts,
            "failed": self.failed,
            "errors": self.errors,
        }


class OfflineOrderProcessor:
    """Queues and syncs orders for offline-first commerce.

    Orders are captured locally and synced when a sync_fn callback is provided.
    The sync_fn receives an OfflineOrder and should return True on success,
    raise ValueError for conflicts, or raise Exception for failures.
    """

    def __init__(self, sync_fn: Optional[Callable[[OfflineOrder], bool]] = None):
        self._queue: List[OfflineOrder] = []
        self._synced: List[OfflineOrder] = []
        self._sync_fn = sync_fn

    def set_sync_fn(self, fn: Callable[[OfflineOrder], bool]) -> None:
        self._sync_fn = fn

    def capture(self, customer_id: str, items: List[Dict[str, Any]],
                total: Optional[float] = None,
                metadata: Optional[Dict[str, Any]] = None) -> OfflineOrder:
        """Capture an order offline."""
        if total is None:
            total = sum(
                item.get("price", 0.0) * item.get("quantity", 1)
                for item in items
            )
        order = OfflineOrder(
            customer_id=customer_id,
            items=items,
            total=total,
            metadata=metadata or {},
        )
        self._queue.append(order)
        logger.info("Captured offline order %s (total=%.2f)", order.order_id, order.total)
        return order

    @property
    def queue_size(self) -> int:
        return len(self._queue)

    @property
    def synced_count(self) -> int:
        return len(self._synced)

    def pending_orders(self) -> List[OfflineOrder]:
        return [o for o in self._queue if o.status == OfflineOrderStatus.QUEUED]

    def sync(self) -> SyncResult:
        """Attempt to sync all queued orders using the sync_fn."""
        if self._sync_fn is None:
            raise RuntimeError("No sync_fn configured. Call set_sync_fn() first.")

        result = SyncResult(total=len(self._queue))
        remaining: List[OfflineOrder] = []

        for order in self._queue:
            if order.status != OfflineOrderStatus.QUEUED:
                remaining.append(order)
                continue
            order.status = OfflineOrderStatus.SYNCING
            try:
                success = self._sync_fn(order)
                if success:
                    order.status = OfflineOrderStatus.SYNCED
                    order.synced_at = time.time()
                    self._synced.append(order)
                    result.synced += 1
                else:
                    order.status = OfflineOrderStatus.FAILED
                    order.error = "sync_fn returned False"
                    remaining.append(order)
                    result.failed += 1
                    result.errors.append({
                        "order_id": order.order_id, "error": order.error,
                    })
            except ValueError as e:
                order.status = OfflineOrderStatus.CONFLICT
                order.error = str(e)
                remaining.append(order)
                result.conflicts += 1
                result.errors.append({
                    "order_id": order.order_id, "error": f"conflict: {e}",
                })
            except Exception as e:
                order.status = OfflineOrderStatus.FAILED
                order.error = str(e)
                remaining.append(order)
                result.failed += 1
                result.errors.append({
                    "order_id": order.order_id, "error": str(e),
                })

        self._queue = remaining
        logger.info("Sync complete: %d synced, %d conflicts, %d failed",
                     result.synced, result.conflicts, result.failed)
        return result

    def retry_failed(self) -> int:
        """Re-queue failed orders for another sync attempt. Returns count re-queued."""
        count = 0
        for order in self._queue:
            if order.status in (OfflineOrderStatus.FAILED, OfflineOrderStatus.CONFLICT):
                order.status = OfflineOrderStatus.QUEUED
                order.error = None
                count += 1
        return count

    def clear_synced(self) -> int:
        """Clear synced order history. Returns count cleared."""
        count = len(self._synced)
        self._synced.clear()
        return count
