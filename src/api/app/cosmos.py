from azure.cosmos import CosmosClient
from .config import settings

_client: CosmosClient | None = None

def get_cosmos_container():
    global _client
    if _client is None:
        _client = CosmosClient(settings.cosmos_endpoint, credential=settings.cosmos_key)
    
    db = _client.get_database_client(settings.cosmos_database)
    container = db.get_container_client(settings.cosmos_container)
    return container