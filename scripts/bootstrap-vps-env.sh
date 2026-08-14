#!/usr/bin/env bash
set -Eeuo pipefail

template_path="${1:-.env.production.example}"
env_path="${2:-.env}"

[[ -f "$template_path" ]] || {
  echo "Modèle de production introuvable : $template_path" >&2
  exit 1
}
command -v openssl >/dev/null 2>&1 || {
  echo "openssl est requis pour générer les secrets." >&2
  exit 1
}

umask 077
touch "$env_path"
chmod 600 "$env_path"

# Retourne la dernière valeur non vide sans exécuter le contenu du .env.
last_nonempty_value() {
  local key="$1"
  awk -v key="$key" '
    index($0, key "=") == 1 {
      value = substr($0, length(key) + 2)
      if (value != "") last = value
    }
    END { if (last != "") print last }
  ' "$env_path"
}

postgres_password="$(last_nonempty_value POSTGRES_PASSWORD)"
redis_password="$(last_nonempty_value REDIS_PASSWORD)"
jwt_secret="$(last_nonempty_value API_JWT_SECRET)"

[[ -n "$postgres_password" ]] || postgres_password="$(openssl rand -hex 24)"
[[ -n "$redis_password" ]] || redis_password="$(openssl rand -hex 24)"
[[ -n "$jwt_secret" ]] || jwt_secret="$(openssl rand -hex 48)"

# Les mots de passe générés sont sûrs dans une URL. Si une valeur existante est
# plus complexe, l'URL de connexion doit déjà être renseignée explicitement.
if [[ ! "$postgres_password" =~ ^[A-Za-z0-9._~-]+$ ]] \
  && ! grep -q '^API_DATABASE_URL=.' "$env_path"; then
  echo "POSTGRES_PASSWORD contient des caractères à encoder : renseigne API_DATABASE_URL." >&2
  exit 1
fi
if [[ ! "$redis_password" =~ ^[A-Za-z0-9._~-]+$ ]] \
  && ! grep -q '^REDIS_URL=.' "$env_path"; then
  echo "REDIS_PASSWORD contient des caractères à encoder : renseigne REDIS_URL." >&2
  exit 1
fi

resolved_template="$(mktemp "${env_path}.template.XXXXXX")"
cleanup() { rm -f "$resolved_template"; }
trap cleanup EXIT

sed \
  -e "s/__POSTGRES_PASSWORD__/$postgres_password/g" \
  -e "s/__REDIS_PASSWORD__/$redis_password/g" \
  -e "s/__API_JWT_SECRET__/$jwt_secret/g" \
  "$template_path" > "$resolved_template"

grep -qE '__[A-Z0-9_]+__' "$resolved_template" && {
  echo "Le modèle contient encore un marqueur non remplacé." >&2
  exit 1
}

added=0
while IFS= read -r line || [[ -n "$line" ]]; do
  [[ "$line" =~ ^([A-Z][A-Z0-9_]*)=(.*)$ ]] || continue
  key="${BASH_REMATCH[1]}"
  value="${BASH_REMATCH[2]}"

  # Une valeur existante, même personnalisée, reste prioritaire. Pour les trois
  # secrets internes, une ligne vide est complétée en ajoutant la valeur sûre à
  # la fin du fichier (les lecteurs dotenv utilisent la dernière occurrence).
  if grep -q "^${key}=" "$env_path"; then
    if [[ "$key" =~ ^(POSTGRES_PASSWORD|REDIS_PASSWORD|API_JWT_SECRET)$ ]] \
      && ! grep -q "^${key}=." "$env_path"; then
      printf '%s=%s\n' "$key" "$value" >> "$env_path"
      added=$((added + 1))
    fi
    continue
  fi

  printf '%s=%s\n' "$key" "$value" >> "$env_path"
  added=$((added + 1))
done < "$resolved_template"

chmod 600 "$env_path"
trap - EXIT
rm -f "$resolved_template"

if (( added == 0 )); then
  echo "$env_path est déjà complet : aucune modification."
else
  echo "$env_path complété avec $added variable(s) manquante(s), sans écraser les valeurs existantes."
fi
