#!/usr/bin/env node
// attach_shots.js — POST-RUN screenshot attach for the agentic-dx bench.
// NO LLM. No provider. No eval re-run. No grader change.
//
// After PHASE 1 (solve), each solver's Playwright screenshots already sit in its
// workspace ROOT (workspaces/<problem>/<agent>/*.png — the Playwright MCP server's
// cwd IS the workspace, so browser_take_screenshot with a bare filename lands there).
// This script adds those PNGs, AS-IS, to that solver's row in the promptfoo results
// so they render as clickable images (with the lightbox) in `promptfoo view`.
//
// It only does two purely-additive things, both AFTER the eval is already written:
//   1. copies each PNG into promptfoo's content-addressed media store
//      (~/.promptfoo/blobs/<h0h1>/<h2h3>/<sha256>  +  .meta.json), and
//   2. sets response.images + blob_references on the already-stored eval_results row,
//      using the SAME representation promptfoo's native providers emit (a blobRef —
//      verified against a real provider-produced eval). The image bytes never go
//      through SQL; only tiny blobRef/ref rows do.
// It does NOT touch the solver/verifier providers, the prompt, or grade_static.py.
//
// Reference wireframes (listed in each workspace's .reference-images.json, written by
// seed.js) are EXCLUDED — only the agent's own captures are attached. Same filter
// grade_static.py uses for its solver-screenshots.html gallery.
//
// Idempotent: re-running replaces a row's image refs rather than duplicating them.
//
// Usage (bench/run.sh calls it after PHASE 1; also runnable by hand / to backfill an
// older run whose workspaces still exist):
//   PROBLEM=basic_form node bench/attach_shots.js                 # newest SOLVE eval for PROBLEM
//   PROBLEM=basic_form node bench/attach_shots.js eval-uut-2026-… # a specific eval id
//
// Honours PROMPTFOO_CONFIG_DIR (defaults to ~/.promptfoo), matching promptfoo.

const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');
const { execFileSync } = require('child_process');
const bench = require('./bench.js'); // SOLVERS, workspaceRel, currentProblem

const HERE = __dirname; // promptfoo/bench
const PROBLEM = bench.currentProblem(); // env PROBLEM (default basic_layout); throws on a typo
const CONFIG_DIR = process.env.PROMPTFOO_CONFIG_DIR
  ? path.resolve(process.env.PROMPTFOO_CONFIG_DIR)
  : path.join(os.homedir(), '.promptfoo');
const DB = path.join(CONFIG_DIR, 'promptfoo.db');
const BLOBS = path.join(CONFIG_DIR, 'blobs');

function die(msg) {
  console.error(`[attach_shots] ${msg}`);
  process.exit(1);
}

// --- sqlite3 CLI helpers (the binary is already a project dependency in practice) --
function sqliteJson(query) {
  const out = execFileSync('sqlite3', ['-json', DB, query], { encoding: 'utf8' });
  return out.trim() ? JSON.parse(out) : [];
}
function sqliteExec(script) {
  // One transaction; image bytes are NOT in here, only small rows / JSON.
  execFileSync('sqlite3', [DB], { input: `BEGIN;\n${script}\nCOMMIT;\n`, encoding: 'utf8' });
}
const q = (s) => `'${String(s).replace(/'/g, "''")}'`; // single-quote a SQL string literal

// --- resolve the eval to attach to ---------------------------------------------
function resolveEvalId() {
  const explicit = process.argv[2];
  if (explicit) return explicit;
  // The PHASE-1 solve eval's description (promptfooconfig.js):
  //   "agentic-dx <problem> — Codex vs Claude solve the Vaadin task, …"
  const like = `agentic-dx ${PROBLEM} — Codex vs Claude%`;
  const rows = sqliteJson(
    `SELECT id FROM evals WHERE description LIKE ${q(like)} ORDER BY created_at DESC LIMIT 1;`,
  );
  if (!rows.length) die(`no SOLVE eval found for PROBLEM=${PROBLEM} (description LIKE ${JSON.stringify(like)}); pass an eval id explicitly.`);
  return rows[0].id;
}

// --- media store: write bytes the way promptfoo does, return a blobRef ----------
function storeBlob(buf) {
  const hash = crypto.createHash('sha256').update(buf).digest('hex');
  const dir = path.join(BLOBS, hash.slice(0, 2), hash.slice(2, 4));
  const file = path.join(dir, hash);
  if (!fs.existsSync(file)) {
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(file, buf);
    fs.writeFileSync(
      `${file}.meta.json`,
      JSON.stringify(
        { mimeType: 'image/png', sizeBytes: buf.length, createdAt: new Date().toISOString(), provider: 'filesystem', key: file },
        null,
        2,
      ) + '\n',
    );
  }
  return { hash, sizeBytes: buf.length };
}

function attachAgent(evalId, agent) {
  const ws = path.join(HERE, bench.workspaceRel(PROBLEM, agent));
  if (!fs.existsSync(ws)) return { agent, status: 'no-workspace' };

  let refs = [];
  try {
    refs = JSON.parse(fs.readFileSync(path.join(ws, '.reference-images.json'), 'utf8'));
  } catch {
    /* none recorded → exclude nothing */
  }
  const pngs = fs
    .readdirSync(ws)
    .filter((n) => n.toLowerCase().endsWith('.png') && !refs.includes(n))
    .sort();
  if (!pngs.length) return { agent, status: 'no-shots' };

  const rows = sqliteJson(
    `SELECT id, test_idx, prompt_idx FROM eval_results
       WHERE eval_id=${q(evalId)} AND json_extract(provider,'$.label')=${q(agent)};`,
  );
  if (!rows.length) return { agent, status: 'no-row', shots: pngs.length };
  const row = rows[0];

  const images = [];
  const stmts = [
    // idempotent: clear any image refs we previously attached to this row
    `DELETE FROM blob_references WHERE eval_id=${q(evalId)} AND test_idx=${row.test_idx}
       AND prompt_idx=${row.prompt_idx} AND kind='image' AND location LIKE 'response.images%';`,
  ];
  pngs.forEach((name, i) => {
    const { hash, sizeBytes } = storeBlob(fs.readFileSync(path.join(ws, name)));
    stmts.push(
      `INSERT OR IGNORE INTO blob_assets (hash, size_bytes, mime_type, provider) VALUES (${q(hash)}, ${sizeBytes}, 'image/png', 'filesystem');`,
    );
    stmts.push(
      `INSERT INTO blob_references (id, blob_hash, eval_id, test_idx, prompt_idx, location, kind)
         VALUES (${q(crypto.randomUUID())}, ${q(hash)}, ${q(evalId)}, ${row.test_idx}, ${row.prompt_idx}, ${q(`response.images[${i}].data`)}, 'image');`,
    );
    images.push({
      mimeType: 'image/png',
      blobRef: { uri: `promptfoo://blob/${hash}`, hash, mimeType: 'image/png', sizeBytes, provider: 'filesystem' },
    });
  });
  // Set response.images (tiny JSON — blobRefs only, no base64). Leaves the rest of
  // the response (output, cost, tokenUsage, metadata.toolCalls, …) untouched.
  stmts.push(
    `UPDATE eval_results SET response = json_set(response, '$.images', json(${q(JSON.stringify(images))})) WHERE id=${q(row.id)};`,
  );
  sqliteExec(stmts.join('\n'));
  return { agent, status: 'attached', shots: pngs.length, names: pngs };
}

function main() {
  if (!fs.existsSync(DB)) die(`promptfoo DB not found at ${DB} (set PROMPTFOO_CONFIG_DIR?)`);
  const evalId = resolveEvalId();
  console.error(`[attach_shots] PROBLEM=${PROBLEM} eval=${evalId}`);
  let total = 0;
  for (const agent of bench.SOLVERS) {
    const r = attachAgent(evalId, agent);
    if (r.status === 'attached') {
      total += r.shots;
      console.error(`[attach_shots]   ${agent}: attached ${r.shots} screenshot(s) → ${r.names.join(', ')}`);
    } else {
      console.error(`[attach_shots]   ${agent}: ${r.status}${r.shots ? ` (${r.shots} shot(s) on disk)` : ''}`);
    }
  }
  console.error(`[attach_shots] done — ${total} screenshot(s) attached. View: npx promptfoo@latest view`);
}

main();
