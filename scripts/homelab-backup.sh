#!/usr/bin/env bash
set -euo pipefail

STAMP=$(date +%F_%H%M%S)
ROOT="${HOME}/homelab-backups"
BACKUP="${ROOT}/${STAMP}"
VOL_DIR="${BACKUP}/volumes"
MANIFEST_DIR="${BACKUP}/manifests"
CERT_DIR="${BACKUP}/certs"
BIND_DIR="${BACKUP}/bind-mounts"
COMPOSE_DIR="${BACKUP}/compose-files"

mkdir -p "$VOL_DIR" "$MANIFEST_DIR" "$CERT_DIR" "$BIND_DIR" "$COMPOSE_DIR" "$ROOT"

echo "==> Writing Docker manifests"
docker ps -a --format '{{.Names}}\t{{.Image}}' > "${MANIFEST_DIR}/containers.tsv" || true
( docker ps -aq | xargs -r docker inspect ) > "${MANIFEST_DIR}/containers.json" || true
docker images --format '{{.Repository}}:{{.Tag}}' > "${MANIFEST_DIR}/images.txt" || true
docker network ls --format '{{.Name}}' > "${MANIFEST_DIR}/networks.txt" || true
docker volume ls -q > "${MANIFEST_DIR}/volumes.txt" || true

echo "==> Exporting named volumes"
for v in $(docker volume ls -q); do
  echo "  -> $v"
  docker run --rm -v "${v}:/v:ro" -v "${VOL_DIR}:/b" alpine sh -c "cd /v && tar czf /b/${v}.tar.gz ."
done

echo "==> Copying Caddy local root CA (if present)"
docker cp caddy:/data/caddy/pki/authorities/local/root.crt "${CERT_DIR}/caddy-rootCA.crt" 2>/dev/null || true

echo "==> Archiving common bind mounts in current dir (if present)"
[ -d ./public ]   && tar czf "${BIND_DIR}/homepage-public.tar.gz"  ./public
[ -d ./config ]   && tar czf "${BIND_DIR}/homepage-config.tar.gz"  ./config
[ -f ./Caddyfile ] && cp -a ./Caddyfile "${BIND_DIR}/"

echo "==> Discovering bind mounts from running containers (under \$HOME)"
declare -A SEEN=()
for cid in $(docker ps -q); do
  while IFS= read -r line; do
    # "bind <Source> <Destination>"
    src=$(printf '%s\n' "$line" | awk '{print $2}')
    dst=$(printf '%s\n' "$line" | awk '{print $3}')
    [ -z "${src:-}" ] && continue
    case "$src" in
      $HOME/*)
        [ -e "$src" ] || continue
        [ -n "${SEEN[$src]:-}" ] && continue
        SEEN[$src]=1
        safe="${src#/}"; safe="${safe//\//__}"
        out="${BIND_DIR}/${safe}.tar.gz"
        echo "  -> bind ${src} (-> ${dst})"
        sudo tar czf "$out" -C / "${src#/}"
        ;;
    esac
  done < <(docker inspect -f '{{range .Mounts}}{{if eq .Type "bind"}}bind {{.Source}} {{.Destination}}{{printf "\n"}}{{end}}{{end}}' "$cid")
done

echo "==> Collecting compose files via container labels (if any)"
for cid in $(docker ps -q); do
  wd=$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' "$cid")
  cfg=$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project.config_files" }}' "$cid")
  [ -n "$wd" ] && [ -d "$wd" ] || continue
  # config_files is ; separated relative paths
  IFS=';' read -r -a files <<< "${cfg:-}"
  for f in "${files[@]:-}"; do
    [ -f "$wd/$f" ] || continue
    rel="${wd%/}/$f"; rel="${rel#/}"
    cp -a "$wd/$f" "${COMPOSE_DIR}/$(echo "$rel" | sed 's#/#__#g')"
  done
  # include .env if present
  [ -f "$wd/.env" ] && cp -a "$wd/.env" "${COMPOSE_DIR}/$(echo "${wd#/}/.env" | sed 's#/#__#g')"
done

echo "==> Also scanning common paths for compose files"
for root in "$PWD" "$HOME" "$HOME/docker" "$HOME/homepage"; do
  [ -d "$root" ] || continue
  find "$root" -maxdepth 3 -type f \( -name 'docker-compose.y*ml' -o -name 'compose.y*ml' -o -name '.env' \) -print0 |
  while IFS= read -r -d '' f; do
    rel="${f#/}"
    out="${COMPOSE_DIR}/$(echo "$rel" | sed 's#/#__#g')"
    [ -f "$out" ] || cp -a "$f" "$out"
  done
done

echo "==> Saving images for running containers"
IMAGES_FILE="${BACKUP}/running-images.txt"
docker ps --format '{{.Image}}' | sort -u > "$IMAGES_FILE"
if [ -s "$IMAGES_FILE" ]; then
  xargs -r docker pull < "$IMAGES_FILE" || true
  docker save -o "${BACKUP}/images.tar" $(cat "$IMAGES_FILE")
fi

echo "==> Writing LATEST pointer and rotating old backups (keep 7)"
echo "$BACKUP" > "${ROOT}/LATEST"
# delete anything older than 7 newest
ls -1dt "${ROOT}"/*/ 2>/dev/null | tail -n +8 | xargs -r rm -rf

echo "==> Backup complete at: ${BACKUP}"
echo "To restore later:  ./homelab-restore.sh \"${BACKUP}\""
