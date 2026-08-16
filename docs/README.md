# Documentation

Le [README racine](../README.md) reste la porte d'entrée du projet : fonctionnalités,
installation, configuration et sécurité. Ce dossier regroupe la documentation
complémentaire.

## Sommaire

| Document | Contenu |
|---|---|
| [implementation-backend.md](implementation-backend.md) | Feuille de route de référence et état réel d'avancement |
| [ci-cd.md](ci-cd.md) | CI GitHub Actions, déploiement VPS, rollback et configuration Nginx |
| [decisions.md](decisions.md) | Décisions produit/techniques en attente et cartographie de la dette |

## Conventions

- Une décision prise est déplacée de `decisions.md` vers un numéro d'ADR
  (`adr/NNNN-sujet.md`) avec son contexte et ses conséquences, dès que le dossier
  `adr/` devient nécessaire.
- Les documents datés portent leur date de dernière analyse en tête de fichier.
- Les liens internes sont relatifs au dépôt, jamais absolus.
