#!/usr/bin/env bash
set -euo pipefail

# Point this to the backup directory you want to restore from
BACKUP_ROOT="${1:-}"
if [ -z "$BACKUP_ROOT" ] || [ ! -d "$BACKUP_ROOT" ]; then
  echo "Usage: $0 /path/to/homelab-backups/<TIMESTAMP>"
  exit 1
fi

VOL_DIR="${BACKUP_ROOT}/volumes"
MANIFEST_DIR="${BACKUP_ROOT}/manifests"
CERT_DIR="${BACKUP_ROOT}/certs"

echo "==> Ensuring Docker is available"
command -v docker >/dev/null || { echo "Docker not found"; exit 1; }

echo "==> Recreating volumes and restoring data"
for archive in "${VOL_DIR}"/*.tar.gz; do
  [ -e "$archive" ] || continue
  vol=$(basename "${archive%.tar.gz}")
  echo "  -> ${vol}"
  docker volume create "$vol" >/dev/null
  docker run --rm \
    -v "${vol}:/v" \
    -v "${VOL_DIR}:/backup" \
    alpine sh -c "cd /v && tar xzf /backup/${vol}.tar.gz"
done

# Optional: recreate a shared network if you use it (e.g., 'proxy')
echo "==> Recreating shared network 'proxy' (if you use Caddy reverse-proxy)"
docker network ls --format '{{.Name}}' | grep -qw proxy || docker network create proxy

# Optional: restore Homepage binds if you backed them up here and want to reuse same path
if [ -f "${BACKUP_ROOT}/homepage-config.tar.gz" ]; then
  mkdir -p ./config
  tar xzf "${BACKUP_ROOT}/homepage-config.tar.gz" -C .
fi
if [ -f "${BACKUP_ROOT}/homepage-public.tar.gz" ]; then
  mkdir -p ./public
  tar xzf "${BACKUP_ROOT}/homepage-public.tar.gz" -C .
fi

# Your compose files (if you backed them up here)
if [ -f "${MANIFEST_DIR}/docker-compose.yml" ] || [ -f "${MANIFEST_DIR}/docker-compose.yaml" ]; then
  echo "==> Restoring compose files into ./stack"
  mkdir -p ./stack
  cp -a "${MANIFEST_DIR}"/docker-compose*.yml ./stack/ 2>/dev/null || true
  [ -f "${MANIFEST_DIR}/.env" ] && cp -a "${MANIFEST_DIR}/.env" ./stack/
  echo "==> Starting stack"
  (cd ./stack && docker compose up -d)
else
  echo "NOTE: No compose files in backup; start containers with your usual compose/projects."
fi

# FYI: if you use Caddy local TLS, you'll still need to re-trust the new CA on clients
if [ -f "${CERT_DIR}/caddy-rootCA.crt" ]; then
  echo "Caddy local root CA saved at: ${CERT_DIR}/caddy-rootCA.crt"
fi

echo "==> Restore finished"
