"""
Azure Functions - Pipeline de traitement de documents (modèle Python v2).

Function : blob_trigger_documents
  - se déclenche à l'upload d'un fichier dans le conteneur "input"
  - extrait documentId, fileName, blobName, size
  - publie un message JSON dans la file Service Bus "documents-queue"
  - passe le document en statut QUEUED dans Cosmos DB

NB : la notification temps réel "UPLOADED" vers React (SignalR) sera
ajoutée plus tard, quand la ressource SignalR sera créée (fonctionnalité 4).
"""
import datetime
import json
import logging
import os

import azure.functions as func
from azure.cosmos import CosmosClient, exceptions
from azure.servicebus import ServiceBusClient, ServiceBusMessage

import tagging  # module de tagging IA (fonctionnalité 3)
import signalr_client  # helper notifications SignalR (fonctionnalité 4)

app = func.FunctionApp()


def _now_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _get_cosmos_container():
    """Retourne le conteneur Cosmos (db-doc / jobs)."""
    client = CosmosClient(
        os.environ["COSMOS_ENDPOINT"],
        credential=os.environ["COSMOS_KEY"],
    )
    database = os.environ.get("COSMOS_DATABASE", "db-doc")
    container = os.environ.get("COSMOS_CONTAINER", "jobs")
    return client.get_database_client(database).get_container_client(container)


# --------------------------------------------------------------------------- #
# Blob Trigger                                                                 #
# --------------------------------------------------------------------------- #
@app.blob_trigger(
    arg_name="blob",
    path="input/{name}",
    connection="AzureWebJobsStorage",
)
def blob_trigger_documents(blob: func.InputStream):
    # blob.name arrive sous la forme "input/<documentId>_<fileName>"
    blob_name = blob.name
    file_part = blob_name.split("/")[-1]          # "<documentId>_<fileName>"

    # Convention de nommage : on coupe au PREMIER underscore.
    # tout ce qui précède = documentId ; le reste = fileName.
    document_id, _, file_name = file_part.partition("_")
    size = blob.length

    logging.info(
        json.dumps({
            "step": "BLOB_TRIGGER",
            "status": "START",
            "documentId": document_id,
            "blobName": blob_name,
            "size": size,
        })
    )

    # 1) Construire le message Service Bus
    message = {
        "documentId": document_id,
        "fileName": file_name,
        "blobName": blob_name,
        "size": size,
        "uploadedAt": datetime.datetime.now(datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
    }

    # 2) Publier dans la file Service Bus
    _publish_to_service_bus(message)

    # 3) Passer le document en QUEUED dans Cosmos (best effort)
    _set_status_queued(document_id)

    # 4) Notifier React : UPLOADED (fonctionnalité 4)
    signalr_client.notify(document_id, "UPLOADED", "Fichier reçu")

    logging.info(
        json.dumps({
            "step": "BLOB_TRIGGER",
            "status": "SUCCESS",
            "documentId": document_id,
        })
    )


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #
def _publish_to_service_bus(message: dict):
    conn = os.environ["SERVICE_BUS_CONNECTION_STRING"]
    queue = os.environ.get("SERVICE_BUS_QUEUE", "documents-queue")

    with ServiceBusClient.from_connection_string(conn) as client:
        with client.get_queue_sender(queue_name=queue) as sender:
            sender.send_messages(
                ServiceBusMessage(
                    json.dumps(message),
                    content_type="application/json",
                )
            )
    logging.info(
        json.dumps({
            "step": "PUBLISH_SERVICE_BUS",
            "status": "SUCCESS",
            "documentId": message["documentId"],
        })
    )


def _set_status_queued(document_id: str):
    """Met le document en QUEUED. Ne fait pas échouer la Function si le
    document n'existe pas (le sujet dit 'mettre éventuellement en QUEUED')."""
    try:
        endpoint = os.environ["COSMOS_ENDPOINT"]
        key = os.environ["COSMOS_KEY"]
        database = os.environ.get("COSMOS_DATABASE", "db-doc")
        container_name = os.environ.get("COSMOS_CONTAINER", "jobs")

        client = CosmosClient(endpoint, credential=key)
        container = client.get_database_client(database).get_container_client(
            container_name
        )

        # pk = "JOB" dans le modèle existant
        doc = container.read_item(item=document_id, partition_key="JOB")
        doc["status"] = "QUEUED"
        doc["updatedAt"] = (
            datetime.datetime.now(datetime.timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
        container.replace_item(item=document_id, body=doc)

        logging.info(
            json.dumps({
                "step": "SET_QUEUED",
                "status": "SUCCESS",
                "documentId": document_id,
            })
        )
    except exceptions.CosmosResourceNotFoundError:
        logging.warning(
            json.dumps({
                "step": "SET_QUEUED",
                "status": "SKIPPED",
                "documentId": document_id,
                "reason": "document introuvable dans Cosmos",
            })
        )
    except Exception as exc:  # noqa: BLE001
        logging.error(
            json.dumps({
                "step": "SET_QUEUED",
                "status": "FAILURE",
                "documentId": document_id,
                "error": str(exc),
            })
        )


# --------------------------------------------------------------------------- #
# Service Bus - Traitement IA (fonctionnalité 2)                              #
# --------------------------------------------------------------------------- #
@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="%SERVICE_BUS_QUEUE%",
    connection="SERVICE_BUS_CONNECTION_STRING",
)
def process_document(msg: func.ServiceBusMessage):
    """Lit un message de la file, fait le traitement IA, met à jour Cosmos.

    Flux : message -> PROCESSING -> tags IA -> PROCESSED.

    Gestion des erreurs (fonctionnalité 5) : toute exception levée ici n'est
    PAS rattrapée, ce qui fait échouer la Function. Service Bus réessaie le
    message ; après maxDeliveryCount tentatives, il le déplace en DLQ.
    Cas couverts :
      - message mal formé        -> json.loads / KeyError lèvent une exception
      - document introuvable     -> on lève KeyError explicitement
      - échec répété de l'IA     -> géré par le fallback, mais si on force une
                                    exception (ex: tags vides) -> remontée
      - exception non gérée      -> remonte naturellement
    """
    # 1) Lire et parser le message
    #    Un message mal formé (JSON invalide, champ manquant) lève ici
    #    une exception -> retries -> DLQ.
    raw = msg.get_body().decode("utf-8")
    data = json.loads(raw)                # JSONDecodeError si mal formé
    document_id = data["documentId"]      # KeyError si champ absent
    file_name = data["fileName"]          # KeyError si champ absent
    correlation_id = data.get("correlationId", "-")

    logging.info(json.dumps({
        "step": "PROCESS_DOCUMENT", "status": "START",
        "documentId": document_id, "fileName": file_name,
    }))

    container = _get_cosmos_container()

    # Document introuvable -> erreur explicite -> retries -> DLQ
    try:
        doc = container.read_item(item=document_id, partition_key="JOB")
    except exceptions.CosmosResourceNotFoundError:
        logging.error(json.dumps({
            "step": "PROCESS_DOCUMENT", "status": "FAILURE",
            "documentId": document_id, "error": "document introuvable",
        }))
        raise  # remonte -> Service Bus réessaie puis DLQ

    # 2) Passer le document en PROCESSING
    doc["status"] = "PROCESSING"
    doc["updatedAt"] = _now_iso()
    container.replace_item(item=document_id, body=doc)
    logging.info(json.dumps({
        "step": "SET_PROCESSING", "status": "SUCCESS",
        "documentId": document_id,
    }))

    # 3) Notifier React : PROCESSING (fonctionnalité 4)
    signalr_client.notify(document_id, "PROCESSING", "Traitement IA en cours")

    # 4) Appeler l'IA pour générer les tags (fonctionnalité 3)
    tags = tagging.generate_tags(file_name, correlation_id, document_id)

    # 5) Mettre à jour Cosmos + 6) passer en PROCESSED
    doc["status"] = "PROCESSED"
    doc["tags"] = tags
    doc["blobName"] = data.get("blobName", doc.get("blobName"))
    doc["size"] = data.get("size", doc.get("size"))
    doc["processedAt"] = _now_iso()
    doc["updatedAt"] = _now_iso()
    container.replace_item(item=document_id, body=doc)

    logging.info(json.dumps({
        "step": "PROCESS_DOCUMENT", "status": "SUCCESS",
        "documentId": document_id, "tags": tags,
    }))

    # 7) Notifier React : PROCESSED avec les tags (fonctionnalité 4)
    signalr_client.notify(document_id, "PROCESSED", "Tagging terminé", tags=tags)


# --------------------------------------------------------------------------- #
# DLQ Alert - surveillance de la Dead Letter Queue (fonctionnalité 6)         #
# --------------------------------------------------------------------------- #
@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="%SERVICE_BUS_QUEUE%/$DeadLetterQueue",
    connection="SERVICE_BUS_CONNECTION_STRING",
)
def dlq_alert(msg: func.ServiceBusMessage):
    """Lit les messages de la DLQ, passe le document en ERROR, notifie React.

    Déclenchée automatiquement quand Service Bus déplace un message dans la
    sous-file "<queue>/$DeadLetterQueue" après épuisement des tentatives.
    """
    document_id = "-"
    reason = "Message envoyé en DLQ après plusieurs échecs"

    # Essayer de récupérer le documentId depuis le corps (peut être illisible
    # si le message était lui-même mal formé).
    try:
        raw = msg.get_body().decode("utf-8")
        data = json.loads(raw)
        document_id = data.get("documentId", "-")
    except (ValueError, UnicodeDecodeError):
        reason = "Message en DLQ illisible / mal formé"

    # Récupérer si possible la raison du dead-lettering fournie par Service Bus.
    try:
        props = msg.application_properties or {}
        dl_reason = props.get(b"DeadLetterReason") or props.get("DeadLetterReason")
        if dl_reason:
            reason = (
                dl_reason.decode() if isinstance(dl_reason, bytes) else str(dl_reason)
            )
    except Exception:  # noqa: BLE001
        pass

    logging.warning(json.dumps({
        "step": "DLQ_ALERT", "status": "START",
        "documentId": document_id, "reason": reason,
    }))

    # Mettre à jour Cosmos : status = ERROR + raison
    try:
        container = _get_cosmos_container()
        try:
            doc = container.read_item(item=document_id, partition_key="JOB")
        except exceptions.CosmosResourceNotFoundError:
            # Document introuvable : on crée une trace minimale.
            doc = {"id": document_id, "pk": "JOB"}

        doc["status"] = "ERROR"
        doc["errorMessage"] = reason
        doc["errorAt"] = _now_iso()
        doc["updatedAt"] = _now_iso()
        container.upsert_item(doc)

        logging.info(json.dumps({
            "step": "DLQ_ALERT", "status": "SUCCESS",
            "documentId": document_id,
        }))
    except Exception as exc:  # noqa: BLE001
        logging.error(json.dumps({
            "step": "DLQ_ALERT", "status": "FAILURE",
            "documentId": document_id, "error": str(exc),
        }))

    # Notifier React : ERROR (fonctionnalité 4)
    signalr_client.notify(document_id, "ERROR", "Erreur de traitement")
