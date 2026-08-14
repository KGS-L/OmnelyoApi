#!/usr/bin/env bash
set -Eeuo pipefail

template_path="${1:-.env.production.example}"
env_path="${2:-.env}"

if [[ -s "$env_path" ]]; then
  echo "$env_path existe et n'est pas vide : aucune modification."
  exit 0
fi

if [[ ! -f "$template_path" ]]; then
  echo "Modèle de production introuvable : $template_path" >&2
  exit 1
fi

command -v openssl >/dev/null 2>&1 || {
  echo "openssl est requis pour générer les secrets." >&2
  exit 1
}

umask 077
postgres_password="$(openssl rand -hex 24)"
redis_password="$(openssl rand -hex 24)"
jwt_secret="$(openssl rand -hex 48)"
temporary_file="$(mktemp "${env_path}.tmp.XXXXXX")"

cleanup() {
  rm -f "$temporary_file"
}
trap cleanup EXIT

sed \
  -e "s/__POSTGRES_PASSWORD__/$postgres_password/g" \
  -e "s/__REDIS_PASSWORD__/$redis_password/g" \
  -e "s/__API_JWT_SECRET__/$jwt_secret/g" \
  "$template_path" > "$temporary_file"

if grep -qE '__[A-Z0-9_]+__' "$temporary_file"; then
  echo "Le modèle contient encore un marqueur non remplacé." >&2
  exit 1
fi

mv "$temporary_file" "$env_path"
chmod 600 "$env_path"
trap - EXIT

echo "$env_path a été créé avec des secrets PostgreSQL, Redis et JWT uniques."
echo "Renseigne maintenant les clés externes laissées vides avant de relancer le déploiement."
