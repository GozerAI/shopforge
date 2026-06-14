"""
Audit Log - Price change tracking and compliance.

Records all pricing changes with before/after values,
strategy used, and the actor who initiated the change.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


@dataclass
class AuditEntry:
    """Single audit log entry for a price change."""
    id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    product_id: str = ""
    variant_id: str = ""
    product_title: str = ""
    action: str = "price_change"  # price_change, strategy_change, bulk_update
    old_price: Optional[float] = None
    new_price: Optional[float] = None
    strategy: str = ""
    reason: str = ""
    actor: str = "system"  # system, executive code, api
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def price_change(self) -> Optional[float]:
        if self.old_price is not None and self.new_price is not None:
            return self.new_price - self.old_price
        return None

    @property
    def price_change_pct(self) -> Optional[float]:
        if self.old_price and self.new_price and self.old_price > 0:
            return ((self.new_price - self.old_price) / self.old_price) * 100
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "product_id": self.product_id,
            "variant_id": self.variant_id,
            "product_title": self.product_title,
            "action": self.action,
            "old_price": self.old_price,
            "new_price": self.new_price,
            "price_change": self.price_change,
            "price_change_pct": round(self.price_change_pct, 2) if self.price_change_pct is not None else None,
            "strategy": self.strategy,
            "reason": self.reason,
            "actor": self.actor,
        }


class AuditLog:
    """In-memory audit log with optional JSON file persistence."""

    def __init__(self, persist_path: Optional[str] = None, max_entries: int = 10000):
        self._entries: List[AuditEntry] = []
        self._max_entries = max_entries
        self._persist_path = Path(persist_path) if persist_path else None

        if self._persist_path and self._persist_path.exists():
            self._load()

    def record(
        self,
        product_id: str,
        product_title: str = "",
        variant_id: str = "",
        old_price: Optional[float] = None,
        new_price: Optional[float] = None,
        strategy: str = "",
        reason: str = "",
        actor: str = "system",
        action: str = "price_change",
        **metadata,
    ) -> AuditEntry:
        """Record a price change event."""
        entry = AuditEntry(
            product_id=product_id,
            variant_id=variant_id,
            product_title=product_title,
            action=action,
            old_price=old_price,
            new_price=new_price,
            strategy=strategy,
            reason=reason,
            actor=actor,
            metadata=metadata,
        )
        self._entries.append(entry)

        # Evict oldest if over limit
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries:]

        if self._persist_path:
            self._save()

        return entry

    def get_entries(
        self,
        product_id: Optional[str] = None,
        actor: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100,
    ) -> List[AuditEntry]:
        """Query audit entries with optional filters."""
        results = self._entries

        if product_id:
            results = [e for e in results if e.product_id == product_id]
        if actor:
            results = [e for e in results if e.actor == actor]
        if action:
            results = [e for e in results if e.action == action]

        return list(reversed(results[-limit:]))

    def get_summary(self) -> Dict[str, Any]:
        """Get audit log summary statistics."""
        if not self._entries:
            return {"total_entries": 0, "actions": {}, "actors": {}}

        actions: Dict[str, int] = {}
        actors: Dict[str, int] = {}
        total_increases = 0
        total_decreases = 0

        for entry in self._entries:
            actions[entry.action] = actions.get(entry.action, 0) + 1
            actors[entry.actor] = actors.get(entry.actor, 0) + 1
            if entry.price_change is not None:
                if entry.price_change > 0:
                    total_increases += 1
                elif entry.price_change < 0:
                    total_decreases += 1

        return {
            "total_entries": len(self._entries),
            "actions": actions,
            "actors": actors,
            "price_increases": total_increases,
            "price_decreases": total_decreases,
        }

    def clear(self) -> None:
        """Clear all entries."""
        self._entries.clear()

    def _save(self) -> None:
        """Persist entries to JSON file."""
        try:
            data = [e.to_dict() for e in self._entries]
            self._persist_path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.error(f"Failed to save audit log: {e}")

    def _load(self) -> None:
        """Load entries from JSON file."""
        try:
            data = json.loads(self._persist_path.read_text())
            for item in data:
                entry = AuditEntry(
                    id=item.get("id", str(uuid4())),
                    product_id=item.get("product_id", ""),
                    variant_id=item.get("variant_id", ""),
                    product_title=item.get("product_title", ""),
                    action=item.get("action", "price_change"),
                    old_price=item.get("old_price"),
                    new_price=item.get("new_price"),
                    strategy=item.get("strategy", ""),
                    reason=item.get("reason", ""),
                    actor=item.get("actor", "system"),
                )
                self._entries.append(entry)
        except Exception as e:
            logger.error(f"Failed to load audit log: {e}")
