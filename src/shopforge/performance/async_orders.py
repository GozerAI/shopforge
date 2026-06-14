"""Async order processing pipeline.

Multi-stage order processing: validation -> inventory reservation ->
payment capture -> fulfillment dispatch. Supports retry and dead-letter.
"""

import logging
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class OrderTaskStatus(Enum):
    """Status of an order processing task."""
    PENDING = "pending"
    VALIDATING = "validating"
    RESERVING = "reserving"
    CAPTURING = "capturing"
    DISPATCHING = "dispatching"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


@dataclass
class OrderTask:
    """Represents an order being processed through the pipeline."""
    id: str = field(default_factory=lambda: str(uuid4()))
    order_data: Dict[str, Any] = field(default_factory=dict)
    status: OrderTaskStatus = OrderTaskStatus.PENDING
    stage: str = "pending"
    attempt: int = 0
    max_retries: int = 3
    errors: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status.value,
            "stage": self.stage,
            "attempt": self.attempt,
            "max_retries": self.max_retries,
            "errors": self.errors,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


@dataclass
class PipelineStats:
    """Aggregated pipeline statistics."""
    total_submitted: int = 0
    total_completed: int = 0
    total_failed: int = 0
    total_dead_letter: int = 0
    active_tasks: int = 0
    avg_duration_seconds: float = 0.0
    _durations: List[float] = field(default_factory=list, repr=False)

    def record_duration(self, duration: float) -> None:
        self._durations.append(duration)
        self.avg_duration_seconds = sum(self._durations) / len(self._durations)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_submitted": self.total_submitted,
            "total_completed": self.total_completed,
            "total_failed": self.total_failed,
            "total_dead_letter": self.total_dead_letter,
            "active_tasks": self.active_tasks,
            "avg_duration_seconds": round(self.avg_duration_seconds, 4),
        }


# Default pipeline stage handlers

def _default_validate(order_data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate order has required fields."""
    required = ["customer_email", "line_items"]
    missing = [f for f in required if f not in order_data or not order_data[f]]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")
    items = order_data["line_items"]
    if not isinstance(items, list) or len(items) == 0:
        raise ValueError("line_items must be a non-empty list")
    for idx, item in enumerate(items):
        if "product_id" not in item:
            raise ValueError(f"line_items[{idx}] missing product_id")
        if item.get("quantity", 0) <= 0:
            raise ValueError(f"line_items[{idx}] has invalid quantity")
    return {"validated": True}


def _default_reserve(order_data: Dict[str, Any]) -> Dict[str, Any]:
    """Reserve inventory (stub — always succeeds)."""
    return {"reserved": True, "items": len(order_data.get("line_items", []))}


def _default_capture(order_data: Dict[str, Any]) -> Dict[str, Any]:
    """Capture payment (stub — always succeeds)."""
    total = sum(
        item.get("price", 0) * item.get("quantity", 1)
        for item in order_data.get("line_items", [])
    )
    return {"captured": True, "amount": total}


def _default_dispatch(order_data: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch fulfillment (stub — always succeeds)."""
    return {"dispatched": True}


_STAGES = [
    ("validating", OrderTaskStatus.VALIDATING, _default_validate),
    ("reserving", OrderTaskStatus.RESERVING, _default_reserve),
    ("capturing", OrderTaskStatus.CAPTURING, _default_capture),
    ("dispatching", OrderTaskStatus.DISPATCHING, _default_dispatch),
]


class AsyncOrderPipeline:
    """Multi-stage order processing pipeline with retry and dead-letter support.

    Orders flow through: validation -> inventory reservation ->
    payment capture -> fulfillment dispatch.

    Each stage can be overridden with custom handlers.
    """

    def __init__(
        self,
        max_retries: int = 3,
        validators: Optional[List[Callable[[Dict[str, Any]], Dict[str, Any]]]] = None,
        on_complete: Optional[Callable[[OrderTask], None]] = None,
        on_fail: Optional[Callable[[OrderTask], None]] = None,
    ):
        self._max_retries = max_retries
        self._tasks: Dict[str, OrderTask] = {}
        self._dead_letter: List[OrderTask] = []
        self._lock = threading.Lock()
        self._stats = PipelineStats()
        self._on_complete = on_complete
        self._on_fail = on_fail

        # Stage handlers (overridable)
        self._stage_handlers: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
            "validating": _default_validate,
            "reserving": _default_reserve,
            "capturing": _default_capture,
            "dispatching": _default_dispatch,
        }

        # Extra validators run during validation stage
        self._validators = validators or []

    def set_stage_handler(
        self, stage: str, handler: Callable[[Dict[str, Any]], Dict[str, Any]]
    ) -> None:
        """Override a pipeline stage handler."""
        if stage not in self._stage_handlers:
            raise ValueError(f"Unknown stage: {stage}. Valid: {list(self._stage_handlers)}")
        self._stage_handlers[stage] = handler

    def submit(self, order_data: Dict[str, Any]) -> str:
        """Submit an order for processing. Returns the task ID."""
        task = OrderTask(
            order_data=order_data,
            max_retries=self._max_retries,
        )
        with self._lock:
            self._tasks[task.id] = task
            self._stats.total_submitted += 1
            self._stats.active_tasks += 1

        self._process_task(task)
        return task.id

    def get_task(self, task_id: str) -> Optional[OrderTask]:
        """Get a task by ID."""
        with self._lock:
            return self._tasks.get(task_id)

    def get_status(self, task_id: str) -> Optional[OrderTaskStatus]:
        """Get the status of a task."""
        task = self.get_task(task_id)
        return task.status if task else None

    def get_stats(self) -> PipelineStats:
        """Return pipeline statistics snapshot."""
        with self._lock:
            return PipelineStats(
                total_submitted=self._stats.total_submitted,
                total_completed=self._stats.total_completed,
                total_failed=self._stats.total_failed,
                total_dead_letter=self._stats.total_dead_letter,
                active_tasks=self._stats.active_tasks,
                avg_duration_seconds=self._stats.avg_duration_seconds,
                _durations=list(self._stats._durations),
            )

    def get_dead_letter_tasks(self) -> List[OrderTask]:
        """Return tasks that exhausted all retries."""
        with self._lock:
            return list(self._dead_letter)

    def retry_dead_letter(self, task_id: str) -> bool:
        """Re-submit a dead-letter task for processing."""
        with self._lock:
            task = None
            for t in self._dead_letter:
                if t.id == task_id:
                    task = t
                    break
            if not task:
                return False
            self._dead_letter.remove(task)
            task.status = OrderTaskStatus.PENDING
            task.stage = "pending"
            task.attempt = 0
            task.errors.clear()
            self._stats.total_dead_letter -= 1
            self._stats.active_tasks += 1

        self._process_task(task)
        return True

    def list_tasks(
        self, status: Optional[OrderTaskStatus] = None
    ) -> List[OrderTask]:
        """List tasks, optionally filtered by status."""
        with self._lock:
            tasks = list(self._tasks.values())
        if status is not None:
            tasks = [t for t in tasks if t.status == status]
        return tasks

    def _process_task(self, task: OrderTask) -> None:
        """Run the task through all pipeline stages."""
        start = time.monotonic()
        stages = [
            ("validating", OrderTaskStatus.VALIDATING),
            ("reserving", OrderTaskStatus.RESERVING),
            ("capturing", OrderTaskStatus.CAPTURING),
            ("dispatching", OrderTaskStatus.DISPATCHING),
        ]

        for stage_name, stage_status in stages:
            task.stage = stage_name
            task.status = stage_status
            task.updated_at = datetime.now(timezone.utc)

            handler = self._stage_handlers[stage_name]
            success = False

            for attempt in range(task.max_retries):
                task.attempt = attempt + 1
                try:
                    result = handler(task.order_data)

                    # Run extra validators during validation stage
                    if stage_name == "validating":
                        for validator in self._validators:
                            validator(task.order_data)

                    if task.result is None:
                        task.result = {}
                    task.result[stage_name] = result
                    success = True
                    break
                except Exception as e:
                    error_msg = f"Stage '{stage_name}' attempt {attempt + 1}: {e}"
                    task.errors.append(error_msg)
                    logger.warning(error_msg)

            if not success:
                task.status = OrderTaskStatus.FAILED
                task.updated_at = datetime.now(timezone.utc)
                duration = time.monotonic() - start
                with self._lock:
                    self._stats.active_tasks -= 1
                    self._stats.total_failed += 1
                    self._stats.record_duration(duration)
                    # Move to dead letter
                    task.status = OrderTaskStatus.DEAD_LETTER
                    self._dead_letter.append(task)
                    self._stats.total_dead_letter += 1
                if self._on_fail:
                    self._on_fail(task)
                return

        # All stages passed
        task.status = OrderTaskStatus.COMPLETED
        task.completed_at = datetime.now(timezone.utc)
        task.updated_at = task.completed_at
        duration = time.monotonic() - start

        with self._lock:
            self._stats.active_tasks -= 1
            self._stats.total_completed += 1
            self._stats.record_duration(duration)

        if self._on_complete:
            self._on_complete(task)
