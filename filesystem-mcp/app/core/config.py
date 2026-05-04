import logging
import os
from logging.handlers import TimedRotatingFileHandler

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


def configure_logging() -> None:
    os.makedirs("./logs", exist_ok=True)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s  - %(message)s")

    file_handler = TimedRotatingFileHandler(
        "./logs/filesystem-mcp-api.log",
        when="midnight",
        interval=1,
        backupCount=7,
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)

    detailed_handler = TimedRotatingFileHandler(
        "./logs/detailed.filesystem-mcp-api.log",
        when="midnight",
        interval=1,
        backupCount=7,
    )
    detailed_handler.setFormatter(formatter)
    detailed_handler.setLevel(logging.DEBUG)
    root_logger.addHandler(detailed_handler)


class Settings(BaseSettings):
    SERVICE_ID: str = "filesystem_mcp"
    APP_TITLE: str = "Filesystem MCP"
    ROOT_PATH: str = ""
    VERSION: str = "1.0"
    RELEASE_ID: str = "0.1"
    API_V1_STR: str = "/api/v1"
    ALLOWED_ORIGINS: str = "*"
    PERSONA_ID_HEADER: str = "Persona-Id"

    FILESYSTEM_API_URL: str = "http://localhost:8011"
    WORKSPACE_ROOT: str = "/workspace"

    CLIENT_ID: str = ""
    CLIENT_SECRET: str = ""
    ACCOUNT_SERVICE_URL: str = ""
    ACCOUNT_SERVICE_JWKS_ENDPOINT: str = "/.well-known/jwks.json"
    ACCOUNT_SERVICE_JWKS_CACHE_TTL: int = 600

    USAGE_REPORT_ENDPOINT: str = "/api/v1/usage_reports"
    TRACK_USAGE: int = 0

    PLATFORM_INT_URL: str = ""

    LICENSE_SERVER_BASE_URL: str = ""
    LICENSE_SERVER_JWKS_ENDPOINT: str = ""
    LICENSE_SERVER_ACTIVATION_ENDPOINT: str = ""
    LICENSE_KEY: str = ""


settings = Settings()
configure_logging()


