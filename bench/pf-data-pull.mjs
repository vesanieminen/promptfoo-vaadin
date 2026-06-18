// Import the git-tracked dataset at bench/data/ INTO the local promptfoo store
// (~/.promptfoo) so `promptfoo view` shows every shared eval, screenshots included.
// Run after `git pull`. Idempotent — safe to re-run.
//
//   node bench/pf-data-pull.mjs
//
// Order matters and reflects promptfoo's own model:
//   - blob_assets is promptfoo's GLOBAL content store (deliberately omitted from
//     per-eval exports), so we insert those rows ourselves — BEFORE importing,
//     so the foreign key from blob_references is satisfiable.
//   - blob_references travel INSIDE the eval JSON, so `promptfoo import` inserts
//     them itself. We must NOT replay them or images get double-attached.
// Steps: init schema -> copy blob files -> insert assets -> import evals.

import fs from 'node:fs';
import path from 'node:path';
import {
  openDb, pf, ensureDir, readJSON,
  EVALS_DIR, INDEX_DIR, REPO_BLOBS, LOCAL_BLOBS, CONFIG_DIR,
} from './pf-data-common.mjs';

ensureDir(CONFIG_DIR);
ensureDir(LOCAL_BLOBS);

// 1. Copy blob payload files into the local store. .meta.json carries an
//    absolute `key` that points at the original machine — rewrite it to here.
function copyBlobsIn(srcDir, dstDir) {
  let files = 0, metas = 0;
  const walk = (dir) => {
    for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
      const src = path.join(dir, ent.name);
      if (ent.isDirectory()) { walk(src); continue; }
      const rel = path.relative(srcDir, src);
      const dst = path.join(dstDir, rel);
      ensureDir(path.dirname(dst));
      if (ent.name.endsWith('.meta.json')) {
        const meta = readJSON(src);
        meta.key = dst.replace(/\.meta\.json$/, '');
        fs.writeFileSync(dst, JSON.stringify(meta, null, 2));
        metas++;
      } else if (!fs.existsSync(dst)) {
        fs.copyFileSync(src, dst);
        files++;
      }
    }
  };
  if (fs.existsSync(srcDir)) walk(srcDir);
  return { files, metas };
}

const blobStats = copyBlobsIn(REPO_BLOBS, LOCAL_BLOBS);

// 2. Ensure the DB exists and is migrated (a fresh store has no schema yet).
//    `list evals` opens the DB, which runs promptfoo's migrations.
pf(['list', 'evals', '-n', '1'], { quiet: true });

// 3. Insert blob_assets (the global content store) so blob_references FKs hold.
const db = openDb(false);
const insAsset = db.prepare(
  `INSERT OR IGNORE INTO blob_assets (hash, size_bytes, mime_type, provider, created_at)
   VALUES (?, ?, ?, ?, ?)`,
);
let assets = 0;
if (fs.existsSync(INDEX_DIR)) {
  for (const f of fs.readdirSync(INDEX_DIR).filter((n) => n.endsWith('.json'))) {
    for (const a of readJSON(path.join(INDEX_DIR, f)).assets ?? []) {
      assets += insAsset.run(a.hash, a.size_bytes, a.mime_type, a.provider, a.created_at).changes;
    }
  }
}
db.close();

// 4. Import each eval JSON (preserve ID, replace if present -> idempotent).
//    promptfoo inserts the eval's own blob_references; the FK now resolves.
let imported = 0;
if (fs.existsSync(EVALS_DIR)) {
  for (const f of fs.readdirSync(EVALS_DIR).filter((n) => n.endsWith('.json')).sort()) {
    pf(['import', path.join(EVALS_DIR, f), '--force'], { quiet: true });
    imported++;
  }
}

console.log(
  `pulled: ${imported} eval(s) imported, ${blobStats.files} blob file(s) + ` +
  `${blobStats.metas} meta(s) installed, ${assets} asset row(s) added.`,
);
console.log('Next: promptfoo view');
