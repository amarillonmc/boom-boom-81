# no81_sync

Syncs No.81 forum content into local Markdown knowledge base files.

## What it exports

- Roles: all topic links found in `topic=1378.0`
- Rulebooks: all topics under `board=15.0`
- Completed records: all topics under `board=14.0;prefix=3`

## Output folders

- `kb/roles/`
- `kb/rulebooks/`
- `kb/records-completed/`
- `kb/deleted/` (archived topics that disappeared from the forum)
- `kb/index/`

## Setup

1. Create a local config file:

```bash
cp tools/no81_sync/config.example.env tools/no81_sync/.env
```

2. Fill in your SMF account in `tools/no81_sync/.env`.

   If your site blocks scripted `login2` posts (e.g. returns `Session 验证失败` on 403),
   you can use cookie auth instead:

   - log in once in browser
   - copy the Cookie header value from that logged-in request (recommended: include both auth cookie and PHPSESSID)
   - set `SMF_COOKIE=...` in `.env`
   - if you only copied the auth cookie value itself, also set `SMF_COOKIE_NAME=...` (e.g. `SMFCookie630`)

   When `SMF_COOKIE` is set, the script will use that session directly and skip username/password login.

3. Install dependencies:

```bash
python -m pip install -r tools/no81_sync/requirements.txt
```

## Run

Export all categories:

```bash
python tools/no81_sync/sync.py
```

Local maintenance/backfill (no re-fetch; updates existing markdown metadata and rebuilds indexes):

```bash
python tools/no81_sync/sync.py --mode maintenance-local
```

Export one category only:

```bash
python tools/no81_sync/sync.py --category roles
python tools/no81_sync/sync.py --category rulebooks
python tools/no81_sync/sync.py --category records
```

Dry run (no file writes):

```bash
python tools/no81_sync/sync.py --dry-run
```

Fast append-only run (do not re-fetch existing topics):

```bash
python tools/no81_sync/sync.py --skip-existing
```

Force re-check existing topics even if `SKIP_EXISTING_TOPICS=true` in config:

```bash
python tools/no81_sync/sync.py --force-existing
```

Sync only topics whose first-floor author matches an author:

```bash
python tools/no81_sync/sync.py --author OPPO
python tools/no81_sync/sync.py --category roles --author OPPO --force-existing
```

Archive/delete local KB topics by first-floor author:

```bash
python tools/no81_sync/sync.py --delete-author OPPO
python tools/no81_sync/sync.py --delete-author OPPO --missing-action delete
```

## New index outputs

- `kb/index/topics.csv`
- `kb/index/topics.jsonl`
- `kb/index/authors.jsonl`
- `kb/index/authors_roles_sample.jsonl`
- `kb/index/warnings.txt`
- `kb/index/warnings.jsonl`

## Reporting posts (topic reply)

The sync can post start/finish status replies to a forum topic (default `topic=35`) using the same SMF credentials.

Config keys:

- `ENABLE_REPORT_POST=true|false`
- `REPORT_ON_START=true|false`
- `REPORT_ON_FINISH=true|false`
- `REPORT_TOPIC_ID=35`

Finish report includes counters: added / updated / unchanged / warnings / failed.

## Differential behavior

By default `SKIP_EXISTING_TOPICS=false`, so existing topics are re-fetched and compared by a stable content hash. This detects edited posts without treating the changing `fetched_at_*` metadata as a content change.

Set `SKIP_EXISTING_TOPICS=true` or pass `--skip-existing` if you want a quick append-only run.

When a previously synced topic no longer appears in the remote category list, the sync treats it as removed from the forum. The default `MISSING_TOPIC_ACTION=archive` moves its Markdown file to:

```text
kb/deleted/<category>/
```

Other options:

```bash
python tools/no81_sync/sync.py --missing-action keep
python tools/no81_sync/sync.py --missing-action delete
```

`archive` and `delete` remove the topic from the active state/index and keep a tombstone entry under `deleted_topics` in `tools/no81_sync/state/state.json`.

If you already completed a full sync before new metadata/index features were added, run:

```bash
python tools/no81_sync/sync.py --mode maintenance-local
```

This backfills existing files and rebuilds `topics/authors/warnings` indexes in batch.

## Notes

- The script uses SMF login via `action=login` -> `action=login2`.
- Some deployments may reject non-browser `login2` POST with session verification errors; use `SMF_COOKIE` fallback in that case.
- Export is text-first. Images/media are not downloaded.
- A local state file is used for incremental writes:
  - `tools/no81_sync/state/state.json`
