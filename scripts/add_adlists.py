#!/usr/bin/env python3
import argparse
import os
import shlex
import sqlite3
import subprocess
import sys
import tempfile
from typing import List, Tuple

# === Your chosen lists (no malware/crypto) ===
ADLISTS: List[Tuple[str, str]] = [
    ("https://big.oisd.nl/", "OISD Big"),
    ("https://v.firebog.net/hosts/Easyprivacy.txt", "EasyPrivacy (Firebog)"),
    ("https://v.firebog.net/hosts/AdguardDNS.txt", "AdGuard DNS (Firebog)"),
]

DB_PATH_IN_CONTAINER = "/etc/pihole/gravity.db"
DEFAULT_GROUP_ID = 0

def run(cmd, check=True, capture_output=False, text=True):
    return subprocess.run(cmd, check=check, capture_output=capture_output, text=text)

def detect_container_name() -> str:
    try:
        out = run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True).stdout.strip().splitlines()
        if "pihole" in out:
            return "pihole"
        for n in out:
            if "pihole" in n.lower():
                return n
    except Exception:
        pass
    raise SystemExit("Couldn't detect a Pi-hole container automatically. Pass --container <name>.")

def container_has_sqlite3(container: str) -> bool:
    # returns True if sqlite3 exists in container
    res = subprocess.run(
        ["docker", "exec", container, "bash", "-lc", "command -v sqlite3 >/dev/null 2>&1"],
        check=False,
    )
    return res.returncode == 0

def exec_sql_in_container(container: str, sql: str):
    cmd = [
        "docker", "exec", "-i", container, "bash", "-lc",
        f"sqlite3 {shlex.quote(DB_PATH_IN_CONTAINER)} <<'SQL'\n{sql}\nSQL"
    ]
    run(cmd)

def ensure_default_group_sql() -> str:
    return f"""
INSERT OR IGNORE INTO "group"(id, enabled, name, description)
VALUES ({DEFAULT_GROUP_ID}, 1, 'Default', 'Auto-created');
UPDATE "group" SET enabled=1 WHERE id={DEFAULT_GROUP_ID};
"""

def upsert_adlist_sql(url: str, comment: str) -> str:
    u = url.replace("'", "''")
    c = comment.replace("'", "''")
    return f"""
INSERT OR IGNORE INTO adlist(address, enabled, date_added, date_modified, comment)
VALUES ('{u}', 1, strftime('%s','now'), strftime('%s','now'), '{c}');
UPDATE adlist
   SET enabled=1,
       date_modified=strftime('%s','now'),
       comment='{c}'
 WHERE address='{u}';
INSERT OR IGNORE INTO adlist_by_group(adlist_id, group_id)
SELECT id, {DEFAULT_GROUP_ID} FROM adlist WHERE address='{u}';
"""

def edit_db_on_host(db_path: str):
    if not os.path.exists(db_path):
        raise SystemExit(f"DB file not found at {db_path}")

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        # sanity check tables
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        have = {r[0] for r in cur.fetchall()}
        need = {"adlist", "adlist_by_group", "group"}
        miss = need - have
        if miss:
            raise SystemExit(f"Unexpected DB schema; missing tables: {', '.join(sorted(miss))}")

        # ensure default group
        cur.execute('INSERT OR IGNORE INTO "group"(id, enabled, name, description) VALUES (?, 1, ?, ?)',
                    (DEFAULT_GROUP_ID, "Default", "Auto-created"))
        cur.execute('UPDATE "group" SET enabled=1 WHERE id=?', (DEFAULT_GROUP_ID,))

        # upsert each adlist
        for url, desc in ADLISTS:
            cur.execute("""
                INSERT OR IGNORE INTO adlist(address, enabled, date_added, date_modified, comment)
                VALUES (?, 1, strftime('%s','now'), strftime('%s','now'), ?)
            """, (url, desc))
            cur.execute("""
                UPDATE adlist SET enabled=1, date_modified=strftime('%s','now'), comment=?
                WHERE address=?
            """, (desc, url))
            # link to default group
            cur.execute("""
                INSERT OR IGNORE INTO adlist_by_group(adlist_id, group_id)
                SELECT id, ? FROM adlist WHERE address=?
            """, (DEFAULT_GROUP_ID, url))

        conn.commit()
    finally:
        conn.close()

def gravity_update(container: str):
    run(["docker", "exec", "-i", container, "pihole", "-g"])

def list_current_adlists(container: str):
    if container_has_sqlite3(container):
        out = run(
            ["docker", "exec", "-i", container, "bash", "-lc",
             f"sqlite3 -header -column {shlex.quote(DB_PATH_IN_CONTAINER)} \"SELECT id, enabled, address, comment FROM adlist ORDER BY id;\""],
            capture_output=True
        ).stdout
        print(out)
    else:
        with tempfile.TemporaryDirectory() as td:
            local_db = os.path.join(td, "gravity.db")
            run(["docker", "cp", f"{container}:{DB_PATH_IN_CONTAINER}", local_db])
            conn = sqlite3.connect(local_db)
            try:
                cur = conn.cursor()
                cur.execute("SELECT id, enabled, address, comment FROM adlist ORDER BY id")
                rows = cur.fetchall()
                print("id | enabled | address | comment")
                for r in rows:
                    print(f"{r[0]} | {r[1]} | {r[2]} | {r[3]}")
            finally:
                conn.close()

def main():
    ap = argparse.ArgumentParser(description="Add/enable Pi-hole adlists from the Docker host.")
    ap.add_argument("--container", help="Pi-hole container name (default: auto-detect)")
    ap.add_argument("--dry-run", action="store_true", help="Show intended changes without applying")
    ap.add_argument("--list", action="store_true", help="List current adlists and exit")
    args = ap.parse_args()

    container = args.container or detect_container_name()

    if args.list:
        list_current_adlists(container)
        sys.exit(0)

    print(f"Target container: {container}")
    print("Ensuring/adding adlists...")

    if container_has_sqlite3(container):
        # Fast path: run SQL inside the container
        sql = ensure_default_group_sql()
        for url, desc in ADLISTS:
            sql += "\n" + upsert_adlist_sql(url, desc)
        if args.dry_run:
            print("--dry-run: would run SQL inside container:\n", sql)
        else:
            exec_sql_in_container(container, sql)
    else:
        # Fallback: copy DB out, edit with Python, copy back
        with tempfile.TemporaryDirectory() as td:
            local_db = os.path.join(td, "gravity.db")
            run(["docker", "cp", f"{container}:{DB_PATH_IN_CONTAINER}", local_db])
            if args.dry_run:
                print(f"--dry-run: would edit DB at {local_db} and copy back to {DB_PATH_IN_CONTAINER}")
            else:
                edit_db_on_host(local_db)
                run(["docker", "cp", local_db, f"{container}:{DB_PATH_IN_CONTAINER}"])

    if args.dry_run:
        print("\n--dry-run specified: skipping gravity update. Use --list to inspect current state.")
        sys.exit(0)

    print("\nRebuilding gravity (pihole -g). This may take a minute...")
    gravity_update(container)
    print("Done.\nCurrent adlists:")
    list_current_adlists(container)

if __name__ == "__main__":
    main()
