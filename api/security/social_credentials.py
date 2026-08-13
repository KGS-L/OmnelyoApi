"""Chiffrement authentifié des secrets OAuth sociaux."""
from cryptography.fernet import Fernet, InvalidToken


class SocialCredentialCipher:
    def __init__(self, key: str) -> None:
        if not key:
            raise RuntimeError("SOCIAL_CREDENTIALS_KEY n'est pas configurée.")
        try:
            self._fernet = Fernet(key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise RuntimeError("SOCIAL_CREDENTIALS_KEY est invalide.") from exc

    def encrypt(self, token: str) -> str:
        if not token:
            raise ValueError("Un token vide ne peut pas être chiffré.")
        return self._fernet.encrypt(token.encode("utf-8")).decode("ascii")

    def decrypt(self, encrypted_token: str) -> str:
        try:
            return self._fernet.decrypt(encrypted_token.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError) as exc:
            raise RuntimeError("Le credential social ne peut pas être déchiffré.") from exc
