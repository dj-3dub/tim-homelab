# Homelab (Pi-hole · Caddy · Homepage)

Reusable Docker stack + backup/restore tooling.

## What’s inside
- **compose/** – Docker Compose for Homepage and Pi-hole + Caddy
- **configs/** – redacted example configs (copy & edit for your env)
- **scripts/** – automation:
  - `homelab-backup.sh` / `homelab-restore.sh` – snapshot named volumes, bind mounts, images list
  - `make-backup-image.sh` – bake a single Docker image that contains your backup bundle
  - `inspect_backup_image.py` – verify exactly what the backup captured
  - `auto_patch_backup.py` – ensure Pi-hole binds `/etc/pihole` and `/etc/dnsmasq.d` are included
  - `add_adlists.py` – programmatically add OISD Big + extras to Pi-hole (Docker-safe)

## Quickstart (demo)
```bash
# use .env.example as a template
docker compose -f compose/homepage/docker-compose.yml --env-file .env.example up -d
docker compose -f compose/pihole-caddy/docker-compose.yml --env-file .env.example up -d
```

## Screenshot
![Screenshot](docs/screenshot.png)
