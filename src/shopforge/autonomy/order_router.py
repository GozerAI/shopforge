"""Intelligent order routing to fulfillment centers.

Uses multi-factor weighted scoring (distance, capacity, cost, speed) to
select the best fulfillment center for each order.
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class FulfillmentCenter:
    """A warehouse / fulfillment location."""
    center_id: str
    name: str
    latitude: float
    longitude: float
    capacity_remaining: int = 1000
    avg_ship_days: float = 3.0
    cost_per_order: float = 5.0
    supported_regions: List[str] = field(default_factory=lambda: ["US"])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "center_id": self.center_id,
            "name": self.name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "capacity_remaining": self.capacity_remaining,
            "avg_ship_days": self.avg_ship_days,
            "cost_per_order": round(self.cost_per_order, 2),
            "supported_regions": self.supported_regions,
        }


@dataclass
class RoutingDecision:
    """Result of routing an order to a fulfillment center."""
    order_id: str
    selected_center_id: str
    selected_center_name: str
    distance_km: float
    estimated_ship_days: float
    estimated_cost: float
    score: float
    alternatives: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order_id": self.order_id,
            "selected_center_id": self.selected_center_id,
            "selected_center_name": self.selected_center_name,
            "distance_km": round(self.distance_km, 1),
            "estimated_ship_days": round(self.estimated_ship_days, 1),
            "estimated_cost": round(self.estimated_cost, 2),
            "score": round(self.score, 4),
            "alternatives": self.alternatives,
        }


_EARTH_RADIUS_KM = 6371.0


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute great-circle distance in km between two coordinates."""
    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2)
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


class FulfillmentRouter:
    """Routes orders to the optimal fulfillment center using weighted scoring.

    Score factors (configurable weights):
      - distance: closer is better (normalized inverse)
      - capacity: more remaining capacity is better
      - cost: lower cost is better (normalized inverse)
      - speed: fewer ship days is better (normalized inverse)
    """

    DEFAULT_WEIGHTS = {
        "distance": 0.35,
        "capacity": 0.15,
        "cost": 0.25,
        "speed": 0.25,
    }

    def __init__(self, centers: Optional[List[FulfillmentCenter]] = None,
                 weights: Optional[Dict[str, float]] = None):
        self._centers: List[FulfillmentCenter] = centers or []
        self._weights = weights or dict(self.DEFAULT_WEIGHTS)

    def add_center(self, center: FulfillmentCenter) -> None:
        self._centers.append(center)

    def remove_center(self, center_id: str) -> bool:
        before = len(self._centers)
        self._centers = [c for c in self._centers if c.center_id != center_id]
        return len(self._centers) < before

    @property
    def centers(self) -> List[FulfillmentCenter]:
        return list(self._centers)

    def route(self, order_id: str, dest_lat: float, dest_lon: float,
              region: str = "US") -> Optional[RoutingDecision]:
        """Select the best fulfillment center for an order."""
        eligible = [c for c in self._centers
                    if region in c.supported_regions and c.capacity_remaining > 0]
        if not eligible:
            logger.warning("No eligible centers for order %s region=%s", order_id, region)
            return None

        scored: List[Dict[str, Any]] = []
        for center in eligible:
            dist = _haversine(dest_lat, dest_lon, center.latitude, center.longitude)
            scored.append({
                "center": center,
                "distance": dist,
                "capacity": center.capacity_remaining,
                "cost": center.cost_per_order,
                "speed": center.avg_ship_days,
            })

        max_dist = max(s["distance"] for s in scored) or 1.0
        max_cap = max(s["capacity"] for s in scored) or 1.0
        max_cost = max(s["cost"] for s in scored) or 1.0
        max_speed = max(s["speed"] for s in scored) or 1.0

        for s in scored:
            dist_score = 1.0 - (s["distance"] / max_dist)
            cap_score = s["capacity"] / max_cap
            cost_score = 1.0 - (s["cost"] / max_cost)
            speed_score = 1.0 - (s["speed"] / max_speed)
            s["total_score"] = (
                self._weights["distance"] * dist_score +
                self._weights["capacity"] * cap_score +
                self._weights["cost"] * cost_score +
                self._weights["speed"] * speed_score
            )

        scored.sort(key=lambda s: s["total_score"], reverse=True)
        best = scored[0]
        center = best["center"]

        alternatives = []
        for alt in scored[1:3]:
            ac = alt["center"]
            alternatives.append({
                "center_id": ac.center_id,
                "name": ac.name,
                "score": round(alt["total_score"], 4),
                "distance_km": round(alt["distance"], 1),
            })

        return RoutingDecision(
            order_id=order_id,
            selected_center_id=center.center_id,
            selected_center_name=center.name,
            distance_km=best["distance"],
            estimated_ship_days=center.avg_ship_days,
            estimated_cost=center.cost_per_order,
            score=best["total_score"],
            alternatives=alternatives,
        )

    def batch_route(self, orders: List[Dict[str, Any]]) -> List[RoutingDecision]:
        """Route multiple orders.

        Each order dict: order_id, latitude, longitude, region (opt, default "US").
        """
        results: List[RoutingDecision] = []
        for o in orders:
            decision = self.route(
                order_id=o["order_id"],
                dest_lat=o["latitude"],
                dest_lon=o["longitude"],
                region=o.get("region", "US"),
            )
            if decision:
                results.append(decision)
        return results
