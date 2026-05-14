import logging
import os
from logging.handlers import TimedRotatingFileHandler

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


def configure_logging() -> None:
    os.makedirs("./logs", exist_ok=True)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s  - %(message)s")

    file_handler = TimedRotatingFileHandler("./logs/docusign-mcp-api.log", when="midnight", interval=1, backupCount=7)
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)


class Settings(BaseSettings):
    SERVICE_ID: str = "docusign_mcp"
    APP_TITLE: str = "DocuSign MCP"
    ROOT_PATH: str = ""
    VERSION: str = "1.0"
    RELEASE_ID: str = "0.1"
    API_V1_STR: str = "/api/v1"
    ALLOWED_ORIGINS: str = "*"
    PERSONA_ID_HEADER: str = "Persona-Id"

    DOCUSIGN_BASE_URL: str = "https://demo.docusign.net/restapi"
    DOCUSIGN_ACCOUNT_ID: str = ""
    DOCUSIGN_AUTH_MODE: str = "token"
    DOCUSIGN_ACCESS_TOKEN: str = ""
    DOCUSIGN_INTEGRATION_KEY: str = ""
    DOCUSIGN_USER_ID: str = ""
    DOCUSIGN_PRIVATE_KEY_PATH: str = ""
    DOCUSIGN_JWT_SCOPES: str = "signature impersonation"
    DOCUSIGN_KEY_SERVICE_NAME: str = "DocuSign"
    DOCUSIGN_STORE_PATH: str = "/workspace/docusign_envelope_store.json"

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
