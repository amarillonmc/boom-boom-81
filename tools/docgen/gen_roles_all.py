#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Generate a single MkDocs-friendly roles list page:

  - kb/roles/all.md

Input:
  - kb/index/topics.csv (expects at least: topic_id, category, title, author, created_at, file_path)

Run (from repo root):
  python tools/docgen/gen_roles_all.py
"""

from __future__ import annotations

import argparse
import csv
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List


@dataclass(frozen=True)
class TopicRow:
    topic_id: int
    title: str
    author: str
    created_at: str
    file_path: str  # may be "kb/roles/xx.md" or "roles/xx.md"


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


def rel_link(from_dir: Path, to_file: Path) -> str:
    rel = os.path.relpath(to_file, from_dir)
    return rel.replace("\\", "/")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", type=str, default="", help="Repo root (where kb/ exists).")
    args = ap.parse_args()

    if args.repo_root:
        repo_root = Path(args.repo_root).expanduser().resolve()
    else:
        # script: tools/docgen/gen_roles_all.py -> repo root is 2 levels up
        repo_root = Path(__file__).resolve().parents[2]
        if not (repo_root / "kb").exists():
            repo_root = Path.cwd().resolve()

    kb = repo_root / "kb"
    csv_path = kb / "index" / "topics.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"Cannot find topics.csv at: {csv_path}")

    rows = read_topics_csv(csv_path)
    roles = build_role_rows(rows)
    roles_sorted = sorted(roles, key=lambda x: x.topic_id, reverse=True)

    out_path = kb / "roles" / "all.md"
    lines: List[str] = []
    lines.append("# 全量角色卡列表")
    lines.append("")
    lines.append(f"- 总数：**{len(roles_sorted)}**")
    lines.append("")
    lines.append("## 列表（按 topic_id 由新到旧）")
    lines.append("")

    for it in roles_sorted:
        rel = normalize_rel_path(it.file_path)  # roles/xxx.md
        target = kb / rel
        link = rel_link(out_path.parent, target)

        meta = []
        if it.author:
            meta.append(f"作者：{it.author}")
        if it.topic_id:
            meta.append(f"topic_id：{it.topic_id}")
        if it.created_at:
            meta.append(f"created_at：{it.created_at}")

        meta_s = f"（{'；'.join(meta)}）" if meta else ""
        lines.append(f"- [{it.title}]({link}) {meta_s}".rstrip())

    lines.append("")
    lines.append("---")
    lines.append(f"_Generated at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}_")
    lines.append("")

    write_text(out_path, "\n".join(lines))
    print(f"[OK] Generated: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())