#!/usr/bin/env python3
import argparse, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

def run(cmd, **kw):
    return subprocess.run(cmd, check=True, text=True, capture_output=True, **kw)

def list_backup_images(prefix="homelab-backup:"):
    try:
        out = run(["docker","images","--format","{{.Repository}}:{{.Tag}}"]).stdout.splitlines()
        return sorted([i for i in out if i.startswith(prefix)])
    except subprocess.CalledProcessError:
        return []

def autodetect_image():
    imgs = list_backup_images()
    if not imgs:
        return None
    # Tags like YYYY-MM-DD_HHMMSS sort lexicographically; the last is newest
    return imgs[-1]

def create_container(image):
    return run(["docker","create",image]).stdout.strip()

def rm_container(cid):
    subprocess.run(["docker","rm","-f",cid], check=False)

def docker_cp(cid, src, dst):
    run(["docker","cp", f"{cid}:{src}", dst])

def read_lines(p: Path):
    try:
        return p.read_text().splitlines()
    except Exception:
        return []

def list_tars(d: Path):
    return sorted([p.name for p in d.glob("*.tar.gz")]) if d.exists() else []

def pretty(b): 
    return "✅ yes" if b else "❌ no"

def main():
    ap = argparse.ArgumentParser(description="Inspect a homelab backup Docker image.")
    g = ap.add_mutually_exclusive_group(required=False)
    g.add_argument("--image", help="Exact image tag, e.g. homelab-backup:2025-08-12_201735")
    g.add_argument("--auto", action="store_true", help="Auto-pick latest homelab-backup:* image")
    ap.add_argument("--expect", nargs="*", default=["pihole","caddy","homepage"], help="Highlight these containers")
    args = ap.parse_args()

    image = args.image
    if args.auto or not image:
        auto = autodetect_image()
        if args.auto:
            image = auto
        elif not image and auto:
            image = auto

    if not image:
        sys.stderr.write(
            "ERROR: No backup image found.\n"
            "Hints:\n"
            "  - Build one:  ~/make-backup-image.sh\n"
            "  - Or list:    docker images | grep homelab-backup\n"
            "  - Or load:    docker load -i /path/to/homelab-backup-image.tar\n"
        )
        sys.exit(2)

    tmp = Path(tempfile.mkdtemp(prefix="bundle-inspect-"))
    bundle = tmp / "bundle"
    cid = None
    try:
        print(f"Using image: {image}")
        cid = create_container(image)
        docker_cp(cid, "/bundle", str(tmp))

        if not bundle.exists():
            sys.stderr.write("ERROR: /bundle not found inside the image. Is this the right image?\n")
            sys.exit(3)

        backup = bundle / "backup"
        vols = backup / "volumes"
        binds = backup / "bind-mounts"
        comps = backup / "compose-files"
        man   = backup / "manifests"
        certs = backup / "certs"
        images_tar = backup / "images.tar"

        containers_json = man / "containers.json"
        running_images = read_lines(man / "running-images.txt")
        containers_tsv = read_lines(man / "containers.tsv")
        try:
            containers = json.loads(containers_json.read_text()) if containers_json.exists() else []
        except Exception as e:
            sys.stderr.write(f"WARNING: could not parse {containers_json.name}: {e}\n")
            containers = []

        vol_arch = set(list_tars(vols))
        bind_arch = set(list_tars(binds))
        comp_files = sorted([p.name for p in comps.glob("*")]) if comps.exists() else []
        cert_present = (certs / "caddy-rootCA.crt").exists()
        images_tar_present = images_tar.exists()

        print("\n== Top-level presence ==")
        print(f"  volumes/:       {pretty(vols.exists())}  ({len(vol_arch)} archives)")
        print(f"  bind-mounts/:   {pretty(binds.exists())}  ({len(bind_arch)} archives)")
        print(f"  compose-files/: {pretty(comps.exists())}  ({len(comp_files)} files)")
        print(f"  manifests/:     {pretty(man.exists())}")
        print(f"  images.tar:     {pretty(images_tar_present)}")
        print(f"  certs/:         {pretty(certs.exists())}   caddy-rootCA.crt: {pretty(cert_present)}")

        if comp_files:
            print("\ncompose-files/ (first 10):")
            for n in comp_files[:10]:
                print("  -", n)

        if running_images:
            print("\nrunning-images.txt:")
            for n in running_images:
                print("  -", n)

        if containers_tsv:
            print("\ncontainers.tsv:")
            for n in containers_tsv:
                print("  -", n)

        def bind_name(src: str) -> str:
            return src.lstrip("/").replace("/", "__") + ".tar.gz"

        if containers:
            wanted = []
            for c in containers:
                name = (c.get("Name") or "").lstrip("/")
                if name:
                    wanted.append(name)
            ordered = [n for n in args.expect if n in wanted] + [n for n in sorted(wanted) if n not in args.expect]

            print("\n== Per-container capture check ==")
            info = {}
            for c in containers:
                name = (c.get("Name") or "").lstrip("/")
                if not name:
                    continue
                image_name = c.get("Config",{}).get("Image") or c.get("Image","")
                mounts = c.get("Mounts") or []
                vols_m = [m for m in mounts if m.get("Type")=="volume"]
                binds_m= [m for m in mounts if m.get("Type")=="bind"]
                info[name]=(image_name,vols_m,binds_m)

            for name in ordered:
                if name not in info:
                    continue
                image_name, vols_m, binds_m = info[name]
                print(f"\n[{name}]  image: {image_name}")
                if vols_m:
                    print("  Volumes:")
                    for m in vols_m:
                        vname = m.get("Name") or ""
                        dest  = m.get("Destination") or m.get("Target") or ""
                        expected = f"{vname}.tar.gz" if vname else ""
                        present = expected in vol_arch if expected else False
                        exp_note = f"   (expected: volumes/{expected})" if expected and not present else ""
                        print(f"    - {vname:25s} -> {dest:25s}  archived: {pretty(present)}{exp_note}")
                else:
                    print("  Volumes: (none)")

                if binds_m:
                    print("  Bind mounts:")
                    for m in binds_m:
                        src = m.get("Source") or ""
                        dest = m.get("Destination") or m.get("Target") or ""
                        expected = bind_name(src) if src else ""
                        present = expected in bind_arch if expected else False
                        exp_note = f"   (expected: bind-mounts/{expected})" if expected and not present else ""
                        print(f"    - {src:45s} -> {dest:25s}  archived: {pretty(present)}{exp_note}")
                else:
                    print("  Bind mounts: (none)")
        else:
            sys.stderr.write("\nNOTE: containers.json missing; deep cross-check skipped.\n")

        print("\n== Done ==")

    except subprocess.CalledProcessError as e:
        cmd_str = " ".join(e.args[0]) if isinstance(e.args, (list, tuple)) else str(e)
        if "docker create" in cmd_str or "create" in cmd_str:
            imgs = list_backup_images()
            sys.stderr.write(f"ERROR: Could not create container from image '{image}'.\n")
            if imgs:
                sys.stderr.write("Available homelab-backup images:\n")
                for i in imgs:
                    sys.stderr.write(f"  - {i}\n")
                sys.stderr.write("\nTry:  ./inspect_backup_image.py --image <one-of-the-above>\n")
            else:
                sys.stderr.write(
                    "No homelab-backup images are present locally.\n"
                    "Hints:\n"
                    "  - Build one:  ~/make-backup-image.sh\n"
                    "  - Or load:    docker load -i /path/to/homelab-backup-image.tar\n"
                    "  - Or run with --auto after one exists.\n"
                )
            sys.exit(1)
        else:
            sys.stderr.write(f"ERROR: Command failed: {e}\n")
            sys.exit(1)
    finally:
        try:
            if 'cid' in locals() and cid:
                rm_container(cid)
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)

if __name__ == "__main__":
    main()
