"""Typed, read-only tools for the AI copilot (P5-T2).

Every tool reuses the system's own services, so the copilot never does inventory
math itself (policy: data-and-ai-use, "AI copilot limits"). Each returns data,
citations to the records it used, and the data label.

Safety: `run_tool` runs a tool in its own transaction that PostgreSQL itself
keeps read-only (`SET TRANSACTION READ ONLY`), with a statement timeout, and
always rolls back. Problems (unknown tool, bad arguments, nothing found) come
back as a message the model can act on, not as an exception.

Citations: product:<sku>, warehouse:<code>, inventory:<sku>@<code>,
supplier:<code>, purchase_order:<number>, recommendation:<id>,
forecast_run:<id>, policy:<document>#<section>. `resolve_citation` checks that a
citation names a real record.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import Engine, or_, select, text
from sqlalchemy.orm import Session

from app.models import (
    DocumentChunk,
    Forecast,
    ForecastRun,
    Product,
    PurchaseOrder,
    PurchaseOrderStatus,
    Recommendation,
    RecommendationStatus,
    Supplier,
    Warehouse,
)
from app.policies_service import PolicyError, search_policies
from app.purchasing_service import supplier_performance
from app.replenishment_service import (
    DATA_LABEL,
    NoForecastRunError,
    assess_all,
    newest_forecast_run,
)

SIMULATED = "SIMULATED operations data (SYN- codes), not a real company"
POLICY_LABEL = "Simulated company policy written for the demo"
STATEMENT_TIMEOUT = "5s"
MAX_ROWS = 50


class ToolResult(BaseModel):
    tool: str
    ok: bool
    data: list[dict[str, Any]] = []
    citations: list[str] = []
    label: str = ""
    message: str | None = None  # why nothing came back, or what went wrong


class _Input(BaseModel):
    # Unknown arguments are an error, so a model cannot slip in options that do not exist.
    model_config = ConfigDict(extra="forbid")


class FindProductsInput(_Input):
    query: str = Field(min_length=1, max_length=100, description="Part of a SKU or product name")
    limit: int = Field(default=10, ge=1, le=20)


class StockRisksInput(_Input):
    sku: str | None = Field(default=None, max_length=32)
    warehouse_code: str | None = Field(default=None, max_length=16)
    status: Literal["out_of_stock", "at_risk", "ok", "excess"] | None = None
    limit: int = Field(default=10, ge=1, le=MAX_ROWS)


class RecommendationsInput(_Input):
    kind: Literal["reorder", "transfer"] | None = None
    sku: str | None = Field(default=None, max_length=32)
    warehouse_code: str | None = Field(default=None, max_length=16)
    limit: int = Field(default=10, ge=1, le=MAX_ROWS)


class PurchaseOrdersInput(_Input):
    status: Literal["open", "received", "cancelled"] | None = None
    supplier_code: str | None = Field(default=None, max_length=16)
    warehouse_code: str | None = Field(default=None, max_length=16)
    sku: str | None = Field(default=None, max_length=32)
    overdue_only: bool = False
    limit: int = Field(default=10, ge=1, le=MAX_ROWS)


class SupplierPerformanceInput(_Input):
    supplier_code: str | None = Field(default=None, max_length=16)


class DemandForecastInput(_Input):
    sku: str = Field(min_length=1, max_length=32)
    warehouse_code: str = Field(min_length=1, max_length=16)


class SearchPoliciesInput(_Input):
    query: str = Field(min_length=1, max_length=200, description="Question in policy words")
    limit: int = Field(default=3, ge=1, le=5)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[_Input]
    function: Callable[[Session, Any, date], ToolResult]


def _plain(value: Any) -> Any:
    """JSON-friendly values: dates as ISO text, Decimals as numbers."""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _upper(code: str | None) -> str | None:
    return code.strip().upper() if code else None


def _warehouse(session: Session, code: str) -> Warehouse | None:
    return session.execute(select(Warehouse).where(Warehouse.code == code)).scalar_one_or_none()


def _product(session: Session, sku: str) -> Product | None:
    return session.execute(select(Product).where(Product.sku == sku)).scalar_one_or_none()


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


# --- The tools ---------------------------------------------------------------------


def find_products(session: Session, args: FindProductsInput, today: date) -> ToolResult:
    escaped = args.query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    rows = session.execute(
        select(Product, Supplier.code)
        .outerjoin(Supplier, Product.supplier_id == Supplier.id)
        .where(
            or_(Product.sku.ilike(pattern, escape="\\"), Product.name.ilike(pattern, escape="\\"))
        )
        .order_by(Product.sku)
        .limit(args.limit)
    ).all()
    data = [
        {
            "sku": product.sku,
            "name": product.name,
            "category": product.category,
            "supplier_code": supplier_code,
            "min_order_qty": product.min_order_qty,
            "pack_size": product.pack_size,
            "demand_profile_item": product.demand_profile_item_id,
        }
        for product, supplier_code in rows
    ]
    return ToolResult(
        tool="find_products",
        ok=True,
        data=data,
        citations=[f"product:{row['sku']}" for row in data],
        label=SIMULATED,
        message=None if data else f"No product matches {args.query!r}",
    )


def stock_risks(session: Session, args: StockRisksInput, today: date) -> ToolResult:
    warehouse_id = None
    if args.warehouse_code:
        site = _warehouse(session, _upper(args.warehouse_code))
        if site is None:
            return ToolResult(
                tool="stock_risks", ok=False, message=f"Unknown warehouse {args.warehouse_code!r}"
            )
        warehouse_id = site.id
    try:
        run, assessments, unassessed = assess_all(session, 0.95, warehouse_id)
    except NoForecastRunError as error:
        return ToolResult(tool="stock_risks", ok=False, message=str(error))
    sku = _upper(args.sku)
    chosen = [
        a
        for a in assessments
        if (sku is None or a.inputs.sku == sku) and (args.status is None or a.status == args.status)
    ][: args.limit]
    keep = [
        "sku",
        "warehouse_code",
        "status",
        "on_hand",
        "on_order",
        "position",
        "daily_mean",
        "reorder_point",
        "target_level",
        "shortfall",
        "days_of_cover",
        "lead_time_days",
        "demand_profile",
    ]
    data = [{key: a.as_dict()[key] for key in keep} for a in chosen]
    citations = []
    for a in chosen:
        citations += [
            f"inventory:{a.inputs.sku}@{a.inputs.warehouse_code}",
            f"product:{a.inputs.sku}",
        ]
    citations += [f"forecast_run:{run.id}", "policy:replenishment#stock-status"]
    return ToolResult(
        tool="stock_risks",
        ok=True,
        data=data,
        citations=_unique(citations),
        label=DATA_LABEL,
        message=None
        if data
        else f"No matching items ({unassessed} product/warehouse pairs have no demand data)",
    )


def recommendations(session: Session, args: RecommendationsInput, today: date) -> ToolResult:
    query = select(Recommendation).where(Recommendation.status == RecommendationStatus.PENDING)
    if args.kind:
        query = query.where(Recommendation.kind == args.kind)
    if args.sku:
        product = _product(session, _upper(args.sku))
        if product is None:
            return ToolResult(tool="recommendations", ok=False, message=f"Unknown SKU {args.sku!r}")
        query = query.where(Recommendation.product_id == product.id)
    if args.warehouse_code:
        site = _warehouse(session, _upper(args.warehouse_code))
        if site is None:
            return ToolResult(
                tool="recommendations",
                ok=False,
                message=f"Unknown warehouse {args.warehouse_code!r}",
            )
        query = query.where(Recommendation.warehouse_id == site.id)
    rows = session.execute(query.order_by(Recommendation.id).limit(args.limit)).scalars().all()

    skus = dict(session.execute(select(Product.id, Product.sku)).all())
    sites = dict(session.execute(select(Warehouse.id, Warehouse.code)).all())
    suppliers = dict(session.execute(select(Supplier.id, Supplier.code)).all())
    data, citations = [], []
    for rec in rows:
        item = rec.details.get("item") or rec.details.get("destination") or {}
        data.append(
            {
                "id": rec.id,
                "kind": rec.kind,
                "status": rec.status,
                "sku": skus[rec.product_id],
                "warehouse_code": sites[rec.warehouse_id],
                "source_warehouse_code": sites.get(rec.source_warehouse_id),
                "supplier_code": suppliers.get(rec.supplier_id),
                "quantity": rec.quantity,
                "reason": rec.reason,
                "position_before": item.get("position"),
                "target_level": item.get("target_level"),
                "service_level": float(rec.service_level),
            }
        )
        citations += [f"recommendation:{rec.id}", f"product:{skus[rec.product_id]}"]
    if rows:
        citations.append("policy:stock-transfers#transfers-come-first")
    return ToolResult(
        tool="recommendations",
        ok=True,
        data=data,
        citations=_unique(citations),
        label=f"{DATA_LABEL}. Pending proposals: nothing is ordered or moved until approved.",
        message=None if data else "No pending recommendations match",
    )


def purchase_orders(session: Session, args: PurchaseOrdersInput, today: date) -> ToolResult:
    query = select(PurchaseOrder, Supplier.code, Warehouse.code).join(Supplier).join(Warehouse)
    if args.status:
        query = query.where(PurchaseOrder.status == args.status)
    if args.supplier_code:
        query = query.where(Supplier.code == _upper(args.supplier_code))
    if args.warehouse_code:
        query = query.where(Warehouse.code == _upper(args.warehouse_code))
    if args.sku:
        product = _product(session, _upper(args.sku))
        if product is None:
            return ToolResult(tool="purchase_orders", ok=False, message=f"Unknown SKU {args.sku!r}")
        query = query.where(PurchaseOrder.lines.any(product_id=product.id))
    if args.overdue_only:
        query = query.where(
            PurchaseOrder.status == PurchaseOrderStatus.OPEN, PurchaseOrder.expected_date < today
        )
    rows = session.execute(
        query.order_by(PurchaseOrder.ordered_date.desc(), PurchaseOrder.id.desc()).limit(args.limit)
    ).all()
    data = [
        {
            "po_number": order.po_number,
            "supplier_code": supplier_code,
            "warehouse_code": warehouse_code,
            "status": order.status,
            "ordered_date": _plain(order.ordered_date),
            "expected_date": _plain(order.expected_date),
            "received_date": _plain(order.received_date),
            "overdue": order.status == PurchaseOrderStatus.OPEN and order.expected_date < today,
            "lines": len(order.lines),
            "units": sum(line.quantity for line in order.lines),
        }
        for order, supplier_code, warehouse_code in rows
    ]
    return ToolResult(
        tool="purchase_orders",
        ok=True,
        data=data,
        citations=[f"purchase_order:{row['po_number']}" for row in data],
        label=SIMULATED,
        message=None if data else "No purchase orders match",
    )


def supplier_performance_tool(
    session: Session, args: SupplierPerformanceInput, today: date
) -> ToolResult:
    supplier_id = None
    if args.supplier_code:
        supplier = session.execute(
            select(Supplier).where(Supplier.code == _upper(args.supplier_code))
        ).scalar_one_or_none()
        if supplier is None:
            return ToolResult(
                tool="supplier_performance",
                ok=False,
                message=f"Unknown supplier {args.supplier_code!r}",
            )
        supplier_id = supplier.id
    rows = supplier_performance(session, today, supplier_id)
    data = [
        {
            "supplier_code": row.code,
            "name": row.name,
            "rating": row.rating,
            "on_time_rate": row.on_time_rate,
            "received_orders_90_days": row.received_orders,
            "on_time_orders": row.on_time_orders,
            "average_days_late": row.average_days_late,
            "open_orders": row.open_orders,
            "overdue_orders": row.overdue_orders,
        }
        for row in rows
    ]
    citations = []
    for row in rows:
        citations.append(f"supplier:{row.code}")
        citations += [f"purchase_order:{number}" for number in row.overdue_orders]
    citations.append("policy:supplier-performance#measuring-delivery-performance")
    return ToolResult(
        tool="supplier_performance",
        ok=True,
        data=data,
        citations=_unique(citations) if rows else [],
        label=SIMULATED,
        message=None if data else "No suppliers",
    )


def demand_forecast(session: Session, args: DemandForecastInput, today: date) -> ToolResult:
    product = _product(session, _upper(args.sku))
    site = _warehouse(session, _upper(args.warehouse_code))
    if product is None or site is None:
        return ToolResult(tool="demand_forecast", ok=False, message="Unknown SKU or warehouse")
    if not product.demand_profile_item_id or not site.demand_profile_store_id:
        return ToolResult(
            tool="demand_forecast",
            ok=False,
            message="No demand profile linked (run link-demand-profiles)",
        )
    try:
        run = newest_forecast_run(session)
    except NoForecastRunError as error:
        return ToolResult(tool="demand_forecast", ok=False, message=str(error))
    rows = session.execute(
        select(Forecast.step, Forecast.forecast, Forecast.lower, Forecast.upper)
        .where(
            Forecast.run_id == run.id,
            Forecast.item_id == product.demand_profile_item_id,
            Forecast.store_id == site.demand_profile_store_id,
        )
        .order_by(Forecast.step)
    ).all()
    if not rows:
        return ToolResult(
            tool="demand_forecast", ok=False, message="The linked series has no forecast"
        )
    # Only point forecasts are added up: summing daily 80% bounds would not give an
    # 80% range for the total, so the bounds are given per day only.
    totals = {
        f"expected_units_next_{days}_days": round(
            sum(r.forecast for r in rows if r.step <= days), 2
        )
        for days in (7, 14, 28)
    }
    data = [
        {
            "sku": product.sku,
            "warehouse_code": site.code,
            "demand_profile": f"{product.demand_profile_item_id} at {site.demand_profile_store_id}",
            **totals,
            "daily": [
                {
                    "day": r.step,
                    "forecast": round(r.forecast, 2),
                    "low_80": round(r.lower, 2),
                    "high_80": round(r.upper, 2),
                }
                for r in rows
            ],
        }
    ]
    return ToolResult(
        tool="demand_forecast",
        ok=True,
        data=data,
        citations=[f"forecast_run:{run.id}", f"product:{product.sku}", f"warehouse:{site.code}"],
        label=f"{DATA_LABEL}. Days are counted from the forecast's start, not calendar dates.",
    )


def search_policies_tool(session: Session, args: SearchPoliciesInput, today: date) -> ToolResult:
    try:
        hits = search_policies(session, args.query, args.limit)
    except PolicyError as error:
        return ToolResult(tool="search_policies", ok=False, message=str(error))
    return ToolResult(
        tool="search_policies",
        ok=True,
        data=[
            {
                "citation": hit.citation,
                "title": hit.title,
                "section": hit.section,
                "text": hit.content,
            }
            for hit in hits
        ],
        citations=[hit.citation for hit in hits],
        label=POLICY_LABEL,
        message=None if hits else "No policy section matches; try the policy's own words",
    )


TOOLS = {
    tool.name: tool
    for tool in [
        Tool(
            "find_products",
            "Find simulated products by part of their SKU or name.",
            FindProductsInput,
            find_products,
        ),
        Tool(
            "stock_risks",
            "Stock status per product and warehouse (out_of_stock, at_risk, ok, excess), "
            "with reorder point and target level, most urgent first.",
            StockRisksInput,
            stock_risks,
        ),
        Tool(
            "recommendations",
            "Pending reorder and transfer proposals and the numbers behind them.",
            RecommendationsInput,
            recommendations,
        ),
        Tool(
            "purchase_orders",
            "Purchase orders with their dates, status and whether they are overdue.",
            PurchaseOrdersInput,
            purchase_orders,
        ),
        Tool(
            "supplier_performance",
            "Per supplier: on-time rate over the last 90 days, rating (good, watch, "
            "at_risk, not_rated) and overdue orders.",
            SupplierPerformanceInput,
            supplier_performance_tool,
        ),
        Tool(
            "demand_forecast",
            "Borrowed demand forecast (next 28 days) for one product at one warehouse.",
            DemandForecastInput,
            demand_forecast,
        ),
        Tool(
            "search_policies",
            "Search the company policies; returns sections with citations.",
            SearchPoliciesInput,
            search_policies_tool,
        ),
    ]
}


def tool_specs() -> list[dict[str, Any]]:
    """Name, description and JSON schema of every tool, for the model (P5-T3)."""
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_model.model_json_schema(),
        }
        for tool in TOOLS.values()
    ]


def run_tool(
    engine: Engine, name: str, arguments: dict[str, Any], today: date | None = None
) -> ToolResult:
    """Validate the arguments and run one tool in a read-only, time-limited transaction."""
    tool = TOOLS.get(name)
    if tool is None:
        return ToolResult(
            tool=name, ok=False, message=f"Unknown tool {name!r}; use one of {sorted(TOOLS)}"
        )
    try:
        args = tool.input_model.model_validate(arguments)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(map(str, e['loc'])) or 'arguments'}: {e['msg']}" for e in error.errors()
        )
        return ToolResult(tool=name, ok=False, message=f"Invalid arguments: {problems}")
    with Session(engine) as session:
        # Must be the first statement of the transaction; PostgreSQL then refuses
        # every write, whatever the tool's code does.
        session.execute(text("SET TRANSACTION READ ONLY"))
        session.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
        try:
            return tool.function(session, args, today or datetime.now(UTC).date())
        finally:
            session.rollback()


def resolve_citation(session: Session, citation: str) -> bool:
    """True if the citation names an existing record or policy section."""
    kind, _, value = citation.partition(":")
    if not value:
        return False
    if kind == "policy":
        document, _, section = value.partition("#")
        found = select(DocumentChunk.id).where(
            DocumentChunk.document == document, DocumentChunk.section_slug == section
        )
    elif kind == "product":
        found = select(Product.id).where(Product.sku == value)
    elif kind == "warehouse":
        found = select(Warehouse.id).where(Warehouse.code == value)
    elif kind == "inventory":
        sku, _, code = value.partition("@")
        return resolve_citation(session, f"product:{sku}") and resolve_citation(
            session, f"warehouse:{code}"
        )
    elif kind == "supplier":
        found = select(Supplier.id).where(Supplier.code == value)
    elif kind == "purchase_order":
        found = select(PurchaseOrder.id).where(PurchaseOrder.po_number == value)
    elif kind in ("recommendation", "forecast_run"):
        if not value.isdigit():
            return False
        model = Recommendation if kind == "recommendation" else ForecastRun
        found = select(model.id).where(model.id == int(value))
    else:
        return False
    return session.execute(found.limit(1)).first() is not None
