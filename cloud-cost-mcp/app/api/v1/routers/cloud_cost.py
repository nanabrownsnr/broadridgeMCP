from datetime import datetime, timezone

from app.core.config import settings
from app.core.platform_integration_client import PlatformIntegrationClient, get_platform_client
from app.schemas.cloud_cost import (
    CalculateWorkloadCostRequest,
    CompareComputeRequest,
    CompareEgressRequest,
    CompareStorageRequest,
    EstimateMigrationSavingsRequest,
    QuickEstimateRequest,
)
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(prefix="/cloud_cost", tags=["cloud_cost"])

PROVIDERS = ("aws", "azure", "gcp", "oci")

# Approximate baseline rates for fast comparative planning (USD)
COMPUTE_RATE_PER_VCPU_HOUR = {"aws": 0.031, "azure": 0.034, "gcp": 0.029, "oci": 0.021}
MEMORY_RATE_PER_GB_HOUR = {"aws": 0.0044, "azure": 0.0049, "gcp": 0.0042, "oci": 0.0034}
STORAGE_RATE_PER_GB_MONTH = {
    "standard": {"aws": 0.023, "azure": 0.020, "gcp": 0.020, "oci": 0.0255},
    "archive": {"aws": 0.004, "azure": 0.002, "gcp": 0.0012, "oci": 0.0025},
    "premium": {"aws": 0.125, "azure": 0.12, "gcp": 0.17, "oci": 0.13},
}
EGRESS_RATE_PER_GB = {"aws": 0.09, "azure": 0.087, "gcp": 0.085, "oci": 0.0085}
FREE_EGRESS_GB = {"aws": 100, "azure": 100, "gcp": 100, "oci": 10_240}
K8S_CONTROL_PLANE_MONTHLY = {"aws": 73.0, "azure": 0.0, "gcp": 73.0, "oci": 0.0}

PRESETS = {
    "small-web-app": dict(vm_count=2, vcpu_per_vm=2, memory_gb_per_vm=4, storage_gb=100, egress_gb=200, kubernetes_cluster_count=0),
    "medium-api-server": dict(vm_count=3, vcpu_per_vm=4, memory_gb_per_vm=16, storage_gb=500, egress_gb=1000, kubernetes_cluster_count=0),
    "kubernetes-cluster": dict(vm_count=5, vcpu_per_vm=4, memory_gb_per_vm=16, storage_gb=1000, egress_gb=2000, kubernetes_cluster_count=1),
    "high-traffic-web": dict(vm_count=8, vcpu_per_vm=8, memory_gb_per_vm=32, storage_gb=2000, egress_gb=8000, kubernetes_cluster_count=1),
}

LAST_REFRESH_AT = datetime.now(timezone.utc)


def _normalize_providers(requested: list[str] | None) -> list[str]:
    if not requested:
        return list(PROVIDERS)
    normalized = [p.lower().strip() for p in requested]
    bad = [p for p in normalized if p not in PROVIDERS]
    if bad:
        raise HTTPException(status_code=400, detail=f"Unsupported providers: {bad}. Use {list(PROVIDERS)}")
    return normalized


def _table_response(title: str, rows: list[dict], columns: list[dict], summary: dict | None = None) -> dict:
    return {
        "content": [{"type": "text", "text": f"{title}\nRows: {len(rows)}"}],
        "structuredContent": {
            "view": "cost_table",
            "title": title,
            "columns": columns,
            "rows": rows,
            "summary": summary or {},
        },
    }


@router.post("/compare_compute", operation_id="cloud_cost_compare_compute")
async def compare_compute(
    payload: CompareComputeRequest,
    platform_client: PlatformIntegrationClient = Depends(get_platform_client),
) -> dict:
    """
    Compare compute monthly cost across cloud providers for the same VM requirement.
    Returns assistant-readable text and structured table content for UI rendering.
    """
    _ = platform_client
    providers = _normalize_providers(payload.providers)
    rows: list[dict] = []
    for p in providers:
        hourly = (payload.vcpu * COMPUTE_RATE_PER_VCPU_HOUR[p]) + (payload.memory_gb * MEMORY_RATE_PER_GB_HOUR[p])
        monthly = hourly * payload.monthly_hours * payload.instance_count
        rows.append(
            {
                "provider": p,
                "vcpu": payload.vcpu,
                "memory_gb": payload.memory_gb,
                "instance_count": payload.instance_count,
                "monthly_hours": payload.monthly_hours,
                "estimated_monthly_cost": round(monthly, 2),
                "currency": settings.CLOUD_COST_CURRENCY,
            }
        )
    rows.sort(key=lambda x: x["estimated_monthly_cost"])
    best = rows[0]
    return _table_response(
        "Compute Cost Comparison",
        rows,
        columns=[
            {"key": "provider", "label": "Provider"},
            {"key": "vcpu", "label": "vCPU"},
            {"key": "memory_gb", "label": "Memory (GB)"},
            {"key": "estimated_monthly_cost", "label": f"Monthly Cost ({settings.CLOUD_COST_CURRENCY})"},
        ],
        summary={"cheapest_provider": best["provider"], "cheapest_monthly_cost": best["estimated_monthly_cost"]},
    )


@router.post("/compare_storage", operation_id="cloud_cost_compare_storage")
async def compare_storage(payload: CompareStorageRequest, platform_client: PlatformIntegrationClient = Depends(get_platform_client)) -> dict:
    """Compare monthly storage cost across providers for a selected tier and storage size."""
    _ = platform_client
    tier = payload.tier.lower().strip()
    if tier not in STORAGE_RATE_PER_GB_MONTH:
        raise HTTPException(status_code=400, detail=f"Unsupported tier '{payload.tier}'. Use one of {list(STORAGE_RATE_PER_GB_MONTH.keys())}.")
    rows: list[dict] = []
    for p in PROVIDERS:
        monthly = payload.storage_gb * STORAGE_RATE_PER_GB_MONTH[tier][p]
        rows.append({"provider": p, "tier": tier, "storage_gb": payload.storage_gb, "estimated_monthly_cost": round(monthly, 2), "currency": settings.CLOUD_COST_CURRENCY})
    rows.sort(key=lambda x: x["estimated_monthly_cost"])
    return _table_response(
        "Storage Cost Comparison",
        rows,
        columns=[
            {"key": "provider", "label": "Provider"},
            {"key": "tier", "label": "Tier"},
            {"key": "storage_gb", "label": "Storage (GB)"},
            {"key": "estimated_monthly_cost", "label": f"Monthly Cost ({settings.CLOUD_COST_CURRENCY})"},
        ],
        summary={"cheapest_provider": rows[0]["provider"], "cheapest_monthly_cost": rows[0]["estimated_monthly_cost"]},
    )


@router.post("/compare_egress", operation_id="cloud_cost_compare_egress")
async def compare_egress(payload: CompareEgressRequest, platform_client: PlatformIntegrationClient = Depends(get_platform_client)) -> dict:
    """Compare monthly egress/data transfer costs across providers using free-tier allowances first."""
    _ = platform_client
    rows: list[dict] = []
    for p in PROVIDERS:
        billable_gb = max(payload.egress_gb - FREE_EGRESS_GB[p], 0)
        monthly = billable_gb * EGRESS_RATE_PER_GB[p]
        rows.append(
            {
                "provider": p,
                "egress_gb": payload.egress_gb,
                "free_egress_gb": FREE_EGRESS_GB[p],
                "billable_egress_gb": round(billable_gb, 2),
                "estimated_monthly_cost": round(monthly, 2),
                "currency": settings.CLOUD_COST_CURRENCY,
            }
        )
    rows.sort(key=lambda x: x["estimated_monthly_cost"])
    return _table_response(
        "Egress Cost Comparison",
        rows,
        columns=[
            {"key": "provider", "label": "Provider"},
            {"key": "egress_gb", "label": "Egress (GB)"},
            {"key": "free_egress_gb", "label": "Free Egress (GB)"},
            {"key": "estimated_monthly_cost", "label": f"Monthly Cost ({settings.CLOUD_COST_CURRENCY})"},
        ],
        summary={"cheapest_provider": rows[0]["provider"], "cheapest_monthly_cost": rows[0]["estimated_monthly_cost"]},
    )


def _workload_monthly_cost(provider: str, payload: CalculateWorkloadCostRequest) -> dict:
    vm_hourly = (payload.vcpu_per_vm * COMPUTE_RATE_PER_VCPU_HOUR[provider]) + (payload.memory_gb_per_vm * MEMORY_RATE_PER_GB_HOUR[provider])
    compute = vm_hourly * payload.monthly_hours * payload.vm_count
    storage = payload.storage_gb * STORAGE_RATE_PER_GB_MONTH["standard"][provider]
    billable_egress = max(payload.egress_gb - FREE_EGRESS_GB[provider], 0)
    egress = billable_egress * EGRESS_RATE_PER_GB[provider]
    k8s = payload.kubernetes_cluster_count * K8S_CONTROL_PLANE_MONTHLY[provider]
    total = compute + storage + egress + k8s
    return {
        "provider": provider,
        "compute_cost": round(compute, 2),
        "storage_cost": round(storage, 2),
        "egress_cost": round(egress, 2),
        "kubernetes_control_plane_cost": round(k8s, 2),
        "estimated_monthly_cost": round(total, 2),
        "currency": settings.CLOUD_COST_CURRENCY,
    }


@router.post("/calculate_workload_cost", operation_id="cloud_cost_calculate_workload_cost")
async def calculate_workload_cost(payload: CalculateWorkloadCostRequest, platform_client: PlatformIntegrationClient = Depends(get_platform_client)) -> dict:
    """Estimate complete workload monthly cost across providers (compute, storage, egress, managed K8s control plane)."""
    _ = platform_client
    rows = [_workload_monthly_cost(p, payload) for p in PROVIDERS]
    rows.sort(key=lambda x: x["estimated_monthly_cost"])
    return _table_response(
        "Workload Cost Estimate",
        rows,
        columns=[
            {"key": "provider", "label": "Provider"},
            {"key": "compute_cost", "label": "Compute"},
            {"key": "storage_cost", "label": "Storage"},
            {"key": "egress_cost", "label": "Egress"},
            {"key": "kubernetes_control_plane_cost", "label": "K8s Control Plane"},
            {"key": "estimated_monthly_cost", "label": f"Total ({settings.CLOUD_COST_CURRENCY})"},
        ],
        summary={"cheapest_provider": rows[0]["provider"], "cheapest_monthly_cost": rows[0]["estimated_monthly_cost"]},
    )


@router.get("/list_presets", operation_id="cloud_cost_list_presets")
async def list_presets(platform_client: PlatformIntegrationClient = Depends(get_platform_client)) -> dict:
    """List available workload presets for quick estimation."""
    _ = platform_client
    items = [{"preset_name": k, **v} for k, v in PRESETS.items()]
    return {"content": [{"type": "text", "text": f"Available presets: {', '.join(PRESETS.keys())}"}], "structuredContent": {"presets": items}}


@router.post("/quick_estimate", operation_id="cloud_cost_quick_estimate")
async def quick_estimate(payload: QuickEstimateRequest, platform_client: PlatformIntegrationClient = Depends(get_platform_client)) -> dict:
    """Run a one-shot cross-cloud estimate using a named preset from list_presets."""
    _ = platform_client
    preset = PRESETS.get(payload.preset_name)
    if not preset:
        raise HTTPException(status_code=404, detail=f"Unknown preset '{payload.preset_name}'. Use list_presets.")
    req = CalculateWorkloadCostRequest(**preset)
    return await calculate_workload_cost(req, platform_client)


@router.post("/estimate_migration_savings", operation_id="cloud_cost_estimate_migration_savings")
async def estimate_migration_savings(
    payload: EstimateMigrationSavingsRequest,
    platform_client: PlatformIntegrationClient = Depends(get_platform_client),
) -> dict:
    """Estimate potential monthly savings when moving workload from current_provider to other providers."""
    _ = platform_client
    current = payload.current_provider.lower().strip()
    if current not in PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unsupported current_provider '{payload.current_provider}'. Use {list(PROVIDERS)}")
    workload = CalculateWorkloadCostRequest(
        vm_count=payload.vm_count,
        vcpu_per_vm=payload.vcpu_per_vm,
        memory_gb_per_vm=payload.memory_gb_per_vm,
        monthly_hours=payload.monthly_hours,
        storage_gb=payload.storage_gb,
        egress_gb=payload.egress_gb,
        kubernetes_cluster_count=payload.kubernetes_cluster_count,
    )
    rows = [_workload_monthly_cost(p, workload) for p in PROVIDERS]
    rows.sort(key=lambda x: x["estimated_monthly_cost"])
    current_cost = next((r["estimated_monthly_cost"] for r in rows if r["provider"] == current), None)
    if current_cost is None:
        raise HTTPException(status_code=500, detail="Failed to calculate current provider baseline.")
    for row in rows:
        row["estimated_monthly_savings_vs_current"] = round(current_cost - row["estimated_monthly_cost"], 2)
    return _table_response(
        "Migration Savings Estimate",
        rows,
        columns=[
            {"key": "provider", "label": "Provider"},
            {"key": "estimated_monthly_cost", "label": f"Monthly Cost ({settings.CLOUD_COST_CURRENCY})"},
            {"key": "estimated_monthly_savings_vs_current", "label": "Savings vs Current"},
        ],
        summary={"current_provider": current, "current_monthly_cost": current_cost, "best_provider": rows[0]["provider"]},
    )


@router.get("/get_data_freshness", operation_id="cloud_cost_get_data_freshness")
async def get_data_freshness(platform_client: PlatformIntegrationClient = Depends(get_platform_client)) -> dict:
    """Return model data freshness metadata for cost estimates."""
    _ = platform_client
    age_hours = round((datetime.now(timezone.utc) - LAST_REFRESH_AT).total_seconds() / 3600, 2)
    return {
        "content": [{"type": "text", "text": f"Data timestamp: {LAST_REFRESH_AT.isoformat()} | age_hours={age_hours}"}],
        "structuredContent": {
            "data_source": "embedded comparative baseline rates",
            "last_refresh_at": LAST_REFRESH_AT.isoformat(),
            "age_hours": age_hours,
            "currency": settings.CLOUD_COST_CURRENCY,
            "providers": list(PROVIDERS),
        },
    }
