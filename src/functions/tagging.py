"""
Tagging IA (fonctionnalité 3).

Génère entre 3 et 8 tags courts en français à partir du nom de fichier.

Stratégie :
  1. Appel de l'IA Google Gemini (API gratuite via clé GEMINI_API_KEY).
  2. Si l'appel échoue (clé absente, quota, réseau, format inattendu),
     bascule automatique sur un fallback déterministe par règles.
Ainsi le pipeline ne se bloque jamais, même sans IA disponible.
"""
import json
import logging
import os
import re
from typing import List

import requests

# Modèle gratuit et rapide, adapté à une tâche simple de tagging.
_GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

_PROMPT = (
    "Analyse le nom de fichier suivant et génère entre 3 et 8 tags courts "
    "en français.\n"
    "Nom du fichier : {file_name}\n\n"
    "Retourne uniquement un tableau JSON de chaînes."
)


# --------------------------------------------------------------------------- #
# Fallback par règles                                                         #
# --------------------------------------------------------------------------- #
_RULES = {
    r"\bcv\b": ["cv", "rh"],
    "lettre": ["lettre", "courrier"],
    "facture": ["facture", "comptabilite"],
    "contrat": ["contrat", "juridique"],
    "rapport": ["rapport", "document"],
    "azure": ["azure", "cloud"],
    "cloud": ["cloud"],
    "blockchain": ["blockchain", "tech"],
    "projet": ["projet"],
}
_EXT_TAGS = {
    "pdf": "pdf", "docx": "word", "doc": "word",
    "xlsx": "excel", "xls": "excel",
    "png": "image", "jpg": "image", "jpeg": "image",
    "txt": "texte", "csv": "data",
}


def _fallback_tags(file_name: str) -> List[str]:
    """Génère des tags sans IA, à partir de règles simples sur le nom."""
    name = file_name.lower()
    tags: List[str] = []

    for pattern, values in _RULES.items():
        if re.search(pattern, name):
            tags.extend(values)

    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    if ext in _EXT_TAGS:
        tags.append(_EXT_TAGS[ext])

    tags.append("document")

    # Déduplication en conservant l'ordre.
    seen, result = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t)
            result.append(t)

    # Garantir entre 3 et 8 tags.
    if len(result) < 3:
        for extra in ["fichier", "data", "document"]:
            if extra not in seen:
                result.append(extra)
                seen.add(extra)
            if len(result) >= 3:
                break
    return result[:8]


# --------------------------------------------------------------------------- #
# Appel IA (Gemini)                                                           #
# --------------------------------------------------------------------------- #
def _gemini_tags(file_name: str) -> List[str]:
    """Appelle l'API Gemini et retourne la liste de tags.
    Lève une exception en cas de problème (capturée par l'appelant)."""
    api_key = os.environ["GEMINI_API_KEY"]  # KeyError si absente -> fallback
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{_GEMINI_MODEL}:generateContent"
    )
    payload = {
        "contents": [
            {"parts": [{"text": _PROMPT.format(file_name=file_name)}]}
        ]
    }
    response = requests.post(
        url,
        params={"key": api_key},
        json=payload,
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()

    # Extraire le texte généré.
    text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    # Nettoyer d'éventuels ``` ou ```json autour du tableau.
    text = re.sub(r"^```(?:json)?|```$", "", text.strip()).strip()

    tags = json.loads(text)
    if not isinstance(tags, list) or not (3 <= len(tags) <= 8):
        raise ValueError(f"réponse IA hors format attendu : {tags!r}")

    return [str(t).strip().lower() for t in tags if str(t).strip()]


# --------------------------------------------------------------------------- #
# Point d'entrée public                                                       #
# --------------------------------------------------------------------------- #
def generate_tags(file_name: str, correlation_id: str = "-",
                  document_id: str = "-") -> List[str]:
    """Retourne 3 à 8 tags pour le fichier. IA d'abord, sinon fallback."""
    try:
        tags = _gemini_tags(file_name)
        logging.info(json.dumps({
            "step": "AI_TAGGING", "status": "SUCCESS",
            "documentId": document_id, "source": "gemini", "tags": tags,
        }))
        return tags
    except Exception as exc:  # noqa: BLE001 - on veut toujours un fallback
        tags = _fallback_tags(file_name)
        logging.warning(json.dumps({
            "step": "AI_TAGGING", "status": "FALLBACK",
            "documentId": document_id, "source": "rules",
            "reason": str(exc), "tags": tags,
        }))
        return tags
