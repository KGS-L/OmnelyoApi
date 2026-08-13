"""Validation serveur d'un Google ID Token."""
from google.auth.transport import requests
from google.oauth2 import id_token


def verify_google_credential(credential: str, client_id: str) -> dict:
    if not client_id:
        raise ValueError("GOOGLE_WEB_CLIENT_ID n'est pas configuré.")
    claims = id_token.verify_oauth2_token(credential, requests.Request(), client_id)
    if not claims.get("sub") or not claims.get("email"):
        raise ValueError("Le token Google ne contient pas l'identité attendue.")
    if not claims.get("email_verified"):
        raise ValueError("L'adresse Google n'est pas vérifiée.")
    return claims
