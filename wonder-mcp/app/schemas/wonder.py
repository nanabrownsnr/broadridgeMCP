from pydantic import BaseModel, Field


class WonderApiRequest(BaseModel):
    """
    Execute a Wonder API call through this MCP.

    Use this as a controlled pass-through while upstream Wonder endpoint details evolve.
    Agents should prefer known endpoint paths from Wonder docs/internal API references.
    """

    method: str = Field(..., description="HTTP method, e.g. GET/POST/PATCH/DELETE.")
    path: str = Field(..., description="API path beginning with '/', e.g. /v1/projects.")
    query: dict[str, str] | None = Field(default=None, description="Optional query parameters.")
    json_body: dict | None = Field(default=None, description="Optional JSON body for write operations.")
    timeout_seconds: int = Field(default=60, ge=5, le=300, description="Request timeout in seconds.")


class WonderAuthDiagnoseRequest(BaseModel):
    """
    Optional lightweight auth test against a supplied Wonder API path.
    """

    test_path: str = Field(default="/", description="Path to test against Wonder API URL.")
    method: str = Field(default="GET", description="HTTP method for the test call.")
