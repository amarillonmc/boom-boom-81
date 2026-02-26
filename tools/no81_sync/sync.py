from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup


FORUM_TZ = ZoneInfo("Asia/Shanghai")

ROLE_INDEX_TOPIC_ID = 1378
RULEBOOK_BOARD_ID = 15
RECORD_BOARD_ID = 14
RECORD_PREFIX = 3


@dataclass
class TopicRef:
    topic_id: int
    category: str


@dataclass
class PostBlock:
    title: str
    author: str
    posted_at: str
    body: str


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

        action = form.get("action") or ""
        action_url = urljoin(self.base_url + "/", action)
        if "action=login2" not in action_url:
            action_url = f"{self.base_url}/index.php?action=login2"

        payload: Dict[str, str] = {}
        for field in form.select("input[name]"):
            name = field.get("name", "").strip()
            value = field.get("value", "")
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


def extract_topic_ids_from_html(html: str) -> Set[int]:
    soup = BeautifulSoup(html, "html.parser")
    topic_ids: Set[int] = set()
    for a in soup.find_all("a", href=True):
        href = normalize_url(a["href"])
        match = re.search(r"topic=(\d+)\.0(?:\b|$)", href)
        if match:
            topic_ids.add(int(match.group(1)))
    return topic_ids


def extract_board_offsets(html: str, board_id: int, prefix: Optional[int]) -> Set[int]:
    soup = BeautifulSoup(html, "html.parser")
    offsets: Set[int] = set()
    for a in soup.find_all("a", href=True):
        href = normalize_url(a["href"])
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


def html_to_clean_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    text = unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_printpage_posts(text: str) -> List[PostBlock]:
    pattern = re.compile(
        r"标题:\s*(?P<title>.+?)\s*作者:\s*(?P<author>.+?)\s*于\s*(?P<time>.+?)\s*(?P<body>.*?)(?=(?:\n标题:\s*.+?\n作者:\s*.+?\s*于\s*.+?)|\Z)",
        re.S,
    )
    posts: List[PostBlock] = []

    for match in pattern.finditer(text):
        title = match.group("title").strip()
        author = match.group("author").strip()
        posted_at = match.group("time").strip()
        body = match.group("body").strip()
        body = re.sub(r"\n{3,}", "\n\n", body)
        posts.append(PostBlock(title=title, author=author, posted_at=posted_at, body=body))

    return posts


def parse_topic_from_printpage(html: str) -> Tuple[str, List[PostBlock]]:
    soup = BeautifulSoup(html, "html.parser")
    page_title = soup.title.get_text(strip=True) if soup.title else "Untitled"
    topic_title = re.sub(r"^打印本页\s*-\s*", "", page_title).strip()

    text = html_to_clean_text(html)
    posts = parse_printpage_posts(text)

    if not posts:
        fallback_body = text
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
) -> Tuple[str, bool]:
    first_post = posts[0]
    has_spoiler_warning = any("Sorry but you are not allowed to view spoiler contents." in p.body for p in posts)

    lines: List[str] = []
    lines.append("---")
    lines.append(f'topic_id: {topic_id}')
    lines.append(f'title: "{yaml_escape(title)}"')
    lines.append(f'category: "{category}"')
    lines.append(f'source_url: "{source_url}"')
    lines.append(f'author: "{yaml_escape(first_post.author)}"')
    lines.append(f'created_at: "{yaml_escape(first_post.posted_at)}"')
    lines.append(f'fetched_at: "{now_forum_time()}"')
    lines.append("---")
    lines.append("")
    lines.append(f"# {title}")
    lines.append("")

    for idx, post in enumerate(posts, start=1):
        lines.append(f"## {idx}F")
        lines.append("")
        lines.append(f"- Author: {post.author}")
        lines.append(f"- Posted at: {post.posted_at}")
        lines.append("")
        lines.append(post.body)
        lines.append("")

    markdown = "\n".join(lines).strip() + "\n"
    return markdown, has_spoiler_warning


def sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def load_state(path: Path) -> Dict[str, Dict[str, str]]:
    if not path.exists():
        return {"topics": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: Dict[str, Dict[str, str]]) -> None:
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


def write_indexes(repo_root: Path, rows: List[Dict[str, str]]) -> None:
    index_dir = repo_root / "kb" / "index"
    index_dir.mkdir(parents=True, exist_ok=True)

    csv_path = index_dir / "topics.csv"
    fields = [
        "topic_id",
        "category",
        "title",
        "author",
        "created_at",
        "fetched_at",
        "source_url",
        "file_path",
        "status",
    ]

    with csv_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    jsonl_path = index_dir / "topics.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as fp:
        for row in rows:
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")


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


def run_sync(repo_root: Path, config_path: Path, category: str, dry_run: bool) -> int:
    cfg = load_env_file(config_path)
    required = ["SMF_BASE_URL", "SMF_USERNAME", "SMF_PASSWORD"]
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        raise RuntimeError(f"Missing required config keys: {', '.join(missing)}")

    ensure_dirs(repo_root)

    delay_ms = int(cfg.get("REQUEST_DELAY_MS", "500"))
    ua = cfg.get("USER_AGENT", "no81-kb-sync/1.0")
    client = ForumClient(cfg["SMF_BASE_URL"], delay_ms=delay_ms, user_agent=ua)
    client.login(cfg["SMF_USERNAME"], cfg["SMF_PASSWORD"])

    refs = build_topic_refs(client, category)
    print(f"Collected topic refs: {len(refs)}")

    state_path = repo_root / "tools" / "no81_sync" / "state" / "state.json"
    state = load_state(state_path)
    topic_state_raw = state.setdefault("topics", {})
    if not isinstance(topic_state_raw, dict):
        topic_state_raw = {}
        state["topics"] = topic_state_raw
    topic_state: Dict[str, Dict[str, str]] = topic_state_raw  # type: ignore[assignment]

    index_rows: List[Dict[str, str]] = []
    warnings: List[str] = []

    for i, ref in enumerate(refs, start=1):
        print(f"[{i}/{len(refs)}] Fetching topic {ref.topic_id} ({ref.category})")
        html = client.fetch_printpage(ref.topic_id)
        title, posts = parse_topic_from_printpage(html)

        source_url = f"{cfg['SMF_BASE_URL'].rstrip('/')}/index.php?topic={ref.topic_id}.0"
        markdown, spoiler_warning = build_markdown(
            topic_id=ref.topic_id,
            title=title,
            category=ref.category,
            source_url=source_url,
            posts=posts,
        )

        if spoiler_warning:
            warnings.append(f"topic={ref.topic_id}: spoiler content may still be hidden")

        content_hash = sha256_text(markdown)
        state_key = f"{ref.category}:{ref.topic_id}"
        old = topic_state.get(state_key, {})

        output_dir = category_output_dir(repo_root, ref.category)
        filename = f"{ref.topic_id}-{slugify_title(title)}.md"
        output_path = output_dir / filename

        changed = content_hash != old.get("hash") or not output_path.exists()
        status = "updated" if changed else "unchanged"
        if spoiler_warning:
            status = f"{status};spoiler-warning"

        if changed and not dry_run:
            output_path.write_text(markdown, encoding="utf-8")

        topic_state[state_key] = {
            "topic_id": str(ref.topic_id),
            "category": ref.category,
            "title": title,
            "hash": content_hash,
            "file_path": str(output_path.relative_to(repo_root)).replace("\\", "/"),
            "fetched_at": now_forum_time(),
        }

        index_rows.append(
            {
                "topic_id": str(ref.topic_id),
                "category": ref.category,
                "title": title,
                "author": posts[0].author if posts else "unknown",
                "created_at": posts[0].posted_at if posts else "unknown",
                "fetched_at": now_forum_time(),
                "source_url": source_url,
                "file_path": str(output_path.relative_to(repo_root)).replace("\\", "/"),
                "status": status,
            }
        )

    if not dry_run:
        save_state(state_path, state)
        write_indexes(repo_root, index_rows)

    if warnings:
        warn_path = repo_root / "kb" / "index" / "warnings.txt"
        content = "\n".join(warnings) + "\n"
        if not dry_run:
            warn_path.write_text(content, encoding="utf-8")
        print(f"Warnings: {len(warnings)} (see kb/index/warnings.txt)")

    print("Sync complete.")
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
