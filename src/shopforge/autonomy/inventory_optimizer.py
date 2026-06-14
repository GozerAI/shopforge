"""Autonomous inventory optimization."""
import logging, math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)
_DEFAULT_SERVICE_LEVEL_Z = 1.65
_DEFAULT_LEAD_TIME_DAYS = 7
_DEFAULT_HOLDING_COST_PCT = 0.25
_DEFAULT_ORDER_COST = 25.0

@dataclass
class ReorderPoint:
    product_id: str = ""
    variant_id: str = ""
    sku: str = ""
    reorder_point: int = 0
    avg_daily_demand: float = 0.0
    lead_time_days: float = _DEFAULT_LEAD_TIME_DAYS
    safety_stock: int = 0
    current_stock: int = 0
    needs_reorder: bool = False
    def to_dict(self):
        return {"product_id": self.product_id, "variant_id": self.variant_id,
            "sku": self.sku, "reorder_point": self.reorder_point,
            "avg_daily_demand": round(self.avg_daily_demand, 2),
            "lead_time_days": self.lead_time_days, "safety_stock": self.safety_stock,
            "current_stock": self.current_stock, "needs_reorder": self.needs_reorder}

@dataclass
class SafetyStockLevel:
    product_id: str = ""
    variant_id: str = ""
    sku: str = ""
    safety_stock: int = 0
    demand_std_dev: float = 0.0
    lead_time_days: float = _DEFAULT_LEAD_TIME_DAYS
    lead_time_std_dev: float = 0.0
    service_level_z: float = _DEFAULT_SERVICE_LEVEL_Z
    def to_dict(self):
        return {"product_id": self.product_id, "variant_id": self.variant_id,
            "sku": self.sku, "safety_stock": self.safety_stock,
            "demand_std_dev": round(self.demand_std_dev, 2),
            "lead_time_days": self.lead_time_days,
            "lead_time_std_dev": round(self.lead_time_std_dev, 2),
            "service_level_z": self.service_level_z}

@dataclass
class EOQResult:
    product_id: str = ""
    variant_id: str = ""
    sku: str = ""
    eoq: int = 0
    annual_demand: float = 0.0
    order_cost: float = _DEFAULT_ORDER_COST
    holding_cost_per_unit: float = 0.0
    total_annual_cost: float = 0.0
    orders_per_year: float = 0.0
    def to_dict(self):
        return {"product_id": self.product_id, "variant_id": self.variant_id,
            "sku": self.sku, "eoq": self.eoq,
            "annual_demand": round(self.annual_demand, 2), "order_cost": self.order_cost,
            "holding_cost_per_unit": round(self.holding_cost_per_unit, 2),
            "total_annual_cost": round(self.total_annual_cost, 2),
            "orders_per_year": round(self.orders_per_year, 2)}

class InventoryOptimizer:
    def __init__(self, lead_time_days=_DEFAULT_LEAD_TIME_DAYS, lead_time_std_dev=1.0,
                 service_level_z=_DEFAULT_SERVICE_LEVEL_Z, holding_cost_pct=_DEFAULT_HOLDING_COST_PCT,
                 order_cost=_DEFAULT_ORDER_COST):
        self._lead_time_days = lead_time_days
        self._lead_time_std_dev = lead_time_std_dev
        self._service_level_z = service_level_z
        self._holding_cost_pct = holding_cost_pct
        self._order_cost = order_cost

    def calculate_safety_stock(self, product_id, variant_id, sku, daily_sales,
                               lead_time_days=None, lead_time_std_dev=None):
        lt = lead_time_days if lead_time_days is not None else self._lead_time_days
        lt_std = lead_time_std_dev if lead_time_std_dev is not None else self._lead_time_std_dev
        if not daily_sales:
            return SafetyStockLevel(product_id=product_id, variant_id=variant_id, sku=sku,
                                    lead_time_days=lt, service_level_z=self._service_level_z)
        avg = sum(daily_sales) / len(daily_sales)
        std = 0.0
        if len(daily_sales) > 1:
            variance = sum((x - avg) ** 2 for x in daily_sales) / (len(daily_sales) - 1)
            std = math.sqrt(variance)
        ss = max(1, math.ceil(self._service_level_z * math.sqrt(lt * std**2 + avg**2 * lt_std**2)))
        return SafetyStockLevel(product_id=product_id, variant_id=variant_id, sku=sku,
                                safety_stock=ss, demand_std_dev=std, lead_time_days=lt,
                                lead_time_std_dev=lt_std, service_level_z=self._service_level_z)

    def calculate_reorder_point(self, product_id, variant_id, sku, daily_sales,
                                current_stock, lead_time_days=None):
        lt = lead_time_days if lead_time_days is not None else self._lead_time_days
        if not daily_sales:
            return ReorderPoint(product_id=product_id, variant_id=variant_id, sku=sku,
                                lead_time_days=lt, current_stock=current_stock)
        avg = sum(daily_sales) / len(daily_sales)
        ss = self.calculate_safety_stock(product_id, variant_id, sku, daily_sales, lead_time_days=lt)
        rop = math.ceil(avg * lt) + ss.safety_stock
        return ReorderPoint(product_id=product_id, variant_id=variant_id, sku=sku,
                            reorder_point=rop, avg_daily_demand=avg, lead_time_days=lt,
                            safety_stock=ss.safety_stock, current_stock=current_stock,
                            needs_reorder=current_stock <= rop)

    def calculate_eoq(self, product_id, variant_id, sku, annual_demand, unit_cost,
                      order_cost=None, holding_cost_pct=None):
        oc = order_cost if order_cost is not None else self._order_cost
        hc = unit_cost * (holding_cost_pct if holding_cost_pct is not None else self._holding_cost_pct)
        if annual_demand <= 0 or hc <= 0:
            return EOQResult(product_id=product_id, variant_id=variant_id, sku=sku,
                             annual_demand=annual_demand, order_cost=oc, holding_cost_per_unit=hc)
        eoq = max(1, math.ceil(math.sqrt((2 * annual_demand * oc) / hc)))
        return EOQResult(product_id=product_id, variant_id=variant_id, sku=sku, eoq=eoq,
                         annual_demand=annual_demand, order_cost=oc, holding_cost_per_unit=hc,
                         total_annual_cost=(annual_demand/eoq)*oc + (eoq/2)*hc,
                         orders_per_year=annual_demand/eoq)

    def analyze_inventory(self, products, sales_history):
        alerts, eoqs, total = [], [], 0
        for p in products:
            pid = p.get("id", "")
            for v in p.get("variants", []):
                vid, sku = v.get("id", ""), v.get("sku", "")
                stock = v.get("inventory_quantity", 0)
                cost = v.get("cost") or v.get("price", 0)
                daily = sales_history.get(sku, [])
                if not daily: continue
                total += 1
                rop = self.calculate_reorder_point(pid, vid, sku, daily, stock)
                if rop.needs_reorder: alerts.append(rop.to_dict())
                ann = sum(daily) / len(daily) * 365
                if cost and cost > 0: eoqs.append(self.calculate_eoq(pid, vid, sku, ann, cost).to_dict())
        alerts.sort(key=lambda a: a.get("current_stock", 0))
        return {"analyzed_at": datetime.now(timezone.utc).isoformat(), "total_analyzed": total,
                "reorder_alerts": alerts, "reorder_alert_count": len(alerts), "eoq_recommendations": eoqs}
