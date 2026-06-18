// Export the local promptfoo store (~/.promptfoo) INTO the git-tracked dataset
// at bench/data/. Run this after an eval run, then `git add bench/data && commit`.
//
//   node bench/pf-data-push.mjs            # REPORT-SCOPED (default): the dataset
//                                          #   mirrors exactly the eval IDs cited
//                                          #   in docs/ reports — exports the
//                                          #   referenced evals and PRUNES the rest.
//   node bench/pf-data-push.mjs --all      # export every local eval, prune nothing
//   node bench/pf-data-push.mjs <id> ...   # export only the given eval id(s), no prune
//
// Per-eval files mean two people exporting different runs never conflict.

import fs from 'node:fs';
import path from 'node:path';
import {
  openDb, pf, ensureDir, writeJSON, copyBlob, safeName, readJSON,
  EVALS_DIR, INDEX_DIR, REPO_BLOBS, LOCAL_BLOBS, REPO_ROOT,
} from './pf-data-common.mjs';

const argv = process.argv.slice(2);
const all = argv.includes('--all');
const onlyIds = argv.filter((a) => !a.startsWith('--'));

// Scan the reports for eval IDs. The dataset is meant to hold exactly the evals
// the reports reference, so this is the default keep-set.
const REPORTS_DIR = path.join(REPO_ROOT, 'docs');
function scanReportEvalIds() {
  const re = /eval-[A-Za-z0-9_-]{3}-\d{4}-\d{2}-\d{2}T\d{2}[:_]\d{2}[:_]\d{2}/g;
  const ids = new Set();
  const walk = (dir) => {
    for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, ent.name);
      if (ent.isDirectory()) { walk(p); continue; }
      if (!/\.(html?|md|json|txt)$/i.test(ent.name)) continue;
      const text = fs.readFileSync(p, 'utf8');
      for (const m of text.match(re) ?? []) {
        // normalise the time separators back to the DB's colon form
        ids.add(m.replace(/T(\d{2})[:_](\d{2})[:_](\d{2})/, 'T$1:$2:$3'));
      }
    }
  };
  if (fs.existsSync(REPORTS_DIR)) walk(REPORTS_DIR);
  return ids;
}

ensureDir(EVALS_DIR);
ensureDir(INDEX_DIR);
ensureDir(REPO_BLOBS);

const db = openDb(true);
const existsInDb = (id) => !!db.prepare('SELECT 1 FROM evals WHERE id = ?').get(id);

// Decide which evals to export, and whether to prune to that set.
let ids, prune;
if (onlyIds.length) {
  ids = onlyIds;
  prune = false;
} else if (all) {
  ids = db.prepare('SELECT id FROM evals ORDER BY created_at').all().map((r) => r.id);
  prune = false;
} else {
  const referenced = [...scanReportEvalIds()];
  const missing = referenced.filter((id) => !existsInDb(id));
  if (missing.length) {
    console.warn(`warning: ${missing.length} eval(s) referenced in reports are not in your local store and will be skipped:`);
    for (const id of missing) console.warn(`  ${id}`);
  }
  ids = referenced.filter(existsInDb);
  prune = true;
}

let exported = 0, skipped = 0, indexed = 0, blobsCopied = 0;

for (const id of ids) {
  const safe = safeName(id);
  const out = path.join(EVALS_DIR, safe + '.json');

  if (!all && onlyIds.length === 0 && fs.existsSync(out)) {
    skipped++;
  } else {
    pf(['export', 'eval', id, '-o', out], { quiet: true });
    exported++;
  }

  // Blob sidecar: references for this eval + the assets they point at.
  const refs = db.prepare('SELECT * FROM blob_references WHERE eval_id = ?').all(id);
  if (refs.length) {
    const hashes = [...new Set(refs.map((r) => r.blob_hash))];
    const assets = hashes
      .map((h) => db.prepare('SELECT * FROM blob_assets WHERE hash = ?').get(h))
      .filter(Boolean);
    writeJSON(path.join(INDEX_DIR, safe + '.json'), { eval_id: id, references: refs, assets });
    indexed++;
    for (const h of hashes) blobsCopied += copyBlob(LOCAL_BLOBS, REPO_BLOBS, h);
  }
}

db.close();

// In report-scoped mode, drop dataset files no longer referenced, and any blob
// they were the last user of — so the dataset stays in sync with the reports.
let prunedE = 0, prunedI = 0, prunedB = 0;
if (prune) {
  const keep = new Set(ids.map((id) => safeName(id) + '.json'));
  for (const f of fs.readdirSync(EVALS_DIR)) {
    if (f.endsWith('.json') && !keep.has(f)) { fs.rmSync(path.join(EVALS_DIR, f)); prunedE++; }
  }
  for (const f of fs.readdirSync(INDEX_DIR)) {
    if (f.endsWith('.json') && !keep.has(f)) { fs.rmSync(path.join(INDEX_DIR, f)); prunedI++; }
  }
  // Blobs still needed = union of asset hashes across surviving index files.
  const needed = new Set();
  for (const f of fs.readdirSync(INDEX_DIR)) {
    if (!f.endsWith('.json')) continue;
    for (const a of readJSON(path.join(INDEX_DIR, f)).assets ?? []) needed.add(a.hash);
  }
  const walkBlobs = (dir) => {
    for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, ent.name);
      if (ent.isDirectory()) { walkBlobs(p); if (fs.readdirSync(p).length === 0) fs.rmdirSync(p); continue; }
      const hash = ent.name.replace(/\.meta\.json$/, '');
      if (!needed.has(hash)) { fs.rmSync(p); if (!ent.name.endsWith('.meta.json')) prunedB++; }
    }
  };
  if (fs.existsSync(REPO_BLOBS)) walkBlobs(REPO_BLOBS);
}

console.log(
  `pushed: ${exported} eval(s) exported, ${skipped} unchanged, ` +
  `${indexed} with blobs, ${blobsCopied} new blob file(s) copied` +
  (prune ? `; pruned ${prunedE} eval(s), ${prunedI} index file(s), ${prunedB} blob(s) no longer in reports` : '') +
  '.',
);
console.log('Next: git add bench/data && git commit');
