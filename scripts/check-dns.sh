#!/usr/bin/env bash
set -Eeuo pipefail

expected_ip="72.61.98.7"
wait_seconds=300
interval_seconds=15
domains=()

usage() {
  cat <<'USAGE'
Usage: bash scripts/check-dns.sh [options] DOMAIN [DOMAIN...]

Options:
  --expected-ip IPV4       IPv4 publique attendue (défaut : 72.61.98.7)
  --wait-seconds SECONDES  Temps maximal de propagation (défaut : 300)
  --interval SECONDES      Intervalle entre deux contrôles (défaut : 15)
  --help                   Affiche cette aide
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --expected-ip) expected_ip="${2:?IPv4 manquante}"; shift 2 ;;
    --wait-seconds) wait_seconds="${2:?durée manquante}"; shift 2 ;;
    --interval) interval_seconds="${2:?intervalle manquant}"; shift 2 ;;
    --help) usage; exit 0 ;;
    --*) echo "Option inconnue : $1" >&2; usage >&2; exit 2 ;;
    *) domains+=("$1"); shift ;;
  esac
done

[[ ${#domains[@]} -gt 0 ]] || { echo "Au moins un domaine est requis." >&2; exit 2; }
[[ "$expected_ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || {
  echo "IPv4 attendue invalide : $expected_ip" >&2
  exit 2
}
[[ "$wait_seconds" =~ ^[0-9]+$ ]] || { echo "Durée invalide." >&2; exit 2; }
[[ "$interval_seconds" =~ ^[1-9][0-9]*$ ]] || { echo "Intervalle invalide." >&2; exit 2; }

deadline=$((SECONDS + wait_seconds))
while true; do
  all_valid=true

  for domain in "${domains[@]}"; do
    resolved_ips="$(getent ahostsv4 "$domain" 2>/dev/null | awk '{print $1}' | sort -u || true)"
    if grep -Fxq "$expected_ip" <<<"$resolved_ips"; then
      echo "DNS valide : $domain -> $expected_ip"
    else
      all_valid=false
      if [[ -n "$resolved_ips" ]]; then
        echo "DNS en attente : $domain -> ${resolved_ips//$'\n'/, } (attendu : $expected_ip)" >&2
      else
        echo "DNS en attente : $domain ne possède pas encore d'IPv4 visible." >&2
      fi
    fi
  done

  [[ "$all_valid" == true ]] && exit 0
  if (( SECONDS >= deadline )); then
    echo "La vérification DNS a expiré après ${wait_seconds}s." >&2
    exit 1
  fi
  sleep "$interval_seconds"
done
