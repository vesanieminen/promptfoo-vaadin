# Shared eval dataset

This directory is the **version-controlled, mergeable** form of the benchmark's
promptfoo results. Clone the repo, pull it into your local promptfoo store, run
your own evals, push the new ones back, and open a PR — many people can extend
the dataset in parallel without binary merge conflicts.

## Why this exists instead of committing `promptfoo.db`

promptfoo keeps everything in a single ~280 MB SQLite file (`~/.promptfoo/promptfoo.db`).
That file is a binary blob: it **cannot be merged**, and every commit would store
a fresh full copy. So instead we keep the data exploded into per-eval files:

| Path | What | Git behaviour |
|------|------|---------------|
| `evals/<id>.json` | one `promptfoo export eval` per eval | per-eval → two people adding different evals never collide |
| `blobs/<aa>/<bb>/<hash>` | screenshot bytes + `.meta.json`, content-addressed | immutable → git dedups, no conflicts |
| `blob-index/<id>.json` | the `blob_assets` + `blob_references` rows for that eval | per-eval, append-only |

(`promptfoo export`/`import` round-trips the eval JSON but **drops blobs**, which
is why blobs + blob-index are synced separately.)

## Requirements

- Node 18+ (uses the built-in `node:sqlite` — no extra install)
- promptfoo available as `npx promptfoo` (or set `PROMPTFOO_BIN` to a global install)

## Use it

```bash
# After `git pull` — load the shared dataset into your local promptfoo store:
bench/pf-data-pull.sh
promptfoo view                 # browse everything, screenshots included

# Run your own evals however you normally do (bench/run.sh, etc.), then:
bench/pf-data-push.sh          # sync the dataset to the evals cited in docs/ reports
git add bench/data && git commit -m "Add eval runs" && git push
```

Both commands are idempotent and safe to re-run. They honour `PROMPTFOO_CONFIG_DIR`.

### Push scope

By default `push` is **report-scoped**: it scans `docs/` (the bench reports) for
eval IDs and makes the dataset hold *exactly* those — exporting the referenced
evals and pruning any eval/blob no longer cited. So adding an eval to the shared
set means referencing it from a report, then pushing. A bare `push` never drags
in unrelated local evals.

```bash
bench/pf-data-push.sh --all              # export every local eval, prune nothing
bench/pf-data-push.sh eval-abc eval-def  # export only these IDs, prune nothing
```

## Notes

- Eval IDs contain `:`; filenames replace it with `_` for Windows portability.
  The real ID lives inside the JSON, so this is cosmetic.
- `pull` rewrites each blob's `.meta.json` `key` to your local absolute path.
## Git LFS

`evals/**` and `blobs/**` are tracked with **Git LFS** (see `.gitattributes`) —
the eval JSON carries full traces/outputs (~1 MB each), so the dataset is large
and grows with every run. Per-eval files still merge cleanly under LFS: LFS only
struggles with *concurrent edits to one file*, which never happens here because
each eval is its own file. `blob-index/` stays in plain git (tiny, append-only).

Collaborators need Git LFS installed (`brew install git-lfs` / `apt install
git-lfs`, then `git lfs install`) before cloning, or run `git lfs pull` after.
