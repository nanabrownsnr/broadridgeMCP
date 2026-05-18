from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from app.core.config import settings
from app.core.platform_integration_client import PlatformIntegrationClient, get_platform_client
from app.schemas.cloud_cost import (
    CalculateWorkloadCostRequest,
    CompareComputeRequest,
    CompareStorageRequest,
    EstimateMigrationSavingsRequest,
    QuickEstimateRequest,
)
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(prefix="/cloud_cost", tags=["cloud_cost"])

PROVIDERS = ("aws", "azure", "gcp", "oci")
AWS_VANTAGE = "https://instances.vantage.sh/instances.json"
AZURE_VANTAGE_CANDIDATES = (
    "https://instances.vantage.sh/azure/instances.json",
    "https://instances.vantage.sh/az/instances.json",
)
GCP_VANTAGE = "https://instances.vantage.sh/gcp/instances.json"
OCI_PRODUCTS = "https://apexapps.oracle.com/pls/apex/cetools/api/v1/products/"
AZURE_RETAIL = "https://prices.azure.com/api/retail/prices"

_CACHE: dict[str, tuple[datetime, Any]] = {}
CACHE_TTL_SECONDS = 3600

PRESETS = {
    "small-web-app": dict(vm_count=2, vcpu_per_vm=2, memory_gb_per_vm=4, storage_gb=100, egress_gb=200, kubernetes_cluster_count=0),
    "medium-api-server": dict(vm_count=3, vcpu_per_vm=4, memory_gb_per_vm=16, storage_gb=500, egress_gb=1000, kubernetes_cluster_count=0),
    "kubernetes-cluster": dict(vm_count=5, vcpu_per_vm=4, memory_gb_per_vm=16, storage_gb=1000, egress_gb=2000, kubernetes_cluster_count=1),
    "high-traffic-web": dict(vm_count=8, vcpu_per_vm=8, memory_gb_per_vm=32, storage_gb=2000, egress_gb=8000, kubernetes_cluster_count=1),
}


def _normalize_providers(requested: list[str] | None) -> list[str]:
    if not requested:
        return list(PROVIDERS)
    normalized = [p.lower().strip() for p in requested]
    bad = [p for p in normalized if p not in PROVIDERS]
    if bad:
        raise HTTPException(status_code=400, detail=f"Unsupported providers: {bad}. Use {list(PROVIDERS)}")
    return normalized


async def _fetch_json(url: str) -> Any:
    now = datetime.now(timezone.utc)
    cached = _CACHE.get(url)
    if cached and (now - cached[0]).total_seconds() < CACHE_TTL_SECONDS:
        return cached[1]
    async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
        res = await client.get(url)
    if res.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Upstream pricing API failed: {url} -> {res.status_code}")
    data = res.json()
    _CACHE[url] = (now, data)
    return data


def _safe_float(v: Any) -> float | None:
    try:
        return float(v)
    except Exception:
        return None


def _table_response(title: str, rows: list[dict], columns: list[dict], summary: dict | None = None, warnings: list[str] | None = None) -> dict:
    return {
        "content": [{"type": "text", "text": f"{title}\nRows: {len(rows)}\nWarnings: {len(warnings or [])}"}],
        "structuredContent": {
            "view": "cost_table",
            "title": title,
            "columns": columns,
            "rows": rows,
            "summary": summary or {},
            "warnings": warnings or [],
            "data_source": "live_public_apis_only",
        },
    }


async def _azure_vantage_data() -> list[dict]:
    last_exc: Exception | None = None
    for url in AZURE_VANTAGE_CANDIDATES:
        try:
            data = await _fetch_json(url)
            if isinstance(data, list):
                return data
        except Exception as ex:
            last_exc = ex
            continue
    if last_exc:
        raise last_exc
    raise HTTPException(status_code=502, detail="Azure vantage data unavailable")


def _select_best_instance(items: list[dict], provider: str, region: str, req_vcpu: int, req_mem: float, monthly_hours: int, instance_count: int) -> dict | None:
    best: dict | None = None
    best_monthly = 10**18
    for item in items:
        vcpu = _safe_float(item.get("vCPU") or item.get("vcpus") or item.get("vcpu"))
        mem = _safe_float(item.get("memory") or item.get("memoryGB") or item.get("memory_gb"))
        if vcpu is None or mem is None:
            continue
        if vcpu < req_vcpu or mem < req_mem:
            continue
        pricing = item.get("pricing", {})
        region_pricing = pricing.get(region) or pricing.get("us-east-1") or pricing.get("eastus") or pricing.get("us-central1")
        if not isinstance(region_pricing, dict):
            continue
        linux = region_pricing.get("linux", {})
        ondemand = _safe_float(linux.get("ondemand"))
        if ondemand is None:
            continue
        monthly = ondemand * monthly_hours * instance_count
        if monthly < best_monthly:
            best_monthly = monthly
            best = {
                "provider": provider,
                "instance_type": item.get("instance_type") or item.get("name") or "unknown",
                "vcpu": int(vcpu),
                "memory_gb": float(mem),
                "hourly_price": round(ondemand, 6),
                "estimated_monthly_cost": round(monthly, 2),
                "currency": settings.CLOUD_COST_CURRENCY,
                "source": "instances.vantage.sh",
            }
    return best


async def _live_compute_rows(payload: CompareComputeRequest, providers: list[str]) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    rows: list[dict] = []
    if "aws" in providers:
        aws_data = await _fetch_json(AWS_VANTAGE)
        best = _select_best_instance(aws_data, "aws", "us-east-1", payload.vcpu, payload.memory_gb, payload.monthly_hours, payload.instance_count)
        if best:
            rows.append(best)
        else:
            warnings.append("No AWS live match found for requested specs.")
    if "gcp" in providers:
        gcp_data = await _fetch_json(GCP_VANTAGE)
        best = _select_best_instance(gcp_data, "gcp", "us-central1", payload.vcpu, payload.memory_gb, payload.monthly_hours, payload.instance_count)
        if best:
            rows.append(best)
        else:
            warnings.append("No GCP live match found for requested specs.")
    if "azure" in providers:
        az_data = await _azure_vantage_data()
        best = _select_best_instance(az_data, "azure", "eastus", payload.vcpu, payload.memory_gb, payload.monthly_hours, payload.instance_count)
        if best:
            rows.append(best)
        else:
            warnings.append("No Azure live match found for requested specs.")
    if "oci" in providers:
        # OCI public API does not expose standardized instance catalog with vCPU/memory like Vantage.
        # We still report live-source availability explicitly.
        warnings.append("OCI live compute matching is not available in this version (Oracle public API lacks normalized instance sizing feed).")
    rows.sort(key=lambda x: x["estimated_monthly_cost"])
    return rows, warnings


@router.post("/compare_compute", operation_id="cloud_cost_compare_compute")
async def compare_compute(payload: CompareComputeRequest, platform_client: PlatformIntegrationClient = Depends(get_platform_client)) -> dict:
    """Compare compute monthly cost using live public pricing feeds only (no embedded hardcoded price tables)."""
    _ = platform_client
    providers = _normalize_providers(payload.providers)
    rows, warnings = await _live_compute_rows(payload, providers)
    if not rows:
        raise HTTPException(status_code=502, detail=f"No live compute rows available. Warnings: {warnings}")
    best = rows[0]
    return _table_response(
        "Compute Cost Comparison (Live APIs)",
        rows,
        columns=[
            {"key": "provider", "label": "Provider"},
            {"key": "instance_type", "label": "Instance"},
            {"key": "vcpu", "label": "vCPU"},
            {"key": "memory_gb", "label": "Memory (GB)"},
            {"key": "estimated_monthly_cost", "label": f"Monthly Cost ({settings.CLOUD_COST_CURRENCY})"},
        ],
        summary={"cheapest_provider": best["provider"], "cheapest_monthly_cost": best["estimated_monthly_cost"]},
        warnings=warnings,
    )


@router.post("/compare_storage", operation_id="cloud_cost_compare_storage")
async def compare_storage(payload: CompareStorageRequest, platform_client: PlatformIntegrationClient = Depends(get_platform_client)) -> dict:
    """
    Compare storage cost using live APIs where available.
    Returns only providers with live-resolved storage unit prices.
    """
    _ = platform_client
    rows: list[dict] = []
    warnings: list[str] = []
    tier = payload.tier.lower().strip()

    # Azure Retail Prices API (live)
    try:
        filt = "serviceName eq 'Storage' and armRegionName eq 'eastus' and priceType eq 'Consumption' and currencyCode eq 'USD'"
        az = await _fetch_json(f"{AZURE_RETAIL}?$filter={httpx.QueryParams({'x': filt}).get('x')}&$top=100")
        items = az.get("Items", []) if isinstance(az, dict) else []
        picked = None
        for it in items:
            sku = str(it.get("skuName", "")).lower()
            unit = str(it.get("unitOfMeasure", "")).lower()
            if "gb" in unit and (tier in sku or tier == "standard"):
                picked = it
                break
        if picked:
            rate = _safe_float(picked.get("retailPrice")) or 0
            rows.append({"provider": "azure", "tier": tier, "storage_gb": payload.storage_gb, "estimated_monthly_cost": round(rate * payload.storage_gb, 2), "currency": settings.CLOUD_COST_CURRENCY, "source": "prices.azure.com"})
    except Exception as ex:
        warnings.append(f"Azure storage live fetch failed: {ex}")

    # OCI products API (live)
    try:
        oci = await _fetch_json(OCI_PRODUCTS)
        items = oci.get("items", []) if isinstance(oci, dict) else []
        rate = None
        for it in items:
            cat = str(it.get("serviceCategory", "")).lower()
            metric = str(it.get("metricName", "")).lower()
            if "storage" not in cat:
                continue
            if "gb" not in metric:
                continue
            currencies = it.get("currencyCodeLocalizations", []) or []
            for cur in currencies:
                if cur.get("currencyCode") != settings.CLOUD_COST_CURRENCY:
                    continue
                for p in (cur.get("prices") or []):
                    if p.get("model") == "PAY_AS_YOU_GO":
                        val = _safe_float(p.get("value"))
                        if val is not None and (rate is None or val < rate):
                            rate = val
        if rate is not None:
            rows.append({"provider": "oci", "tier": tier, "storage_gb": payload.storage_gb, "estimated_monthly_cost": round(rate * payload.storage_gb, 2), "currency": settings.CLOUD_COST_CURRENCY, "source": "apexapps.oracle.com"})
    except Exception as ex:
        warnings.append(f"OCI storage live fetch failed: {ex}")

    warnings.append("AWS/GCP storage live normalization is not included yet in this version.")
    rows.sort(key=lambda x: x["estimated_monthly_cost"])
    if not rows:
        raise HTTPException(status_code=502, detail=f"No live storage rows available. Warnings: {warnings}")
    return _table_response(
        "Storage Cost Comparison (Live APIs)",
        rows,
        columns=[
            {"key": "provider", "label": "Provider"},
            {"key": "tier", "label": "Tier"},
            {"key": "storage_gb", "label": "Storage (GB)"},
            {"key": "estimated_monthly_cost", "label": f"Monthly Cost ({settings.CLOUD_COST_CURRENCY})"},
        ],
        summary={"cheapest_provider": rows[0]["provider"], "cheapest_monthly_cost": rows[0]["estimated_monthly_cost"]},
        warnings=warnings,
    )


def _pick_live_row_for_workload(rows: list[dict]) -> list[dict]:
    return [{"provider": r["provider"], "estimated_monthly_cost": r["estimated_monthly_cost"], "currency": r["currency"], "instance_type": r["instance_type"]} for r in rows]


@router.post("/calculate_workload_cost", operation_id="cloud_cost_calculate_workload_cost")
async def calculate_workload_cost(payload: CalculateWorkloadCostRequest, platform_client: PlatformIntegrationClient = Depends(get_platform_client)) -> dict:
    """Estimate workload compute cost from live instance feeds. Storage/egress are excluded unless resolved by dedicated live tools."""
    _ = platform_client
    compute_req = CompareComputeRequest(
        vcpu=payload.vcpu_per_vm,
        memory_gb=payload.memory_gb_per_vm,
        monthly_hours=payload.monthly_hours,
        instance_count=payload.vm_count,
        providers=list(PROVIDERS),
    )
    rows, warnings = await _live_compute_rows(compute_req, list(PROVIDERS))
    if not rows:
        raise HTTPException(status_code=502, detail=f"No live compute rows available. Warnings: {warnings}")
    result_rows = _pick_live_row_for_workload(rows)
    result_rows.sort(key=lambda x: x["estimated_monthly_cost"])
    return _table_response(
        "Workload Cost Estimate (Live Compute Only)",
        result_rows,
        columns=[
            {"key": "provider", "label": "Provider"},
            {"key": "instance_type", "label": "Reference Instance"},
            {"key": "estimated_monthly_cost", "label": f"Compute Monthly Cost ({settings.CLOUD_COST_CURRENCY})"},
        ],
        summary={"cheapest_provider": result_rows[0]["provider"], "cheapest_monthly_cost": result_rows[0]["estimated_monthly_cost"]},
        warnings=warnings + ["Storage/egress/k8s control-plane costs are excluded until live-normalized feeds are added."],
    )


@router.get("/list_presets", operation_id="cloud_cost_list_presets")
async def list_presets(platform_client: PlatformIntegrationClient = Depends(get_platform_client)) -> dict:
    """List available workload presets for quick estimation."""
    _ = platform_client
    items = [{"preset_name": k, **v} for k, v in PRESETS.items()]
    return {"content": [{"type": "text", "text": f"Available presets: {', '.join(PRESETS.keys())}"}], "structuredContent": {"presets": items}}


@router.post("/quick_estimate", operation_id="cloud_cost_quick_estimate")
async def quick_estimate(payload: QuickEstimateRequest, platform_client: PlatformIntegrationClient = Depends(get_platform_client)) -> dict:
    """Run a one-shot estimate using a named preset with live compute pricing."""
    _ = platform_client
    preset = PRESETS.get(payload.preset_name)
    if not preset:
        raise HTTPException(status_code=404, detail=f"Unknown preset '{payload.preset_name}'. Use list_presets.")
    req = CalculateWorkloadCostRequest(**preset)
    return await calculate_workload_cost(req, platform_client)


@router.post("/estimate_migration_savings", operation_id="cloud_cost_estimate_migration_savings")
async def estimate_migration_savings(payload: EstimateMigrationSavingsRequest, platform_client: PlatformIntegrationClient = Depends(get_platform_client)) -> dict:
    """Estimate migration savings using live compute pricing baseline."""
    _ = platform_client
    current = payload.current_provider.lower().strip()
    if current not in PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unsupported current_provider '{payload.current_provider}'. Use {list(PROVIDERS)}")
    req = CalculateWorkloadCostRequest(
        vm_count=payload.vm_count,
        vcpu_per_vm=payload.vcpu_per_vm,
        memory_gb_per_vm=payload.memory_gb_per_vm,
        monthly_hours=payload.monthly_hours,
        storage_gb=payload.storage_gb,
        egress_gb=payload.egress_gb,
        kubernetes_cluster_count=payload.kubernetes_cluster_count,
    )
    base = await calculate_workload_cost(req, platform_client)
    rows = base["structuredContent"]["rows"]
    current_row = next((r for r in rows if r["provider"] == current), None)
    if not current_row:
        raise HTTPException(status_code=502, detail=f"Current provider '{current}' is not available in live compute result.")
    current_cost = float(current_row["estimated_monthly_cost"])
    out = []
    for row in rows:
        out.append(
            {
                "provider": row["provider"],
                "estimated_monthly_cost": row["estimated_monthly_cost"],
                "estimated_monthly_savings_vs_current": round(current_cost - float(row["estimated_monthly_cost"]), 2),
                "currency": settings.CLOUD_COST_CURRENCY,
            }
        )
    out.sort(key=lambda x: x["estimated_monthly_cost"])
    return _table_response(
        "Migration Savings Estimate (Live Compute)",
        out,
        columns=[
            {"key": "provider", "label": "Provider"},
            {"key": "estimated_monthly_cost", "label": f"Monthly Cost ({settings.CLOUD_COST_CURRENCY})"},
            {"key": "estimated_monthly_savings_vs_current", "label": "Savings vs Current"},
        ],
        summary={"current_provider": current, "current_monthly_cost": current_cost, "best_provider": out[0]["provider"]},
        warnings=["Savings comparison is compute-only in this live version."],
    )


@router.get("/get_data_freshness", operation_id="cloud_cost_get_data_freshness")
async def get_data_freshness(platform_client: PlatformIntegrationClient = Depends(get_platform_client)) -> dict:
    """Return cache freshness metadata for live API results."""
    _ = platform_client
    now = datetime.now(timezone.utc)
    cache_entries = []
    for url, (ts, _) in _CACHE.items():
        cache_entries.append({"source_url": url, "cached_at": ts.isoformat(), "age_minutes": round((now - ts).total_seconds() / 60, 2)})
    return {
        "content": [{"type": "text", "text": f"Live cache entries: {len(cache_entries)}"}],
        "structuredContent": {"cache_ttl_seconds": CACHE_TTL_SECONDS, "entries": cache_entries, "currency": settings.CLOUD_COST_CURRENCY},
    }
