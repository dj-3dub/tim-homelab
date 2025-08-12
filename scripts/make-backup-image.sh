#!/usr/bin/env bash
set -euo pipefail

# 0) Make a fresh backup first (uses sudo for root-owned binds like caddy_config)
sudo -v
sudo env HOME=/home/tim /home/tim/homelab-backup.sh
sudo chown -R tim:tim /home/tim/homelab-backups

BACKUP_DIR="$(cat /home/tim/homelab-backups/LATEST)"
[ -d "$BACKUP_DIR" ] || { echo "Backup folder not found"; exit 1; }

STAMP=$(date +%F_%H%M%S)
BUILD_ROOT="$HOME/homelab-image-build-$STAMP"
BUNDLE_DIR="$BUILD_ROOT/bundle"

echo "==> Preparing build context at: $BUILD_ROOT"
mkdir -p "$BUNDLE_DIR"
rsync -a "$BACKUP_DIR"/ "$BUNDLE_DIR/backup/"

# Drop restore script into the bundle
if [ -f "$HOME/homelab-restore.sh" ]; then
  cp -a "$HOME/homelab-restore.sh" "$BUNDLE_DIR/homelab-restore.sh"
else
  # Minimal inline restore helper (calls your backup’s structure)
  cat > "$BUNDLE_DIR/homelab-restore.sh" <<'RS'
#!/usr/bin/env bash
set -euo pipefail
BACKUP="${1:-}"
if [ -z "$BACKUP" ] || [ ! -d "$BACKUP" ]; then
  echo "Usage: $0 /path/to/backup"
  exit 1
fi
VOL_DIR="$BACKUP/volumes"
[ -d "$VOL_DIR" ] || { echo "No volumes dir in $BACKUP"; exit 1; }
echo "Restoring volumes..."
for a in "$VOL_DIR"/*.tar.gz; do
  [ -e "$a" ] || continue
  v="$(basename "${a%.tar.gz}")"
  echo "  -> $v"
  docker volume create "$v" >/dev/null
  docker run --rm -v "$v:/v" -v "$VOL_DIR:/b" alpine sh -c "cd /v && tar xzf /b/$v.tar.gz"
done
echo "If you backed up compose files, copy them out of ./compose-files and run: docker compose up -d"
RS
  chmod +x "$BUNDLE_DIR/homelab-restore.sh"
fi

# Helpful README
cat > "$BUNDLE_DIR/README.txt" <<TXT
This image contains your homelab backup and restore tools.

To extract on any host:
  docker create --name homelab-bundle IMAGE_TAG
  docker cp homelab-bundle:/bundle ./bundle
  docker rm homelab-bundle

Then restore (as root/admin):
  sudo ./bundle/homelab-restore.sh ./bundle/backup

What's inside /bundle:
  backup/          -> volumes/*.tar.gz, bind-mount archives, compose-files, manifests, images.tar (if present)
  homelab-restore.sh
  README.txt
TXT

# Dockerfile
cat > "$BUILD_ROOT/Dockerfile" <<'DF'
FROM busybox:latest
LABEL org.opencontainers.image.title="Homelab Backup" \
      org.opencontainers.image.description="Tim's Docker volumes, configs, compose files, and saved images" \
      org.opencontainers.image.authors="Tim" \
      org.opencontainers.image.source="local"
COPY bundle /bundle
# No entrypoint; this is a data image. Extract /bundle with docker cp (see README.txt)
CMD ["sh","-c","echo 'Backup image ready. To extract: docker create --name homelab-bundle $HOSTNAME && docker cp homelab-bundle:/bundle ./bundle && docker rm homelab-bundle'"]
DF

# Build & tag
IMAGE_TAG="homelab-backup:$STAMP"
echo "==> Building image: $IMAGE_TAG"
docker build -t "$IMAGE_TAG" "$BUILD_ROOT"

echo
echo "Done. Your backup image: $IMAGE_TAG"
echo
echo "To verify contents (lists top-level of /bundle):"
echo "  docker run --rm $IMAGE_TAG ls -la /bundle"
echo
echo "To extract on any host:"
echo "  docker create --name homelab-bundle $IMAGE_TAG"
echo "  docker cp homelab-bundle:/bundle ./bundle"
echo "  docker rm homelab-bundle"
echo "  sudo ./bundle/homelab-restore.sh ./bundle/backup"
echo
echo "Optional: push to a PRIVATE registry (replace with yours):"
echo "  docker tag $IMAGE_TAG ghcr.io/<your-username>/$IMAGE_TAG"
echo "  docker push ghcr.io/<your-username>/$IMAGE_TAG"
echo
echo "Security note: this image likely contains secrets/configs. Keep it PRIVATE."
