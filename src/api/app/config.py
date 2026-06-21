from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_PATH,
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    cosmos_endpoint: str
    cosmos_key: str
    cosmos_database: str
    cosmos_container: str
    blob_connection_string: str
    blob_container: str

    # SignalR (fonctionnalité 4)
    signalr_connection_string: str = ""
    signalr_hub: str = "documents"

    # Service Bus (fonctionnalité 7 - retry)
    service_bus_connection_string: str = ""
    service_bus_queue: str = "documents-queue"


settings = Settings()
