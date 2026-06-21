"""
Endpoint de négociation SignalR (fonctionnalité 4).

React appelle POST /signalr/negotiate pour obtenir l'URL du service SignalR
et un token d'accès client. C'est le point d'entrée du mode Serverless.
"""
import base64
import hashlib
import hmac
import json
import time

from fastapi import APIRouter, HTTPException

from .config import settings

router = APIRouter()


def _parse_conn_str(conn_str: str):
    parts = dict(kv.split("=", 1) for kv in conn_str.split(";") if "=" in kv)
    return parts["Endpoint"].rstrip("/"), parts["AccessKey"]


def _build_token(audience: str, access_key: str, ttl: int = 3600) -> str:
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


@router.post("/signalr/negotiate")
def signalr_negotiate():
    """Retourne l'URL du hub et un token d'accès pour le client React."""
    conn = settings.signalr_connection_string
    if not conn:
        raise HTTPException(status_code=500, detail="SignalR non configuré")

    hub = settings.signalr_hub
    endpoint, access_key = _parse_conn_str(conn)

    audience = f"{endpoint}/client/?hub={hub}"
    token = _build_token(audience, access_key)

    return {"url": audience, "accessToken": token}
