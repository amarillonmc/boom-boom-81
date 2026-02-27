from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from html import unescape
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urljoin
from urllib.parse import urlparse
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError

import requests
from bs4 import BeautifulSoup
from bs4 import Tag
from bs4.element import NavigableString


try:
    FORUM_TZ = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:
    # Fallback for Python environments without IANA timezone data (common on Windows).
    # Forum time is fixed at UTC+8 for this use case.
    FORUM_TZ = timezone(timedelta(hours=8), name="CST")

ROLE_INDEX_TOPIC_ID = 1378
RULEBOOK_BOARD_ID = 15
RECORD_BOARD_ID = 14
RECORD_PREFIX = 3
DEFAULT_REPORT_TOPIC_ID = 35
DEFAULT_SAMPLE_SIZE = 7


@dataclass
class TopicRef:
    topic_id: int
    category: str
    source: str = ""


@dataclass
class PostBlock:
    title: str
    author: str
    posted_at: str
    body: str


@dataclass
class TopicResult:
    topic_id: int
    category: str
    title: str
    author: str
    created_at_raw: str
    created_at_iso: Optional[str]
    fetched_at_raw: str
    fetched_at_iso: str
    source_url: str
    file_path: str
    status: str
    approx_chars: int
    approx_tokens: int
    data_quality: str


@dataclass
class WarningEntry:
    run_id: str
    topic_id: int
    category: str
    file_path: str
    floor_index: Optional[int]
    warning_type: str
    message: str
    snippet: str
    created_at_iso: str


def compact_blank_lines(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_env_file(path: Path) -> Dict[str, str]:
    data: Dict[str, str] = {}
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def now_forum_time() -> str:
    return datetime.now(FORUM_TZ).strftime("%Y-%m-%d %H:%M:%S %z")


def now_forum_iso() -> str:
    return datetime.now(FORUM_TZ).isoformat()


def now_forum_compact() -> str:
    return datetime.now(FORUM_TZ).strftime("%Y%m%d%H:%M")


def parse_forum_time_to_iso(raw: str) -> Optional[str]:
    raw = raw.strip()
    if not raw:
        return None

    month_map = {
        "一月": 1,
        "二月": 2,
        "三月": 3,
        "四月": 4,
        "五月": 5,
        "六月": 6,
        "七月": 7,
        "八月": 8,
        "九月": 9,
        "十月": 10,
        "十一月": 11,
        "十二月": 12,
    }

    m = re.match(r"^(\S+)\s+(\d{1,2}),\s*(\d{4}),\s*(\d{1,2}):(\d{2})\s*(上午|下午)$", raw)
    if m:
        month_text, day, year, hour, minute, ampm = m.groups()
        month = month_map.get(month_text)
        if not month:
            return None
        hh = int(hour)
        if ampm == "上午":
            if hh == 12:
                hh = 0
        else:
            if hh != 12:
                hh += 12
        dt = datetime(int(year), month, int(day), hh, int(minute), tzinfo=FORUM_TZ)
        return dt.isoformat()

    m2 = re.match(r"^(今天|昨天)\s*(\d{1,2}):(\d{2})\s*(上午|下午)$", raw)
    if m2:
        day_word, hour, minute, ampm = m2.groups()
        base = datetime.now(FORUM_TZ)
        if day_word == "昨天":
            base = base - timedelta(days=1)
        hh = int(hour)
        if ampm == "上午":
            if hh == 12:
                hh = 0
        else:
            if hh != 12:
                hh += 12
        dt = datetime(base.year, base.month, base.day, hh, int(minute), tzinfo=FORUM_TZ)
        return dt.isoformat()

    return None


def normalize_url(href: str) -> str:
    href = href.strip()
    href = re.sub(r"([?&])PHPSESSID=[^&;#]+&?", r"\1", href)
    href = href.replace("?&", "?")
    href = href.rstrip("&")
    href = href.split("#", 1)[0]
    return href


def slugify_title(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title).strip("-").lower()
    if not slug:
        slug = "topic"
    return slug[:80]


def yaml_escape(value: str) -> str:
    return value.replace('"', '\\"')


class ForumClient:
    def __init__(self, base_url: str, delay_ms: int, user_agent: str):
        self.base_url = base_url.rstrip("/")
        self.delay_seconds = max(0, delay_ms) / 1000.0
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    def _sleep(self) -> None:
        if self.delay_seconds:
            time.sleep(self.delay_seconds)

    def get(self, url: str) -> requests.Response:
        self._sleep()
        resp = self.session.get(url, timeout=40)
        resp.raise_for_status()
        return resp

    def post(self, url: str, data: Dict[str, str]) -> requests.Response:
        self._sleep()
        resp = self.session.post(url, data=data, timeout=40, allow_redirects=True)
        resp.raise_for_status()
        return resp

    def login(self, username: str, password: str) -> None:
        login_url = f"{self.base_url}/index.php?action=login"
        page = self.get(login_url)
        soup = BeautifulSoup(page.text, "html.parser")

        form = soup.find("form")
        if not form:
            raise RuntimeError("Unable to find login form on SMF login page.")

        action = str(form.get("action") or "")
        action_url = urljoin(self.base_url + "/", action)
        if "action=login2" not in action_url:
            action_url = f"{self.base_url}/index.php?action=login2"

        payload: Dict[str, str] = {}
        for field in form.select("input[name]"):
            name = str(field.get("name", "")).strip()
            value = str(field.get("value", ""))
            payload[name] = value

        payload["user"] = username
        payload["passwrd"] = password
        payload.setdefault("cookielength", "-1")

        result = self.post(action_url, payload)
        ok_text = result.text
        if "action=logout" not in ok_text and username not in ok_text:
            raise RuntimeError("Login failed. Verify SMF credentials or required permissions.")

    def fetch_board_page(self, board_id: int, offset: int = 0, prefix: Optional[int] = None) -> str:
        base = f"{self.base_url}/index.php?board={board_id}.{offset}"
        if prefix is not None:
            base += f";prefix={prefix}"
        return self.get(base).text

    def fetch_topic_page(self, topic_id: int) -> str:
        url = f"{self.base_url}/index.php?topic={topic_id}.0"
        return self.get(url).text

    def fetch_printpage(self, topic_id: int) -> str:
        url = f"{self.base_url}/index.php?action=printpage;topic={topic_id}.0"
        return self.get(url).text

    def post_reply(self, topic_id: int, message: str, subject: Optional[str] = None) -> None:
        post_page_url = f"{self.base_url}/index.php?action=post;topic={topic_id}.0"
        page = self.get(post_page_url)
        soup = BeautifulSoup(page.text, "html.parser")

        form = soup.find("form")
        if not form:
            raise RuntimeError(f"Unable to find post form for topic {topic_id}.")

        action = str(form.get("action") or "")
        post_url = urljoin(self.base_url + "/", action)
        if not post_url:
            post_url = f"{self.base_url}/index.php?action=post2;start=0;board=0"

        payload: Dict[str, str] = {}
        for field in form.select("input[name]"):
            name = str(field.get("name", "")).strip()
            if not name:
                continue
            payload[name] = str(field.get("value", ""))

        textarea = form.find("textarea", attrs={"name": "message"})
        if textarea is None:
            raise RuntimeError("Post form message textarea not found.")

        payload["message"] = message
        payload["topic"] = str(topic_id)
        if subject is not None and subject.strip():
            payload["subject"] = subject.strip()
        elif "subject" not in payload:
            payload["subject"] = f"Re: Topic {topic_id}"

        if "post" not in payload:
            payload["post"] = "Post"

        resp = self.post(post_url, payload)
        if "action=post;topic=" in resp.url or "error" in resp.text.lower():
            raise RuntimeError(f"Posting reply to topic {topic_id} may have failed.")


def extract_topic_ids_from_html(html: str) -> Set[int]:
    soup = BeautifulSoup(html, "html.parser")
    topic_ids: Set[int] = set()
    for a in soup.find_all("a", href=True):
        href = normalize_url(str(a.get("href", "")))
        match = re.search(r"topic=(\d+)\.0(?:\b|$)", href)
        if match:
            topic_ids.add(int(match.group(1)))
    return topic_ids


def extract_board_offsets(html: str, board_id: int, prefix: Optional[int]) -> Set[int]:
    soup = BeautifulSoup(html, "html.parser")
    offsets: Set[int] = set()
    for a in soup.find_all("a", href=True):
        href = normalize_url(str(a.get("href", "")))
        if f"board={board_id}." not in href:
            continue

        if prefix is not None and f";prefix={prefix}" not in href:
            continue

        match = re.search(rf"board={board_id}\.(\d+)", href)
        if match:
            offsets.add(int(match.group(1)))
    return offsets


def collect_board_topics(client: ForumClient, board_id: int, prefix: Optional[int]) -> Set[int]:
    todo: List[int] = [0]
    visited: Set[int] = set()
    topics: Set[int] = set()

    while todo:
        offset = todo.pop(0)
        if offset in visited:
            continue
        visited.add(offset)

        html = client.fetch_board_page(board_id=board_id, offset=offset, prefix=prefix)
        topics |= extract_topic_ids_from_html(html)

        for next_offset in sorted(extract_board_offsets(html, board_id, prefix)):
            if next_offset not in visited and next_offset not in todo:
                todo.append(next_offset)

    return topics


def collect_role_topics(client: ForumClient) -> Set[int]:
    html = client.fetch_printpage(ROLE_INDEX_TOPIC_ID)
    topic_ids = extract_topic_ids_from_html(html)
    topic_ids.discard(ROLE_INDEX_TOPIC_ID)
    return topic_ids


def text_content(node: Tag | NavigableString | None) -> str:
    if node is None:
        return ""
    if isinstance(node, NavigableString):
        return unescape(str(node).replace("\xa0", " "))
    return unescape(node.get_text("", strip=False).replace("\xa0", " "))


def normalize_inline_text(text: str) -> str:
    text = text.replace("\t", " ")
    text = re.sub(r"[ \f\v]+", " ", text)
    return text


def render_children(node: Tag, list_depth: int = 0) -> str:
    chunks: List[str] = []
    for child in node.children:
        if not isinstance(child, (Tag, NavigableString)):
            continue
        chunks.append(render_node(child, list_depth=list_depth))
    return "".join(chunks)


def render_list(list_node: Tag, ordered: bool, list_depth: int) -> str:
    lines: List[str] = []
    index = 1
    for child in list_node.children:
        if not isinstance(child, Tag) or child.name != "li":
            continue
        item_text = compact_blank_lines(render_children(child, list_depth=list_depth + 1))
        if not item_text:
            continue
        indent = "  " * list_depth
        bullet = f"{index}. " if ordered else "- "
        item_lines = item_text.split("\n")
        lines.append(f"{indent}{bullet}{item_lines[0]}")
        for cont in item_lines[1:]:
            lines.append(f"{indent}  {cont}")
        index += 1
    if not lines:
        return ""
    return "\n".join(lines) + "\n\n"


def render_blockquote(node: Tag, list_depth: int) -> str:
    text = compact_blank_lines(render_children(node, list_depth=list_depth))
    if not text:
        return ""
    out_lines = []
    for line in text.split("\n"):
        if line.strip():
            out_lines.append(f"> {line}")
        else:
            out_lines.append(">")
    return "\n".join(out_lines) + "\n\n"


def render_code_block(node: Tag) -> str:
    text = node.get_text("\n", strip=False)
    text = text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    return f"```\n{text}\n```\n\n"


def render_node(node: Tag | NavigableString, list_depth: int = 0) -> str:
    if isinstance(node, NavigableString):
        return normalize_inline_text(text_content(node))

    name = (node.name or "").lower()

    if name in {"script", "style", "noscript", "iframe", "video", "audio", "source"}:
        return ""

    if name == "br":
        return "\n"

    if name in {"strong", "b"}:
        inner = compact_blank_lines(render_children(node, list_depth=list_depth))
        return f"**{inner}**" if inner else ""

    if name in {"em", "i"}:
        inner = compact_blank_lines(render_children(node, list_depth=list_depth))
        return f"*{inner}*" if inner else ""

    if name == "a":
        label = compact_blank_lines(render_children(node, list_depth=list_depth))
        href = str(node.get("href") or "").strip()
        if not label:
            label = href
        if href:
            return f"[{label}]({href})"
        return label

    if name in {"ul", "ol"}:
        return render_list(node, ordered=(name == "ol"), list_depth=list_depth)

    if name == "blockquote":
        return render_blockquote(node, list_depth=list_depth)

    if name in {"pre", "code"}:
        return render_code_block(node)

    if name == "hr":
        return "\n---\n\n"

    if name in {"img", "svg", "picture", "figure", "figcaption"}:
        return ""

    if name in {"p", "div", "section", "article", "table", "tr", "td", "th"}:
        inner = compact_blank_lines(render_children(node, list_depth=list_depth))
        if not inner:
            return ""
        return inner + "\n\n"

    return render_children(node, list_depth=list_depth)


def postbody_to_markdown(body: Tag) -> str:
    text = render_children(body)
    return compact_blank_lines(text)


def parse_post_header(header: Tag) -> Tuple[str, str, str]:
    raw = compact_blank_lines(header.get_text("\n", strip=True))

    title_match = re.search(r"标题:\s*(.+)", raw)
    title = title_match.group(1).strip() if title_match else "Untitled"

    author_match = re.search(r"作者:\s*(.+?)\s*于\s*(.+)$", raw)
    if author_match:
        author = author_match.group(1).strip()
        posted_at = author_match.group(2).strip()
    else:
        author = "unknown"
        posted_at = "unknown"

    return title, author, posted_at


def parse_topic_from_printpage(html: str) -> Tuple[str, List[PostBlock]]:
    soup = BeautifulSoup(html, "html.parser")
    page_title = soup.title.get_text(strip=True) if soup.title else "Untitled"
    topic_title = re.sub(r"^打印本页\s*-\s*", "", page_title).strip()

    posts: List[PostBlock] = []
    posts_container = soup.select_one("#posts")
    if posts_container:
        headers = posts_container.select("div.postheader")
        bodies = posts_container.select("div.postbody")
        pair_count = min(len(headers), len(bodies))
        for idx in range(pair_count):
            title, author, posted_at = parse_post_header(headers[idx])
            body_md = postbody_to_markdown(bodies[idx])
            posts.append(PostBlock(title=title, author=author, posted_at=posted_at, body=body_md))

    if not posts:
        fallback_body = compact_blank_lines(soup.get_text("\n", strip=True))
        posts = [
            PostBlock(
                title=topic_title or "Untitled",
                author="unknown",
                posted_at="unknown",
                body=fallback_body,
            )
        ]

    if not topic_title:
        topic_title = posts[0].title

    return topic_title, posts


def build_markdown(
    topic_id: int,
    title: str,
    category: str,
    source_url: str,
    posts: List[PostBlock],
) -> Tuple[str, Dict[str, object]]:
    first_post = posts[0]
    has_spoiler_warning = any("Sorry but you are not allowed to view spoiler contents." in p.body for p in posts)
    spoiler_export_ok = not has_spoiler_warning
    missing_sections: List[str] = []
    if has_spoiler_warning:
        missing_sections.append("spoiler_contents")

    created_at_raw = first_post.posted_at
    created_at_iso = parse_forum_time_to_iso(created_at_raw)
    fetched_at_raw = now_forum_time()
    fetched_at_iso = now_forum_iso()
    data_quality = "restricted" if has_spoiler_warning else "ok"

    lines: List[str] = []
    lines.append("---")
    lines.append(f'topic_id: {topic_id}')
    lines.append(f'title: "{yaml_escape(title)}"')
    lines.append(f'category: "{category}"')
    lines.append(f'source_url: "{source_url}"')
    lines.append(f'author: "{yaml_escape(first_post.author)}"')
    lines.append(f'created_at_raw: "{yaml_escape(created_at_raw)}"')
    lines.append(f'created_at_iso: "{created_at_iso or ""}"')
    lines.append(f'fetched_at_raw: "{fetched_at_raw}"')
    lines.append(f'fetched_at_iso: "{fetched_at_iso}"')
    lines.append(f"has_spoiler: {'true' if has_spoiler_warning else 'false'}")
    lines.append(f"spoiler_export_ok: {'true' if spoiler_export_ok else 'false'}")
    if missing_sections:
        lines.append("missing_sections:")
        for item in missing_sections:
            lines.append(f"  - {item}")
    else:
        lines.append("missing_sections: []")
    lines.append(f'data_quality: "{data_quality}"')
    lines.append("---")
    lines.append("")
    lines.append(f"# {title}")
    lines.append("")

    for idx, post in enumerate(posts, start=1):
        lines.append(f"## {idx}F")
        lines.append("")
        posted_iso = parse_forum_time_to_iso(post.posted_at) or ""
        lines.append(f"- floor_index: {idx}")
        lines.append(f"- Author: {post.author}")
        lines.append(f"- Posted at raw: {post.posted_at}")
        lines.append(f"- Posted at iso: {posted_iso}")
        lines.append("")
        lines.append(post.body)
        lines.append("")

    markdown = "\n".join(lines).strip() + "\n"
    approx_chars = len(markdown)
    approx_tokens = max(1, math.ceil(approx_chars / 2))
    meta: Dict[str, object] = {
        "has_spoiler_warning": has_spoiler_warning,
        "spoiler_export_ok": spoiler_export_ok,
        "missing_sections": missing_sections,
        "data_quality": data_quality,
        "created_at_raw": created_at_raw,
        "created_at_iso": created_at_iso,
        "fetched_at_raw": fetched_at_raw,
        "fetched_at_iso": fetched_at_iso,
        "approx_chars": approx_chars,
        "approx_tokens": approx_tokens,
    }
    return markdown, meta


def sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def load_state(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {"topics": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def category_output_dir(repo_root: Path, category: str) -> Path:
    mapping = {
        "roles": repo_root / "kb" / "roles",
        "rulebooks": repo_root / "kb" / "rulebooks",
        "records": repo_root / "kb" / "records-completed",
    }
    return mapping[category]


def ensure_dirs(repo_root: Path) -> None:
    for path in [
        repo_root / "kb" / "roles",
        repo_root / "kb" / "rulebooks",
        repo_root / "kb" / "records-completed",
        repo_root / "kb" / "index",
        repo_root / "tools" / "no81_sync" / "state",
    ]:
        path.mkdir(parents=True, exist_ok=True)


def write_indexes(repo_root: Path, rows: List[TopicResult]) -> None:
    index_dir = repo_root / "kb" / "index"
    index_dir.mkdir(parents=True, exist_ok=True)

    csv_path = index_dir / "topics.csv"
    fields = [
        "topic_id",
        "category",
        "title",
        "author",
        "created_at_raw",
        "created_at_iso",
        "fetched_at_raw",
        "fetched_at_iso",
        "source_url",
        "file_path",
        "approx_chars",
        "approx_tokens",
        "data_quality",
        "status",
    ]

    with csv_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)

    jsonl_path = index_dir / "topics.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as fp:
        for row in rows:
            fp.write(json.dumps(row.__dict__, ensure_ascii=False) + "\n")


def write_warnings(repo_root: Path, warnings: List[WarningEntry]) -> None:
    index_dir = repo_root / "kb" / "index"
    index_dir.mkdir(parents=True, exist_ok=True)

    txt_path = index_dir / "warnings.txt"
    with txt_path.open("w", encoding="utf-8") as fp:
        for w in warnings:
            fp.write(f"topic={w.topic_id} category={w.category} type={w.warning_type} message={w.message}\n")

    jsonl_path = index_dir / "warnings.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as fp:
        for w in warnings:
            fp.write(json.dumps(w.__dict__, ensure_ascii=False) + "\n")


def write_author_indexes(repo_root: Path, rows: List[TopicResult], sample_size: int) -> None:
    grouped: Dict[str, List[TopicResult]] = {}
    for row in rows:
        grouped.setdefault(row.author, []).append(row)

    authors_path = repo_root / "kb" / "index" / "authors.jsonl"
    samples_path = repo_root / "kb" / "index" / "authors_roles_sample.jsonl"

    with authors_path.open("w", encoding="utf-8") as afp, samples_path.open("w", encoding="utf-8") as sfp:
        for author, items in sorted(grouped.items(), key=lambda x: x[0]):
            by_cat = {"roles": [], "rulebooks": [], "records": []}
            total_tokens = 0
            latest_created = None
            latest_fetched = None
            for it in items:
                by_cat.setdefault(it.category, []).append(it.topic_id)
                total_tokens += it.approx_tokens
                if it.created_at_iso and (latest_created is None or it.created_at_iso > latest_created):
                    latest_created = it.created_at_iso
                if it.fetched_at_iso and (latest_fetched is None or it.fetched_at_iso > latest_fetched):
                    latest_fetched = it.fetched_at_iso

            payload = {
                "author": author,
                "roles_count": len(by_cat.get("roles", [])),
                "rulebooks_count": len(by_cat.get("rulebooks", [])),
                "records_count": len(by_cat.get("records", [])),
                "topic_ids_by_category": by_cat,
                "last_created_at_iso": latest_created,
                "last_fetched_at_iso": latest_fetched,
                "total_approx_tokens": total_tokens,
            }
            afp.write(json.dumps(payload, ensure_ascii=False) + "\n")

            role_items = [it for it in items if it.category == "roles"]
            role_items.sort(key=lambda r: (r.created_at_iso or "", r.topic_id))
            sample_ids = [it.topic_id for it in role_items[:sample_size]]
            if len(role_items) > sample_size:
                tail = [it.topic_id for it in role_items[-sample_size:]]
                merged = []
                for tid in sample_ids + tail:
                    if tid not in merged:
                        merged.append(tid)
                sample_ids = merged[:sample_size]

            sfp.write(
                json.dumps(
                    {
                        "author": author,
                        "sample_size": sample_size,
                        "sample_topic_ids": sample_ids,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def build_topic_refs(client: ForumClient, category: str) -> List[TopicRef]:
    refs: List[TopicRef] = []
    if category in ("all", "roles"):
        for topic_id in sorted(collect_role_topics(client)):
            refs.append(TopicRef(topic_id=topic_id, category="roles"))

    if category in ("all", "rulebooks"):
        for topic_id in sorted(collect_board_topics(client, board_id=RULEBOOK_BOARD_ID, prefix=None)):
            refs.append(TopicRef(topic_id=topic_id, category="rulebooks"))

    if category in ("all", "records"):
        for topic_id in sorted(collect_board_topics(client, board_id=RECORD_BOARD_ID, prefix=RECORD_PREFIX)):
            refs.append(TopicRef(topic_id=topic_id, category="records"))

    return refs


def env_bool(cfg: Dict[str, str], key: str, default: bool) -> bool:
    val = cfg.get(key)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def to_int(value: object, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(str(value))
    except Exception:
        return default


def parse_topic_id_from_source_url(url: str) -> Optional[int]:
    try:
        q = parse_qs(urlparse(url).query)
        vals = q.get("topic")
        if not vals:
            return None
        raw = vals[0]
        m = re.match(r"(\d+)", raw)
        return int(m.group(1)) if m else None
    except Exception:
        return None


def try_report_post(
    client: ForumClient,
    enabled: bool,
    report_topic_id: int,
    subject: str,
    message: str,
    warnings: List[WarningEntry],
    run_id: str,
) -> None:
    if not enabled:
        return
    try:
        client.post_reply(topic_id=report_topic_id, subject=subject, message=message)
    except Exception as exc:
        warnings.append(
            WarningEntry(
                run_id=run_id,
                topic_id=report_topic_id,
                category="report",
                file_path="",
                floor_index=None,
                warning_type="report_post_failed",
                message=str(exc),
                snippet=message[:180],
                created_at_iso=now_forum_iso(),
            )
        )


def run_sync(repo_root: Path, config_path: Path, category: str, dry_run: bool) -> int:
    cfg = load_env_file(config_path)
    required = ["SMF_BASE_URL", "SMF_USERNAME", "SMF_PASSWORD"]
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        raise RuntimeError(f"Missing required config keys: {', '.join(missing)}")

    ensure_dirs(repo_root)

    delay_ms = int(cfg.get("REQUEST_DELAY_MS", "500"))
    ua = cfg.get("USER_AGENT", "no81-kb-sync/1.0")
    report_enabled = env_bool(cfg, "ENABLE_REPORT_POST", False)
    report_on_start = env_bool(cfg, "REPORT_ON_START", True)
    report_on_finish = env_bool(cfg, "REPORT_ON_FINISH", True)
    report_topic_id = int(cfg.get("REPORT_TOPIC_ID", str(DEFAULT_REPORT_TOPIC_ID)))
    sample_size = int(cfg.get("AUTHOR_SAMPLE_SIZE", str(DEFAULT_SAMPLE_SIZE)))
    skip_existing = env_bool(cfg, "SKIP_EXISTING_TOPICS", True)
    client = ForumClient(cfg["SMF_BASE_URL"], delay_ms=delay_ms, user_agent=ua)
    client.login(cfg["SMF_USERNAME"], cfg["SMF_PASSWORD"])

    run_id = uuid.uuid4().hex[:12]
    run_start = time.time()
    warning_entries: List[WarningEntry] = []

    if not dry_run and report_on_start:
        start_msg = f"{now_forum_compact()}开始工作\nrun_id={run_id}\ncategory={category}"
        try_report_post(
            client=client,
            enabled=report_enabled,
            report_topic_id=report_topic_id,
            subject="[KB同步] 开始",
            message=start_msg,
            warnings=warning_entries,
            run_id=run_id,
        )

    refs = build_topic_refs(client, category)
    print(f"Collected topic refs: {len(refs)}")

    state_path = repo_root / "tools" / "no81_sync" / "state" / "state.json"
    state = load_state(state_path)
    topic_state_raw = state.setdefault("topics", {})
    if not isinstance(topic_state_raw, dict):
        topic_state_raw = {}
        state["topics"] = topic_state_raw
    topic_state: Dict[str, Dict[str, str]] = topic_state_raw  # type: ignore[assignment]

    index_rows: List[TopicResult] = []
    added_count = 0
    updated_count = 0
    unchanged_count = 0
    failed_count = 0

    for i, ref in enumerate(refs, start=1):
        state_key = f"{ref.category}:{ref.topic_id}"
        old = topic_state.get(state_key, {})
        old_file_rel = str(old.get("file_path", ""))
        old_path = (repo_root / old_file_rel) if old_file_rel else None
        if skip_existing and old_file_rel and old_path and old_path.exists():
            unchanged_count += 1
            index_rows.append(
                TopicResult(
                    topic_id=ref.topic_id,
                    category=ref.category,
                    title=str(old.get("title", "")),
                    author=str(old.get("author", "unknown")),
                    created_at_raw=str(old.get("created_at_raw", "unknown")),
                    created_at_iso=(str(old.get("created_at_iso")) if old.get("created_at_iso") else None),
                    fetched_at_raw=str(old.get("fetched_at_raw", "")),
                    fetched_at_iso=str(old.get("fetched_at_iso", now_forum_iso())),
                    source_url=str(old.get("source_url", f"{cfg['SMF_BASE_URL'].rstrip('/')}/index.php?topic={ref.topic_id}.0")),
                    file_path=old_file_rel.replace("\\", "/"),
                    status="unchanged",
                    approx_chars=to_int(old.get("approx_chars", 0), 0),
                    approx_tokens=to_int(old.get("approx_tokens", 0), 0),
                    data_quality=str(old.get("data_quality", "ok")),
                )
            )
            continue

        print(f"[{i}/{len(refs)}] Fetching topic {ref.topic_id} ({ref.category})")
        try:
            html = client.fetch_printpage(ref.topic_id)
            title, posts = parse_topic_from_printpage(html)

            source_url = f"{cfg['SMF_BASE_URL'].rstrip('/')}/index.php?topic={ref.topic_id}.0"
            markdown, meta = build_markdown(
                topic_id=ref.topic_id,
                title=title,
                category=ref.category,
                source_url=source_url,
                posts=posts,
            )

            if bool(meta.get("has_spoiler_warning")):
                warning_entries.append(
                    WarningEntry(
                        run_id=run_id,
                        topic_id=ref.topic_id,
                        category=ref.category,
                        file_path="",
                        floor_index=None,
                        warning_type="spoiler_hidden",
                        message="Spoiler content may still be hidden due to permissions.",
                        snippet="Sorry but you are not allowed to view spoiler contents.",
                        created_at_iso=now_forum_iso(),
                    )
                )

            content_hash = sha256_text(markdown)

            output_dir = category_output_dir(repo_root, ref.category)
            filename = f"{ref.topic_id}-{slugify_title(title)}.md"
            output_path = output_dir / filename

            existed_before = output_path.exists() or (old_path.exists() if old_path else False)
            changed = content_hash != old.get("hash") or not output_path.exists()
            if not changed and existed_before:
                status = "unchanged"
                unchanged_count += 1
            elif existed_before:
                status = "updated"
                updated_count += 1
            else:
                status = "added"
                added_count += 1

            if changed and not dry_run:
                output_path.write_text(markdown, encoding="utf-8")

            file_rel = str(output_path.relative_to(repo_root)).replace("\\", "/")
            topic_state[state_key] = {
                "topic_id": str(ref.topic_id),
                "category": ref.category,
                "title": title,
                "author": posts[0].author if posts else "unknown",
                "created_at_raw": str(meta.get("created_at_raw", "")),
                "created_at_iso": str(meta.get("created_at_iso", "")),
                "fetched_at_raw": str(meta.get("fetched_at_raw", "")),
                "fetched_at_iso": str(meta.get("fetched_at_iso", "")),
                "source_url": source_url,
                "hash": content_hash,
                "file_path": file_rel,
                "approx_chars": str(meta.get("approx_chars", 0)),
                "approx_tokens": str(meta.get("approx_tokens", 0)),
                "data_quality": str(meta.get("data_quality", "ok")),
            }

            index_rows.append(
                TopicResult(
                    topic_id=ref.topic_id,
                    category=ref.category,
                    title=title,
                    author=posts[0].author if posts else "unknown",
                    created_at_raw=str(meta.get("created_at_raw", "unknown")),
                    created_at_iso=(str(meta.get("created_at_iso")) if meta.get("created_at_iso") else None),
                    fetched_at_raw=str(meta.get("fetched_at_raw", now_forum_time())),
                    fetched_at_iso=str(meta.get("fetched_at_iso", now_forum_iso())),
                    source_url=source_url,
                    file_path=file_rel,
                    status=status,
                    approx_chars=to_int(meta.get("approx_chars", 0), 0),
                    approx_tokens=to_int(meta.get("approx_tokens", 0), 0),
                    data_quality=str(meta.get("data_quality", "ok")),
                )
            )
        except Exception as exc:
            failed_count += 1
            warning_entries.append(
                WarningEntry(
                    run_id=run_id,
                    topic_id=ref.topic_id,
                    category=ref.category,
                    file_path="",
                    floor_index=None,
                    warning_type="topic_fetch_failed",
                    message=str(exc),
                    snippet="",
                    created_at_iso=now_forum_iso(),
                )
            )

    if not dry_run:
        save_state(state_path, state)
        write_indexes(repo_root, index_rows)
        write_warnings(repo_root, warning_entries)
        write_author_indexes(repo_root, index_rows, sample_size=sample_size)

    warning_count = len(warning_entries)
    duration = int(time.time() - run_start)
    if not dry_run and report_on_finish:
        finish_msg = (
            f"{now_forum_compact()}结束工作\n"
            f"run_id={run_id}\n"
            f"追加{added_count}条，更新{updated_count}条，未变更{unchanged_count}条，告警{warning_count}条，失败{failed_count}条，耗时{duration}秒"
        )
        try_report_post(
            client=client,
            enabled=report_enabled,
            report_topic_id=report_topic_id,
            subject="[KB同步] 结束",
            message=finish_msg,
            warnings=warning_entries,
            run_id=run_id,
        )

    print(
        f"Sync complete. added={added_count}, updated={updated_count}, unchanged={unchanged_count}, warnings={warning_count}, failed={failed_count}"
    )

    return 0


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync No81 forum topics to local Markdown KB")
    parser.add_argument(
        "--category",
        choices=["all", "roles", "rulebooks", "records"],
        default="all",
        help="Which category to sync",
    )
    parser.add_argument(
        "--config",
        default="tools/no81_sync/.env",
        help="Path to local config file",
    )
    parser.add_argument("--dry-run", action="store_true", help="Run without writing files")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str]) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    config_path = (repo_root / args.config).resolve()

    try:
        return run_sync(
            repo_root=repo_root,
            config_path=config_path,
            category=args.category,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
