// Shared helpers for the git-synced promptfoo eval dataset.
//
// The dataset under bench/data/ is the version-controlled, mergeable form of
// the local promptfoo store (~/.promptfoo). It has three parts:
//
//   data/evals/<id>.json       one promptfoo `export eval` per eval (text, per-eval -> conflict-free)
//   data/blobs/<aa>/<bb>/<h>   content-addressed screenshot bytes + .meta.json (immutable -> dedups in git)
//   data/blob-index/<id>.json  the blob_assets + blob_references rows for that eval
//
// promptfoo's own `export`/`import` round-trips the eval JSON but DROPS blobs,
// so blobs + blob-index are synced by us. Everything is keyed per-eval, so two
// contributors adding different evals never collide.

import { DatabaseSync } from 'node:sqlite';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export const REPO_ROOT = path.resolve(__dirname, '..');
export const DATA_DIR = path.join(__dirname, 'data');
export const EVALS_DIR = path.join(DATA_DIR, 'evals');
export const REPO_BLOBS = path.join(DATA_DIR, 'blobs');
export const INDEX_DIR = path.join(DATA_DIR, 'blob-index');

// Local promptfoo store — honour PROMPTFOO_CONFIG_DIR, matching promptfoo itself
// and bench/attach_shots.js.
export const CONFIG_DIR = process.env.PROMPTFOO_CONFIG_DIR
  ? path.resolve(process.env.PROMPTFOO_CONFIG_DIR)
  : path.join(os.homedir(), '.promptfoo');
export const DB_PATH = path.join(CONFIG_DIR, 'promptfoo.db');
export const LOCAL_BLOBS = path.join(CONFIG_DIR, 'blobs');

export function openDb(readOnly = false) {
  return new DatabaseSync(DB_PATH, { readOnly });
}

// blobs/<first 2 hex>/<next 2 hex>/<full hash>  (matches promptfoo + attach_shots.js)
export function shard(root, hash) {
  return path.join(root, hash.slice(0, 2), hash.slice(2, 4), hash);
}

// Eval IDs contain ':' (e.g. eval-jVc-2026-06-12T16:04:40). Keep filenames
// portable (Windows); the real ID lives inside the JSON, so this is cosmetic.
export function safeName(id) {
  return id.replace(/[:]/g, '_');
}

// Run the promptfoo CLI. Override with PROMPTFOO_BIN (space-separated) if you
// have a global install; defaults to `npx promptfoo` against this repo.
export function pf(args, { quiet = false } = {}) {
  const bin = process.env.PROMPTFOO_BIN
    ? process.env.PROMPTFOO_BIN.split(' ')
    : ['npx', 'promptfoo'];
  const res = spawnSync(bin[0], [...bin.slice(1), ...args], {
    cwd: REPO_ROOT,
    stdio: quiet ? ['ignore', 'ignore', 'inherit'] : 'inherit',
    env: { ...process.env, NODE_NO_WARNINGS: '1' },
  });
  if (res.status !== 0) {
    throw new Error(`promptfoo ${args.join(' ')} exited with ${res.status}`);
  }
}

export function ensureDir(p) {
  fs.mkdirSync(p, { recursive: true });
}

export function readJSON(p) {
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}

export function writeJSON(p, obj) {
  ensureDir(path.dirname(p));
  fs.writeFileSync(p, JSON.stringify(obj, null, 2) + '\n');
}

// Copy one blob (and its .meta.json sidecar) between two blob roots, skipping
// files that already exist (blobs are immutable / content-addressed).
// Returns the number of payload files newly copied (0 or 1).
export function copyBlob(srcRoot, dstRoot, hash) {
  const src = shard(srcRoot, hash);
  const dst = shard(dstRoot, hash);
  let copied = 0;
  if (fs.existsSync(src) && !fs.existsSync(dst)) {
    ensureDir(path.dirname(dst));
    fs.copyFileSync(src, dst);
    copied = 1;
  }
  const srcMeta = src + '.meta.json';
  const dstMeta = dst + '.meta.json';
  if (fs.existsSync(srcMeta) && !fs.existsSync(dstMeta)) {
    ensureDir(path.dirname(dstMeta));
    fs.copyFileSync(srcMeta, dstMeta);
  }
  return copied;
}
