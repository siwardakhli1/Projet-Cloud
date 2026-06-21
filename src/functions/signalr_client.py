"""
Helper SignalR (fonctionnalité 4) - envoi de notifications temps réel à React.

Mode Serverless : on signe un JWT court (HS256) avec l'AccessKey extraite de
la connection string SignalR, puis on POST le message sur le hub via l'API REST.
L'événement côté React s'appelle "documentUpdate".

Une notification perdue ne doit jamais faire échouer le traitement métier :
toutes les erreurs sont avalées et journalisées.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import time
from typing import List, Optional

import requests

_HUB = os.environ.get("SIGNALR_HUB", "documents")


def _parse_conn_str(conn_str: str):
    parts = dict(kv.split("=", 1) for kv in conn_str.split(";") if "=" in kv)
    return parts["Endpoint"].rstrip("/"), parts["AccessKey"]


def _build_token(audience: str, access_key: str, ttl: int = 60) -> str:
    """Génère un JWT HS256 signé avec l'AccessKey SignalR."""
    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"aud": audience, "exp": int(time.time()) + ttl}
    signing_input = (
        b64(json.dumps(header).encode())
        + "."
        + b64(json.dumps(payload).encode())
    )
    signature = hmac.new(
        access_key.encode(), signing_input.encode(), hashlib.sha256
    ).digest()
    return signing_input + "." + b64(signature)


def notify(document_id: str, status: str, message: str,
           tags: Optional[List[str]] = None) -> None:
    """Diffuse un événement d'état du document à tous les clients du hub.

    Construit un événement conforme au sujet :
        {"documentId": ..., "status": ..., "message": ..., "tags"?: [...]}
    """
    conn = os.environ.get("SIGNALR_CONNECTION_STRING")
    if not conn:
        logging.warning(json.dumps({
            "step": "SIGNALR_NOTIFY", "status": "SKIPPED",
            "documentId": document_id, "reason": "SIGNALR non configuré",
        }))
        return

    try:
        endpoint, access_key = _parse_conn_str(conn)
        url = f"{endpoint}/api/v1/hubs/{_HUB}"
        token = _build_token(url, access_key)

        event = {
            "documentId": document_id,
            "status": status,
            "message": message,
        }
        if tags is not None:
            event["tags"] = tags

        body = {"target": "documentUpdate", "arguments": [event]}

        resp = requests.post(
            url,
            json=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        resp.raise_for_status()
        logging.info(json.dumps({
            "step": "SIGNALR_NOTIFY", "status": "SUCCESS",
            "documentId": document_id, "event": status,
        }))
    except Exception as exc:  # noqa: BLE001
        logging.error(json.dumps({
            "step": "SIGNALR_NOTIFY", "status": "FAILURE",
            "documentId": document_id, "error": str(exc),
        }))
