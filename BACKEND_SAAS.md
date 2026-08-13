# Backend SaaS

Le backend web vit dans `api/` et reste séparé du processus Telegram historique.
PostgreSQL est la source de vérité pour les comptes et workspaces ; Redis contient
les OTP et, plus tard, la file de production.

## Démarrage local

```bash
docker compose up -d postgres redis api
```

L'API est disponible sur `http://localhost:8000`, Swagger sur `/docs` et le schéma
OpenAPI sur `/openapi.json`. Le service `api` exécute `alembic upgrade head` avant
de démarrer.

## Authentification

- `POST /v1/auth/email/request-otp` demande un code.
- `POST /v1/auth/email/verify` échange le code contre access + refresh tokens.
- `POST /v1/auth/google` vérifie un Google ID Token côté serveur.
- `POST /v1/auth/refresh` effectue une rotation du refresh token.
- `POST /v1/auth/logout` révoque le refresh token.
- `GET /v1/users/me` retourne le profil authentifié.

Les access tokens durent 15 minutes par défaut. Les refresh tokens sont aléatoires,
stockés uniquement sous forme SHA-256, rotatifs et révocables. Les codes OTP sont
hachés avec HMAC, expirent dans Redis et sont limités par adresse.

## Google

`GOOGLE_WEB_CLIENT_ID` correspond au client Web Google Identity Services du futur
frontend. Il est distinct du client OAuth YouTube : l'un authentifie le compte
SaaS, l'autre autorise explicitement la publication sur une chaîne.

## Email

`EmailSender` est volontairement une interface sans prestataire pour l'instant.
En développement, `EXPOSE_DEV_OTP=true` peut renvoyer le code dans la réponse.
Cette option est automatiquement ignorée en production. Avant un déploiement réel,
brancher Resend, Brevo ou un SMTP transactionnel et laisser `EXPOSE_DEV_OTP=false`.

## Modèle multi-tenant

Une première connexion crée :

1. un `User` ;
2. une `AuthIdentity` (`email` ou `google`) ;
3. un `Workspace` ;
4. un membership avec rôle `owner`.

Toute future ressource métier devra avoir un `workspace_id`. L'autorisation devra
toujours vérifier le membership dans PostgreSQL, jamais accepter un workspace ID
du frontend sans contrôle.
