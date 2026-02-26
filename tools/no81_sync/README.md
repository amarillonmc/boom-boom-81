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

## Notes

- The script uses SMF login via `action=login` -> `action=login2`.
- Export is text-first. Images/media are not downloaded.
- A local state file is used for incremental writes:
  - `tools/no81_sync/state/state.json`
