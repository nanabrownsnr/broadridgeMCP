from pydantic import BaseModel, Field


class CompareComputeRequest(BaseModel):
    vcpu: int = Field(..., ge=1, description="Required vCPU count per instance.")
    memory_gb: float = Field(..., gt=0, description="Required memory in GB per instance.")
    monthly_hours: int = Field(default=730, ge=1, description="Usage hours per month.")
    instance_count: int = Field(default=1, ge=1, description="Number of identical instances.")
    providers: list[str] | None = Field(default=None, description="Optional provider filter (aws, azure, gcp, oci).")


class CompareStorageRequest(BaseModel):
    storage_gb: float = Field(..., gt=0, description="Storage volume in GB.")
    tier: str = Field(default="standard", description="Storage tier: standard, archive, premium.")


class CompareEgressRequest(BaseModel):
    egress_gb: float = Field(..., ge=0, description="Monthly outbound transfer in GB.")


class CalculateWorkloadCostRequest(BaseModel):
    vm_count: int = Field(default=1, ge=1, description="Number of VMs.")
    vcpu_per_vm: int = Field(..., ge=1, description="vCPU per VM.")
    memory_gb_per_vm: float = Field(..., gt=0, description="Memory GB per VM.")
    monthly_hours: int = Field(default=730, ge=1, description="Usage hours per month.")
    storage_gb: float = Field(default=0, ge=0, description="Storage GB.")
    egress_gb: float = Field(default=0, ge=0, description="Egress GB.")
    kubernetes_cluster_count: int = Field(default=0, ge=0, description="Managed Kubernetes cluster count.")


class QuickEstimateRequest(BaseModel):
    preset_name: str = Field(..., description="Preset name returned by list_presets.")


class EstimateMigrationSavingsRequest(BaseModel):
    current_provider: str = Field(..., description="Current provider (aws, azure, gcp, oci).")
    vm_count: int = Field(default=1, ge=1)
    vcpu_per_vm: int = Field(..., ge=1)
    memory_gb_per_vm: float = Field(..., gt=0)
    monthly_hours: int = Field(default=730, ge=1)
    storage_gb: float = Field(default=0, ge=0)
    egress_gb: float = Field(default=0, ge=0)
    kubernetes_cluster_count: int = Field(default=0, ge=0)
