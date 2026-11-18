# rps-games

Extracts the games people mention in the comments of Rock Paper Shotgun's weekly
*"What are we all playing this weekend?"* threads, normalizes them to canonical titles,
and ranks them.

```
article URL ─► fetch comment thread ─► parse comments ─► Claude extracts mentions ─► IGDB normalizes ─► CSVs
```

## Requirements

- Python 3.13+ and [uv](https://docs.astral.sh/uv/)
- An Anthropic API key
- Optional, recommended: IGDB access through a Twitch developer app, for canonical names and release years

## Setup

```sh
uv sync
export ANTHROPIC_API_KEY=sk-ant-...
```

### IGDB credentials (optional)

1. Create an application at <https://dev.twitch.tv/console/apps>. Any name works;
   use `http://localhost` as the OAuth redirect URL and pick the *Confidential* client type.
2. Copy the Client ID and generate a Client Secret.
3. Export them:

   ```sh
   export TWITCH_CLIENT_ID=...
   export TWITCH_CLIENT_SECRET=...
   ```

Without these, titles are normalized by merging near-identical spellings of Claude's titles
instead of matching them against IGDB. No release years are available in that mode.

## Usage

```sh
uv run rps-games "https://www.rockpapershotgun.com/what-are-we-all-playing-this-weekend-408"
```

The URL works with or without `?view=comments`. The command prints the top 25 games and writes
the full results to `data/thread-<id>/`.

### Options

| Flag | Default | Description |
|---|---|---|
| `--data DIR` | `data` | Directory for caches and outputs |
| `--model ID` | `claude-opus-5-5` | Claude model for extraction and IGDB disambiguation, e.g. `claude-haiku-5-5` for a cheaper run |
| `--effort` | `low` | Extraction effort: `low`, `medium` or `high` |
| `--batch-chars N` | `12000` | Characters of comment text per Claude call. Lower this if a batch fails with `max_tokens` |
| `--min-confidence X` | `0.5` | Drop mentions Claude rated below this confidence (0–1) |
| `--parse-only` | off | Fetch and parse only, write `comments.json`, skip Claude and IGDB |

## Output

The tool writes these files to `data/thread-<id>/`:

| File | Contents |
|---|---|
| `comments.json` | Every comment: `id`, `parent_id`, `depth`, `author`, `date` (Unix time), `likes`, `text` |
| `extractions.json` | Raw Claude output per comment, cached per model |
| `mentions.csv` | One row per game mention in a comment. Columns: the text as written, Claude's title, the resolved game and year, `relation`, `confidence`, and `method` (how the title was matched) |
| `games.csv` | One row per game, ranked |

### How games are ranked

Each mention is tagged with a `relation`:

| Relation | Meaning |
|---|---|
| `playing` | Playing it now or this weekend |
| `finished` | Recently completed it |
| `dropped` | Gave up on it |
| `planning` | Intends to play it |
| `mentioned` | Anything else |
| `comparison` | Only used for comparison ("feels like Planescape") |

`games.csv` counts each commenter at most once per game. Its columns are:

- `players`: commenters who are `playing`, `finished` or `dropped` it
- `mentioners`: commenters who mention it in any way
- `comments`: number of comments that mention it
- `likes_on_comments`: total likes on those comments

Games are sorted by `players`, then `mentioners`, then likes.

## Caching and reruns

Reruns are cheap and safe:

- **Downloaded pages:** `data/raw/` keeps the downloaded HTML, so RPS is fetched once per thread.
  Delete the thread's files there to fetch again, for example after more comments are posted.
- **Claude results:** saved per model and comment, so a rerun only sends comments that are new
  or failed last time. A failed batch is reported and retried on the next run.
- **Title matches:** `data/aliases.json` stores every resolved title and is shared across threads,
  so games that come up every week skip IGDB and Claude.

### Fixing a wrong match

Edit the entry in `data/aliases.json`. The tool adds new entries but never overwrites existing
ones. Each entry is keyed by the normalized title:

```json
"doom": {"key": "igdb:7351", "name": "Doom", "year": 2016, "method": "manual"}
```

Use `igdb:<id>` for an IGDB game or `title:<anything>` for a custom group.
To check matches, filter `mentions.csv` on `method`:

| `method` | How the title was matched |
|---|---|
| `exact` / `fuzzy` | Clear IGDB match |
| `llm` | Claude picked among IGDB candidates |
| `unresolved` | No IGDB match; Claude's title is kept |
| `cluster` | Spellings merged; IGDB not configured |

The `fuzzy` and `llm` rows are the ones most worth reviewing.

## Project layout

```
rps_games/
  fetch.py    finds the thread id on the article page, downloads /community/thread/<id>
  parse.py    turns the thread HTML into flat comments with reply parents
  extract.py  batched Claude calls with a fixed response format, cached per model
  resolve.py  IGDB search + fuzzy matching + Claude tie-breaking, or title merging without IGDB
  cli.py      runs the steps in order and writes the CSVs
```
