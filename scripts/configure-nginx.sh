#!/usr/bin/env bash
set -Eeuo pipefail

api_domain="api-omnelyo.kgslab.com"
bot_domain="bot-omnelyo.kgslab.com"
expected_ip="72.61.98.7"
dns_wait_seconds=300
certbot_email=""
enable_tls=false

usage() {
  cat <<'USAGE'
Usage: sudo bash scripts/configure-nginx.sh [options]

Options:
  --api-domain DOMAIN   Domaine de l'API
  --bot-domain DOMAIN   Domaine du bot
  --expected-ip IPV4    IPv4 publique attendue
  --dns-wait SECONDES   Attente maximale de propagation DNS
  --email EMAIL         Active Certbot avec cet email
  --no-tls              Configure uniquement HTTP (valeur par défaut)
  --help                Affiche cette aide
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --api-domain) api_domain="${2:?domaine manquant}"; shift 2 ;;
    --bot-domain) bot_domain="${2:?domaine manquant}"; shift 2 ;;
    --expected-ip) expected_ip="${2:?IPv4 manquante}"; shift 2 ;;
    --dns-wait) dns_wait_seconds="${2:?durée manquante}"; shift 2 ;;
    --email) certbot_email="${2:?email manquant}"; enable_tls=true; shift 2 ;;
    --no-tls) enable_tls=false; shift ;;
    --help) usage; exit 0 ;;
    *) echo "Option inconnue : $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  echo "Ce script doit être exécuté avec sudo." >&2
  exit 1
fi

for command_name in nginx sed install readlink; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "Commande requise absente : $command_name" >&2
    exit 1
  }
done

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repository_dir="$(cd -- "$script_dir/.." && pwd)"
template="$repository_dir/deploy/nginx/omnelyo.conf.template"
headers="$repository_dir/deploy/nginx/security-headers.conf"
dns_checker="$repository_dir/scripts/check-dns.sh"
site_available="/etc/nginx/sites-available/omnelyo"
site_enabled="/etc/nginx/sites-enabled/omnelyo"
backup=""

[[ -f "$template" ]] || { echo "Modèle absent : $template" >&2; exit 1; }
[[ -f "$headers" ]] || { echo "En-têtes absents : $headers" >&2; exit 1; }
[[ -f "$dns_checker" ]] || { echo "Contrôleur DNS absent : $dns_checker" >&2; exit 1; }

echo "Vérification de la propagation DNS avant modification de Nginx..."
bash "$dns_checker" --expected-ip "$expected_ip" --wait-seconds "$dns_wait_seconds" \
  "$api_domain" "$bot_domain"

install -d -m 755 /etc/nginx/sites-available /etc/nginx/sites-enabled /etc/nginx/snippets
install -m 644 "$headers" /etc/nginx/snippets/omnelyo-security-headers.conf

temporary_config="$(mktemp /etc/nginx/sites-available/omnelyo.tmp.XXXXXX)"
cleanup() { rm -f "$temporary_config"; }
trap cleanup EXIT

sed \
  -e "s/__API_DOMAIN__/$api_domain/g" \
  -e "s/__BOT_DOMAIN__/$bot_domain/g" \
  "$template" > "$temporary_config"

if [[ -f "$site_available" ]]; then
  backup="${site_available}.backup.$(date -u +%Y%m%dT%H%M%SZ)"
  cp -a "$site_available" "$backup"
fi

install -m 644 "$temporary_config" "$site_available"
ln -sfn "$site_available" "$site_enabled"

if ! nginx -t; then
  echo "Configuration Nginx invalide, restauration." >&2
  rm -f "$site_enabled"
  if [[ -n "$backup" ]]; then
    cp -a "$backup" "$site_available"
    ln -sfn "$site_available" "$site_enabled"
  else
    rm -f "$site_available"
  fi
  nginx -t || true
  exit 1
fi

systemctl reload nginx
echo "Configuration HTTP Omnelyo installée et Nginx rechargé."

if [[ "$enable_tls" == true ]]; then
  if ! command -v certbot >/dev/null 2>&1; then
    command -v apt-get >/dev/null 2>&1 || {
      echo "Certbot est absent et apt-get n'est pas disponible." >&2
      exit 1
    }
    echo "Installation automatique de Certbot et de son module Nginx..."
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y certbot python3-certbot-nginx
  fi
  certbot --nginx --non-interactive --agree-tos --redirect \
    --email "$certbot_email" \
    -d "$api_domain" -d "$bot_domain"
  nginx -t
  systemctl reload nginx
  echo "Certificats TLS installés pour l'API et le bot."
else
  echo "TLS non demandé. Relance avec --email adresse@example.com après validation DNS."
fi
