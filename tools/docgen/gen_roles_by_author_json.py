#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Generate per-author JSON lists for roles:

  - kb/roles/by-author/<author>.json
  - kb/roles/by-author/index.json   (author -> json file + count; helpful entrypoint)

Input:
  - kb/index/topics.csv

Run (from repo root):
  python tools/docgen/gen_roles_by_author_json.py
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


@dataclass(frozen=True)
class TopicRow:
    topic_id: int
    title: str
    author: str
    created_at: str
    file_path: str  # may be "kb/roles/xx.md" or "roles/xx.md"


INVALID_WIN_FILENAME_CHARS = r'<>:"/\\|?*\x00-\x1F'
_invalid_re = re.compile(f"[{re.escape(INVALID_WIN_FILENAME_CHARS)}]")


def safe_filename(name: str) -> str:
    s = name.strip()
    s = _invalid_re.sub("_", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.strip(". ")
    if not s:
        s = "unknown"
    if len(s) > 120:
        s = s[:120].rstrip()
    return s


def pick_field(row: dict, *candidates: str, default: str = "") -> str:
    for k in candidates:
        if k in row and row[k] is not None:
            return str(row[k]).strip()
    return default


def normalize_rel_path(file_path: str) -> str:
    p = file_path.strip().lstrip("/").replace("\\", "/")
    if p.startswith("kb/"):
        p = p[3:]
    return p


def read_topics_csv(csv_path: Path) -> List[dict]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def build_role_rows(rows: List[dict]) -> List[TopicRow]:
    out: List[TopicRow] = []
    for r in rows:
        category = pick_field(r, "category").lower()
        if category != "roles":
            continue

        topic_id_s = pick_field(r, "topic_id", default="0")
        try:
            topic_id = int(topic_id_s)
        except ValueError:
            topic_id = 0

        title = pick_field(r, "title", default=f"topic {topic_id}")
        author = pick_field(r, "author", default="unknown")
        created_at = pick_field(r, "created_at", default="")
        file_path = pick_field(r, "file_path", "path", default="")
        if not file_path:
            continue

        out.append(TopicRow(topic_id, title, author, created_at, file_path))
    return out


def ensure_unique_filenames(authors: List[str], suffix: str) -> Dict[str, str]:
    """
    Map author -> unique filename (with suffix like '.json').
    If sanitized name collides, append 6-char hash.
    """
    used: Dict[str, str] = {}
    out: Dict[str, str] = {}

    for a in authors:
        base = safe_filename(a)
        fn = f"{base}{suffix}"
        if fn in used and used[fn] != a:
            h = hashlib.md5(a.encode("utf-8")).hexdigest()[:6]
            fn = f"{base}-{h}{suffix}"
        used[fn] = a
        out[a] = fn

    return out


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", type=str, default="", help="Repo root (where kb/ exists).")
    args = ap.parse_args()

    if args.repo_root:
        repo_root = Path(args.repo_root).expanduser().resolve()
    else:
        repo_root = Path(__file__).resolve().parents[2]
        if not (repo_root / "kb").exists():
            repo_root = Path.cwd().resolve()

    kb = repo_root / "kb"
    csv_path = kb / "index" / "topics.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"Cannot find topics.csv at: {csv_path}")

    rows = read_topics_csv(csv_path)
    roles = build_role_rows(rows)

    by_author: Dict[str, List[TopicRow]] = {}
    for it in roles:
        by_author.setdefault(it.author, []).append(it)

    authors = sorted(by_author.keys())
    author_to_json_fn = ensure_unique_filenames(authors, ".json")

    out_dir = kb / "roles" / "by-author"
    index_entries = []

    for author in authors:
        items = sorted(by_author[author], key=lambda x: x.topic_id, reverse=True)
        fn = author_to_json_fn[author]
        out_path = out_dir / fn

        payload = {
            "author": author,
            "count": len(items),
            "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "items": [
                {
                    "topic_id": it.topic_id,
                    "title": it.title,
                    "created_at": it.created_at,
                    # relative to kb/; agent can turn it into /raw/<rel_path>
                    "rel_path": normalize_rel_path(it.file_path),
                }
                for it in items
            ],
        }

        write_json(out_path, payload)
        index_entries.append({"author": author, "count": len(items), "file": fn})

    index_payload = {
        "type": "roles_by_author_index",
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "total_authors": len(index_entries),
        "total_roles": len(roles),
        "authors": sorted(index_entries, key=lambda x: (-x["count"], x["author"])),
    }
    write_json(out_dir / "index.json", index_payload)

    print(f"[OK] Generated {len(authors)} author JSON files under: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())