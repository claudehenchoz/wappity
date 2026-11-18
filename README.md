# rps-games

<!-- library:start -->
**Latest thread:** [#408 · 14 Nov 2026](library/weeks/2026-11-14-408.md) — Queen's Domain, The Legend of Zelda: Ocarina of Time, Cyberpunk 2077, Control Resonant, Euro Truck Simulator 2

**Library:** [Last 3 months](library/last-3-months.md) · [All weeks](library/index.md)
<!-- library:end -->

Extracts the games people mention in the comments of Rock Paper Shotgun's weekly
*"What are we all playing this weekend?"* threads, normalizes them to canonical titles,
and ranks them.

```
RPS archive ─► newest thread ─► parse comments ─► Claude extracts mentions ─► IGDB normalizes ─► library/ + CSVs
```

A GitHub Action runs this every Thursday at 16:00 Swiss time on the previous weekend's thread.
Each run adds a page to [`library/`](library/index.md), refreshes the
[last-three-months view](library/last-3-months.md) and updates the links above.

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

### Update the library (what the Action runs)

```sh
uv run rps-games weekly                     # newest thread, if it's not in the library yet
uv run rps-games weekly --backfill-weeks 13 # the 13 newest threads (about three months)
uv run rps-games weekly --force             # reprocess even if already in the library
```

`weekly` finds threads through RPS's monthly archive pages
(`/archive/YYYY/MM`), so it needs no URL. It skips threads already saved in `library/data/`,
so running it twice is harmless. It then regenerates every library page and the block at the top
of this README.

To regenerate the markdown from `library/data/` without any network or API calls:

```sh
uv run rps-games render
```

### Process a single thread

```sh
uv run rps-games thread "https://www.rockpapershotgun.com/what-are-we-all-playing-this-weekend-408"
```

The URL works with or without `?view=comments`. The command prints the top 25 games and writes
the full results to `data/thread-<id>/`. Add `--save` to also add the thread to the library.
The short form `uv run rps-games <URL>` still works.

### Options

`thread` and `weekly` both accept:

| Flag | Default | Description |
|---|---|---|
| `--data DIR` | `data` | Directory for caches and outputs |
| `--model ID` | `claude-opus-5-5` | Claude model for extraction and IGDB disambiguation, e.g. `claude-haiku-5-5` for a cheaper run |
| `--effort` | `low` | Extraction effort: `low`, `medium` or `high` |
| `--batch-chars N` | `12000` | Characters of comment text per Claude call. Lower this if a batch fails with `max_tokens` |
| `--min-confidence X` | `0.5` | Drop mentions Claude rated below this confidence (0–1) |
| `--parse-only` | off | `thread` only: fetch and parse, write `comments.json`, skip Claude and IGDB |

## Automation (GitHub Actions)

The workflow in [`.github/workflows/weekly.yml`](.github/workflows/weekly.yml):

1. Runs every Thursday at 16:00 Europe/Zurich time, following summer time. GitHub's cron only
   understands UTC, so the workflow is triggered at both 14:00 and 15:00 UTC, and a guard step
   skips whichever one is too early. In summer the second trigger finds nothing new and does nothing.
2. Runs `rps-games weekly`.
3. Commits any changes to `library/`, `data/aliases.json` and `README.md` as `github-actions[bot]`
   and pushes them to `main`.

The threads come out on Saturday mornings, so by Thursday most of the comments are in.

### Secrets

In the GitHub repository, go to **Settings → Secrets and variables → Actions → New repository
secret** and add:

| Secret | Required | Value |
|---|---|---|
| `ANTHROPIC_API_KEY` | yes | Your Anthropic API key |
| `TWITCH_CLIENT_ID` | recommended | Twitch app Client ID, for IGDB |
| `TWITCH_CLIENT_SECRET` | recommended | Twitch app Client Secret, for IGDB |

The workflow pushes with the built-in `GITHUB_TOKEN`; no personal token is needed.

### Running it by hand

Go to **Actions → Weekly games library → Run workflow**. The inputs are:

- `backfill_weeks`: also process the N newest threads. Use `13` on the first run to fill the
  three-month view straight away.
- `force`: reprocess threads that are already in the library.

GitHub turns off scheduled workflows after 60 days without commits. The weekly bot commit keeps the
repository active, but if a run fails for weeks in a row, check the Actions tab.

## Library

Everything under `library/` is generated. Don't edit the markdown by hand; it is rebuilt on every run.

| Path | Contents |
|---|---|
| `library/data/<date>-<n>.json` | The source data for each thread: ranked games and one row per mention. The pages are built from these |
| `library/weeks/<date>-<n>.md` | One page per thread: a ranked table plus the games mentioned only once |
| `library/last-3-months.md` | Every thread from the 91 days up to the newest one, with unique players and mentioners counted across all of those weeks, plus what's new this week |
| `library/index.md` | All threads, newest first, each with its top 3 games |

The block at the top of this README is rewritten between the `<!-- library:start -->
**Latest thread:** [#408 · 14 Nov 2026](library/weeks/2026-11-14-408.md) — Queen's Domain, The Legend of Zelda: Ocarina of Time, Cyberpunk 2077, Control Resonant, Euro Truck Simulator 2

**Library:** [Last 3 months](library/last-3-months.md) · [All weeks](library/index.md)
<!-- library:end -->` markers. Leave the markers in place.

## Per-thread CSVs

Each processed thread also writes these files to `data/thread-<id>/`. They are not committed:

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

Games are sorted by `players`, then `mentioners`, then likes. The library pages use the same
numbers: *Played by* is `players` and *Mentioned by* is `mentioners`.

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

A fix only affects threads processed afterwards. To apply it to weeks already in the library, run
`uv run rps-games weekly --backfill-weeks N --force` locally and commit the result. This is cheap
locally, because the Claude results are cached in `data/`. In GitHub Actions the cache isn't kept
between runs, so the Claude calls would be paid for again.

## Project layout

```
rps_games/
  discover.py  lists weekend threads from RPS's monthly archive pages
  fetch.py     reads the publish date and thread id from the article, downloads /community/thread/<id>
  parse.py     turns the thread HTML into flat comments with reply parents
  extract.py   batched Claude calls with a fixed response format, cached per model
  resolve.py   IGDB search + fuzzy matching + Claude tie-breaking, or title merging without IGDB
  pipeline.py  runs one thread end to end, writes the CSVs, returns the week's results
  library.py   saves week JSON and renders the week pages, the 3-month view, the index and the README block
  cli.py       the thread / weekly / render subcommands
.github/workflows/weekly.yml   the Thursday schedule
```
