#!/usr/bin/env python3
"""
auto_patch_backup.py

Ensure your latest homelab backup has all critical bind-mounts archived,
especially Pi-hole's /etc/pihole and /etc/dnsmasq.d. Optionally rebuild
your "backup image" afterward.

Usage examples:
  python3 auto_patch_backup.py
  python3 auto_patch_backup.py --backup /home/tim/homelab-backups/2025-08-12_224310
  python3 auto_patch_backup.py --extra-prefix /opt --extra-prefix /srv --rebuild-image
  python3 auto_patch_backup.py --dry-run

Notes:
- Requires Docker CLI on the host.
- Uses sudo for archiving root-owned paths (you’ll be prompted once).
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

DEFAULT_EXPECT = ["pihole", "caddy", "homepage"]

# Default prefixes we’re willing to archive if bind-mounted by a container.
DEFAULT_PREFIXES = [
    # your home
    str(Path.home()),
    # Pi-hole & Caddy system dirs (root-owned)
    "/etc/pihole",
    "/etc/dnsmasq.d",
    "/etc/caddy",
    "/etc/caddy_config",
]

def run(cmd: List[str], check=True, capture_output=True, text=True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, capture_output=capture_output, text=text)

def sudo_ok() -> bool:
    try:
        # Pre-authenticate so later tar commands don't prompt mid-loop
        subprocess.run(["sudo", "-v"], check=True)
        return True
    except subprocess.CalledProcessError:
        return False

def read_latest_backup() -> Optional[Path]:
    latest_ptr = Path.home() / "homelab-backups" / "LATEST"
    if latest_ptr.exists():
        p = latest_ptr.read_text().strip()
        if p:
            bp = Path(p)
            if bp.exists():
                return bp
    # fallback: pick most recent timestamp dir under ~/homelab-backups
    root = Path.home() / "homelab-backups"
    if root.exists():
        candidates = sorted([d for d in root.iterdir() if d.is_dir()], key=lambda d: d.name)
        return candidates[-1] if candidates else None
    return None

def list_archives(dirpath: Path) -> Set[str]:
    if not dirpath.exists():
        return set()
    return {p.name for p in dirpath.glob("*.tar.gz")}

def safe_archive_name_from_src(src: str) -> str:
    # /a/b/c  ->  a__b__c.tar.gz
    return src.lstrip("/").replace("/", "__") + ".tar.gz"

def docker_inspect(container: str) -> Optional[dict]:
    try:
        out = run(["docker", "inspect", container]).stdout
        data = json.loads(out)
        return data[0] if data else None
    except subprocess.CalledProcessError:
        return None

def gather_container_mounts(containers: Iterable[str]) -> Dict[str, Tuple[str, List[dict], List[dict]]]:
    """
    Returns {name: (image, volume_mounts, bind_mounts)}
    where each mount dict is a standard docker inspect Mounts item.
    """
    info: Dict[str, Tuple[str, List[dict], List[dict]]] = {}
    for name in containers:
        data = docker_inspect(name)
        if not data:
            continue
        image = data.get("Config", {}).get("Image") or data.get("Image", "")
        mounts = data.get("Mounts") or []
        vols = [m for m in mounts if m.get("Type") == "volume"]
        binds = [m for m in mounts if m.get("Type") == "bind"]
        info[name] = (image, vols, binds)
    return info

def should_include_path(src: str, prefixes: List[str]) -> bool:
    # include only if src is inside one of the allowed prefixes
    for p in prefixes:
        # Normalize to avoid trailing slash mismatches
        p_norm = str(Path(p))
        try:
            src_norm = str(Path(src))
        except Exception:
            src_norm = src
        if src_norm == p_norm or src_norm.startswith(p_norm + os.sep):
            return True
    return False

def ensure_bind_archives(
    bind_mounts: List[Tuple[str, str, str]],
    bind_dir: Path,
    dry_run: bool,
) -> List[str]:
    """
    For each (container, src, dst), ensure an archive exists in bind_dir.
    Return a list of created archive filenames.
    """
    created: List[str] = []
    bind_dir.mkdir(parents=True, exist_ok=True)
    existing = list_archives(bind_dir)

    for cname, src, dst in bind_mounts:
        arc = safe_archive_name_from_src(src)
        if arc in existing:
            continue
        # make it
        archive_path = bind_dir / arc
        if dry_run:
            print(f"[dry-run] Would archive: {src} -> {archive_path}")
            created.append(arc)
            continue

        # Use sudo tar to handle root-owned paths
        rel = src.lstrip("/")
        try:
            print(f"Archiving {src} (from {cname}) -> {archive_path}")
            subprocess.run(
                ["sudo", "tar", "czf", str(archive_path), "-C", "/", rel],
                check=True,
            )
            # fix ownership so the user can read it
            subprocess.run(["sudo", "chown", f"{os.getuid()}:{os.getgid()}", str(archive_path)], check=True)
            created.append(arc)
        except subprocess.CalledProcessError as e:
            print(f"ERROR: tar failed for {src}: {e}", file=sys.stderr)
    return created

def rebuild_backup_image(make_script: Path) -> None:
    print("\n== Rebuilding backup Docker image ==")
    try:
        subprocess.run([str(make_script)], check=True)
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Rebuild failed: {e}", file=sys.stderr)

def main():
    ap = argparse.ArgumentParser(description="Patch a homelab backup with missing bind-mount archives (e.g., Pi-hole config).")
    ap.add_argument("--backup", help="Path to an existing backup directory (default: latest from ~/homelab-backups/LATEST)")
    ap.add_argument("--containers", nargs="*", default=DEFAULT_EXPECT, help="Containers to inspect (default: pihole caddy homepage)")
    ap.add_argument("--extra-prefix", action="append", default=[], help="Extra host path prefixes to allow for archiving (can repeat)")
    ap.add_argument("--dry-run", action="store_true", help="Show what would be done without changing anything")
    ap.add_argument("--rebuild-image", action="store_true", help="After patching, run ~/make-backup-image.sh to rebuild the backup image")
    args = ap.parse_args()

    backup_root = Path(args.backup) if args.backup else read_latest_backup()
    if not backup_root or not backup_root.exists():
        print("ERROR: Could not resolve a backup directory. "
              "Run your backup first (~/homelab-backup.sh) or pass --backup /path/to/backup.",
              file=sys.stderr)
        sys.exit(2)

    backup_vols  = backup_root / "volumes"
    backup_binds = backup_root / "bind-mounts"
    backup_comps = backup_root / "compose-files"
    backup_man   = backup_root / "manifests"

    print(f"Using backup: {backup_root}")

    # Pre-auth sudo if we'll need it (unless dry-run)
    if not args.dry_run:
        if not sudo_ok():
            print("ERROR: sudo is required to archive root-owned paths (e.g., /etc/pihole).", file=sys.stderr)
            sys.exit(1)

    # Compose allowed prefixes
    allowed = list(DEFAULT_PREFIXES) + list(args.extra_prefix or [])
    # Deduplicate while preserving order
    seen: Set[str] = set()
    allowed = [p for p in allowed if not (p in seen or seen.add(p))]

    # Gather mounts
    info = gather_container_mounts(args.containers)
    if not info:
        print("WARNING: No containers found from the provided list.", file=sys.stderr)

    # Build a list of candidate bind mounts to ensure in the backup
    candidates: List[Tuple[str, str, str]] = []  # (container, src, dst)

    # Always include Pi-hole key paths (even if not mounted through Docker)
    for must in ("/etc/pihole", "/etc/dnsmasq.d"):
        if should_include_path(must, allowed) and Path(must).exists():
            candidates.append(("pihole", must, must))

    # Include binds reported by docker inspect
    for cname, (_img, _vols, binds) in info.items():
        for m in binds:
            src = m.get("Source") or ""
            dst = m.get("Destination") or m.get("Target") or ""
            if not src or not dst:
                continue
            if Path(src).exists() and should_include_path(src, allowed):
                candidates.append((cname, src, dst))

    # De-duplicate by source path (keep first occurrence)
    seen_src: Set[str] = set()
    filtered: List[Tuple[str, str, str]] = []
    for tup in candidates:
        _, src, _ = tup
        if src in seen_src:
            continue
        seen_src.add(src)
        filtered.append(tup)

    # Report BEFORE
    existing = list_archives(backup_binds)
    print("\n== BEFORE ==")
    print(f"bind-mount archives present: {len(existing)}")
    for n in sorted(existing):
        print(f"  - {n}")

    # Which ones are missing?
    missing = []
    for cname, src, dst in filtered:
        arc = safe_archive_name_from_src(src)
        if arc not in existing:
            missing.append((cname, src, dst, arc))

    if not missing:
        print("\nNothing missing; backup already contains all targeted bind mounts.")
    else:
        print("\nMissing archives that will be created:")
        for cname, src, dst, arc in missing:
            print(f"  - {src}  (container: {cname})  -> bind-mounts/{arc}")

    # Create missing archives
    created = ensure_bind_archives([(c,s,d) for c,s,d,_ in missing], backup_binds, args.dry_run)

    # Report AFTER
    final = list_archives(backup_binds)
    print("\n== AFTER ==")
    print(f"bind-mount archives present: {len(final)}")
    for n in sorted(final):
        mark = " (new)" if n in created else ""
        print(f"  - {n}{mark}")

    # Rebuild image if requested
    if args.rebuild_image:
        make_script = Path.home() / "make-backup-image.sh"
        if not make_script.exists():
            print(f"\nNOTE: {make_script} not found; skipping rebuild. "
                  "Build your backup image manually or create the script.", file=sys.stderr)
        else:
            rebuild_backup_image(make_script)

    print("\nDone.")

if __name__ == "__main__":
    main()
