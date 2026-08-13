# CI/CD avec GitHub Actions

## Fichiers Compose

- `docker-compose.yml` contient tous les services communs.
- `docker-compose.override.yml` est chargé automatiquement en développement :
  ports locaux, montage du code et rechargement automatique.
- `docker-compose.prod.yml` ajoute Caddy et les volumes HTTPS sans exposer
  PostgreSQL ni Redis.

```bash
# Développement
docker compose up -d --build

# Production
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

En production, ne jamais ajouter `docker-compose.override.yml` à la commande.

## CI

`.github/workflows/ci.yml` s'exécute sur les pull requests et les pushes vers
`main`. Il utilise uniquement Linux et :

1. installe les dépendances minimales de `requirements-ci.txt` ;
2. exécute les tests ;
3. compile les modules Python ;
4. applique Alembic sur un vrai PostgreSQL éphémère ;
5. valide les compositions Docker.

Les anciennes exécutions de la même branche sont annulées automatiquement. Aucun
artefact lourd ni image Docker n'est envoyé à GitHub, ce qui économise minutes et
stockage.

## CD

Le déploiement est volontairement manuel depuis l'onglet Actions, workflow
`Deploy production`. Sur un dépôt privé avec GitHub Free, configure les secrets
au niveau du dépôt dans `Settings > Secrets and variables > Actions` :

- `VPS_HOST` : adresse du serveur ;
- `VPS_USER` : utilisateur Linux de déploiement, sans accès root direct ;
- `VPS_PROJECT_PATH` : dépôt déjà cloné sur le serveur ;
- `VPS_SSH_PRIVATE_KEY` : clé privée dédiée au déploiement ;
- `VPS_HOST_KEY` : ligne complète de la clé hôte SSH, obtenue par un canal sûr.

Le VPS doit avoir Git, Docker Compose, le dépôt cloné et son propre `.env` de
production. Les secrets applicatifs ne sont jamais copiés depuis GitHub.

Les environnements et leurs secrets ne sont pas disponibles pour les dépôts privés
sur GitHub Free. Si le dépôt devient public ou si le compte passe à GitHub Pro,
tu pourras ajouter `environment: production` au job et imposer des protections.

Le workflow récupère la révision choisie, construit les images et démarre les
services. Pour un dépôt privé, configure sur le VPS une deploy key GitHub en lecture
seule afin que `git fetch` fonctionne.

## Sécurité du runner

La CI utilise un runner GitHub hébergé. Il est possible plus tard d'installer un
runner auto-hébergé sur une machine séparée, mais il ne faut pas exécuter de pull
requests non fiables directement sur le VPS de production. Un workflow malveillant
pourrait autrement accéder aux fichiers et services du serveur.
