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
- `kb/index/`

## Setup

1. Create a local config file:

```bash
cp tools/no81_sync/config.example.env tools/no81_sync/.env
```

2. Fill in your SMF account in `tools/no81_sync/.env`.

3. Install dependencies:

```bash
python -m pip install -r tools/no81_sync/requirements.txt
```

## Run

Export all categories:

```bash
python tools/no81_sync/sync.py
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

By default `SKIP_EXISTING_TOPICS=true` to avoid re-fetching already-synced topics in large libraries.

Set `SKIP_EXISTING_TOPICS=false` if you want to force re-check existing topics.

## Notes

- The script uses SMF login via `action=login` -> `action=login2`.
- Export is text-first. Images/media are not downloaded.
- A local state file is used for incremental writes:
  - `tools/no81_sync/state/state.json`
