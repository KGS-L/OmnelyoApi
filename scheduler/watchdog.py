"""
Vérification quotidienne (cron indépendant) :
- clips dont scheduled_publish_at est passé mais status != 'published'
- alerte via le bot Telegram si problème détecté
"""


def check_scheduled_clips() -> None:
    """
    Requête la DB pour les clips en retard, vérifie leur statut réel
    via youtube_uploader.check_publish_status, et notifie en cas d'anomalie.
    """
    raise NotImplementedError
