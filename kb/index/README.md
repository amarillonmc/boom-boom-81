# Index Guide (LLM/Agent)

Purpose: route questions to the smallest relevant file set with minimal token usage.

## Read Order

1. Read `kb/index/topics.jsonl` (preferred) or `kb/index/topics.csv`.
2. Filter by `category` and keywords.
3. Open only matched `file_path` Markdown files.
4. Synthesize answer.

Do not scan all files first.

## Categories

- `roles`: character cards
- `rulebooks`: rules and frameworks
- `records`: completed battle records

## Index Fields

- `topic_id`: forum topic id
- `category`: one of `roles | rulebooks | records`
- `title`: topic title
- `author`: topic starter (or parsed first post author)
- `created_at`: first post time (forum format)
- `fetched_at`: local sync time (UTC+8)
- `source_url`: original forum topic URL
- `file_path`: local markdown path to read
- `status`: sync status (`updated`, `unchanged`, optional warnings)

## Query Routing Patterns

- Author style/profile questions:
  - filter `author == <name>`
  - start with `roles`, then `records` for behavior evidence

- Character performance across battles:
  - filter `category == records`
  - match character name in `title` and body

- Rule/system/model issues:
  - start with `rulebooks`
  - validate with examples in `records`

## Data Quality Notes

- If spoiler permission failed during sync, see `kb/index/warnings.txt`.
- Media files are intentionally excluded; text only.
