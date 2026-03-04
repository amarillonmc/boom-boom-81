#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Generate MkDocs-friendly "roles by author" pages from kb/index/topics.csv.

Creates/overwrites:
  - kb/roles/by-author/index.md
  - kb/roles/by-author/<author>.md

Assumptions (based on kb/index README):
  - topics.csv contains at least: topic_id, category, title, author, file_path
  - category values include: roles | rulebooks | records

Run:
  - From repo root:
      python tools/docgen/gen_roles_by_author.py
  - Or specify repo root:
      python tools/docgen/gen_roles_by_author.py --repo-root "C:\\sites\\boom-boom-81\\repo"
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone


@dataclass(frozen=True)
class TopicRow:
    topic_id: int
    title: str
    author: str
    created_at: str
    file_path: str  # usually like "kb/roles/xxxx.md" or "roles/xxxx.md"


INVALID_WIN_FILENAME_CHARS = r'<>:"/\\|?*\x00-\x1F'
_invalid_re = re.compile(f"[{re.escape(INVALID_WIN_FILENAME_CHARS)}]")


def safe_filename(name: str) -> str:
    """
    Make a filesystem-safe filename for Windows/Linux.
    Keeps Unicode (so '小兵.md' is OK) but strips Windows-forbidden chars.
    """
    s = name.strip()
    s = _invalid_re.sub("_", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.strip(". ")  # Windows dislikes trailing dot/space
    if not s:
        s = "unknown"
    # guard against ridiculous length
    if len(s) > 120:
        s = s[:120].rstrip()
    return s


def normalize_rel_path(file_path: str) -> str:
    """
    Normalize index file_path into a path relative to docs root (kb/).
    e.g. "kb/roles/123.md" -> "roles/123.md"
         "roles/123.md"    -> "roles/123.md"
    """
    p = file_path.strip().lstrip("/").replace("\\", "/")
    if p.startswith("kb/"):
        p = p[3:]
    return p


def read_topics_csv(csv_path: Path) -> List[dict]:
    # utf-8-sig tolerates BOM if someone opened/saved in Excel
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = []
        for r in reader:
            rows.append(r)
        return rows


def pick_field(row: dict, *candidates: str, default: str = "") -> str:
    for k in candidates:
        if k in row and row[k] is not None:
            return str(row[k]).strip()
    return default


def build_rows(rows: List[dict]) -> List[TopicRow]:
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
            # If index is incomplete, skip rather than generating broken links.
            continue

        out.append(
            TopicRow(
                topic_id=topic_id,
                title=title,
                author=author,
                created_at=created_at,
                file_path=file_path,
            )
        )
    return out


def ensure_unique_filenames(authors: List[str]) -> Dict[str, str]:
    """
    Map author name -> unique markdown filename.
    If collisions occur after sanitization, append a short hash.
    """
    used: Dict[str, str] = {}
    result: Dict[str, str] = {}

    for a in authors:
        base = safe_filename(a)
        fn = f"{base}.md"

        if fn in used and used[fn] != a:
            h = hashlib.md5(a.encode("utf-8")).hexdigest()[:6]
            fn = f"{base}-{h}.md"

        used[fn] = a
        result[a] = fn

    return result


def rel_link(from_dir: Path, to_file: Path) -> str:
    """
    Build a relative link with forward slashes for Markdown/MkDocs.
    """
    rel = os.path.relpath(to_file, from_dir)
    return rel.replace("\\", "/")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def generate_author_page(
    author: str,
    items: List[TopicRow],
    out_path: Path,
    docs_root: Path,
) -> None:
    """
    items: TopicRow list for this author
    out_path: .../kb/roles/by-author/<author>.md
    docs_root: .../kb
    """
    # Sort: newest topic_id first (topic_id increases over time; good enough)
    items_sorted = sorted(items, key=lambda x: x.topic_id, reverse=True)

    lines: List[str] = []
    lines.append(f"# {author}")
    lines.append("")
    lines.append(f"- 角色卡数量：**{len(items_sorted)}**")
    lines.append("")
    lines.append("## 列表（按 topic_id 由新到旧）")
    lines.append("")

    for it in items_sorted:
        rel = normalize_rel_path(it.file_path)  # e.g. roles/xxx.md
        target = docs_root / rel
        link = rel_link(out_path.parent, target)

        meta = []
        if it.topic_id:
            meta.append(f"topic_id: {it.topic_id}")
        if it.created_at:
            meta.append(f"created_at: {it.created_at}")

        meta_s = f"（{'；'.join(meta)}）" if meta else ""
        # Keep title readable; don't escape aggressively
        lines.append(f"- [{it.title}]({link}) {meta_s}".rstrip())

    lines.append("")
    lines.append("---")
    lines.append(f"_Generated at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}_")
    lines.append("")

    write_text(out_path, "\n".join(lines))


def generate_index_page(
    author_to_filename: Dict[str, str],
    author_counts: Dict[str, int],
    out_path: Path,
) -> None:
    authors_sorted = sorted(
        author_to_filename.keys(),
        key=lambda a: (-author_counts.get(a, 0), a),
    )

    lines: List[str] = []
    lines.append("# 角色卡作者索引")
    lines.append("")
    lines.append("按作者列出全部角色卡主题（`kb/index/topics.csv` 中 `category=roles`）。")
    lines.append("")
    lines.append("## 作者列表（按角色卡数量由多到少）")
    lines.append("")

    for a in authors_sorted:
        fn = author_to_filename[a]
        cnt = author_counts.get(a, 0)
        lines.append(f"- [{a}]({fn})（{cnt}）")

    lines.append("")
    lines.append("---")
    lines.append(f"_Generated at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}_")
    lines.append("")

    write_text(out_path, "\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-root",
        type=str,
        default="",
        help="Path to repo root (where kb/ exists). Default: auto-detect from script location / cwd.",
    )
    args = parser.parse_args()

    # Auto-detect repo root
    if args.repo_root:
        repo_root = Path(args.repo_root).expanduser().resolve()
    else:
        # Try: script path -> repo root
        here = Path(__file__).resolve()
        # tools/docgen/gen_roles_by_author.py -> repo root is 2 levels up
        guess = here.parents[2] if len(here.parents) >= 3 else Path.cwd().resolve()
        repo_root = guess

        # If guess doesn't contain kb/, fallback to cwd
        if not (repo_root / "kb").exists():
            repo_root = Path.cwd().resolve()

    docs_root = repo_root / "kb"
    csv_path = docs_root / "index" / "topics.csv"

    if not csv_path.exists():
        raise FileNotFoundError(f"Cannot find topics.csv at: {csv_path}")

    raw_rows = read_topics_csv(csv_path)
    role_rows = build_rows(raw_rows)

    # group by author
    by_author: Dict[str, List[TopicRow]] = {}
    for r in role_rows:
        by_author.setdefault(r.author, []).append(r)

    authors = sorted(by_author.keys())
    author_to_filename = ensure_unique_filenames(authors)
    author_counts = {a: len(by_author[a]) for a in authors}

    out_dir = docs_root / "roles" / "by-author"
    index_out = out_dir / "index.md"
    generate_index_page(author_to_filename, author_counts, index_out)

    for a in authors:
        fn = author_to_filename[a]
        out_path = out_dir / fn
        generate_author_page(a, by_author[a], out_path, docs_root)

    print(f"[OK] Generated {len(authors)} author pages under: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())