# Agent guide — swim-club-tech-survey

`swim-club-tech-survey` is a fully automated monthly crawl. It walks every Swimming Canada–
registered club's website, fingerprints which team-management / registration platform they
use, and publishes the result as a CSV + an interactive HTML report on GitHub Pages.
Canadian clubs today; the scope note in
[`docs/data_sources.md`](docs/data_sources.md) tracks where the boundary is.

## Canonical rules

The cross-repo rules for any SwimBlocks project live in the [`swimblocks/.github`](https://github.com/swimblocks/.github)
standards repo. Read these first:

- [AGENTS.md](https://github.com/swimblocks/.github/blob/main/AGENTS.md) — distilled agent guide
- [CONTRIBUTING.md](https://github.com/swimblocks/.github/blob/main/CONTRIBUTING.md) —
  long-form house rules
- [development.md](https://github.com/swimblocks/.github/blob/main/docs/development.md) —
  setting up a new machine

Everything below is **repo-specific** — quirks that the canonical guide doesn't cover.

## Repo-specific quirks

- **The pipeline runs in CI, not locally.** [`.github/workflows/run_survey.yml`](.github/workflows/run_survey.yml)
  is the production driver: it runs `python main.py`, copies the report into
  `output/index.html`, deploys to GitHub Pages, and cuts a tagged release with the
  results CSV attached. Manual local runs are fine for development; treat the workflow as
  source of truth for the production cadence (monthly, 1st of the month, 06:00 UTC).
- **Provincial directories first, national API as fallback.** Each province's scraper lives
  in `src/clubs.py` (or related modules). The national Swimming Canada feed is the
  fallback. Issue [#13](https://github.com/swimblocks/swim-club-tech-survey/issues/13)
  tracks the in-progress shift; new provincial scrapers go in via that pattern.
- **Don't commit raw club CSVs.** `data/clubs_raw.csv` and `data/results.csv` are
  gitignored — they're regenerated each run. `clubs.json` and `name_resolutions.json`
  *are* committed because CI needs them as inputs.
- **No officials PII.** This repo only handles **club-level** info (name, province, city,
  website). Even so, the README warns that individual club addresses are not stored or
  published. Keep it that way — if a scraper ever pulls down an address or contact, scrub
  it before it lands in `data/`.
- **Error-rate threshold** is enforced in the workflow: ≥50 clubs with `error` set fails
  the CI run, treating the dataset as unreliable. If you change the scraper in a way that
  legitimately raises errors temporarily, surface that in the PR.
- **Name normalisation is hand-curated.** `src/name_resolution.py` plus the committed
  `name_resolutions.json` handle the "is `WPSC` the same as `Wilmot Pirates Swim Club`?"
  problem. New clubs from a new province typically need a few name-resolution entries.

## Where to start reading

- [`README.md`](README.md) — user-facing overview + diagram of the data flow
- [`docs/data_sources.md`](docs/data_sources.md) — what's authoritative for what
- [`docs/club_discovery.md`](docs/club_discovery.md) — how the club list is assembled
- [`main.py`](main.py) — the production entry point
- [`src/clubs.py`](src/clubs.py) — club discovery
- [`src/detector.py`](src/detector.py) — platform-fingerprinting signatures
- [`.github/workflows/run_survey.yml`](.github/workflows/run_survey.yml) — production driver
