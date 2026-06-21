"""
Endpoint de relance (fonctionnalité 7).

POST /documents/{id}/retry
Republie un message dans Service Bus pour relancer le traitement d'un
document (typiquement un document passé en ERROR via la DLQ), sans avoir
à réuploader le fichier.
"""
import json
from datetime import datetime, timezone

from azure.cosmos.exceptions import CosmosHttpResponseError
from azure.servicebus import ServiceBusClient, ServiceBusMessage
from fastapi import APIRouter, HTTPException

from .config import settings
from .cosmos import get_cosmos_container

router = APIRouter(prefix="/documents", tags=["documents"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@router.post("/{document_id}/retry", status_code=200,
             summary="Relancer le traitement d'un document",
             description="Republie un message dans Service Bus pour "
                         "relancer le pipeline de traitement.")
def retry_document(document_id: str):
    container = get_cosmos_container()

    # 1) Vérifier que le document existe
    try:
        doc = container.read_item(item=document_id, partition_key="JOB")
    except CosmosHttpResponseError as e:
        if getattr(e, "status_code", None) == 404:
            raise HTTPException(status_code=404, detail="Document introuvable")
        raise HTTPException(status_code=500, detail="Erreur Cosmos")

    # 2) Reconstruire le message à partir des infos stockées
    message = {
        "documentId": document_id,
        "fileName": doc.get("fileName", f"{document_id}.bin"),
        "blobName": doc.get("blobName", ""),
        "size": doc.get("size", 0),
        "uploadedAt": _now_iso(),
        "retry": True,
    }

    # 3) Republier dans Service Bus
    try:
        with ServiceBusClient.from_connection_string(
            settings.service_bus_connection_string
        ) as client:
            sender = client.get_queue_sender(
                queue_name=settings.service_bus_queue
            )
            with sender:
                sender.send_messages(
                    ServiceBusMessage(
                        json.dumps(message),
                        content_type="application/json",
                    )
                )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail=f"Échec de republication Service Bus: {exc}",
        )

    # 4) Remettre le document en QUEUED
    doc["status"] = "QUEUED"
    doc["updatedAt"] = _now_iso()
    container.replace_item(item=document_id, body=doc)

    return {"documentId": document_id, "status": "QUEUED", "retried": True}
