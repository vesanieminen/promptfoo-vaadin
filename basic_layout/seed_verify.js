// seed_verify.js — promptfoo `beforeAll` extension hook for verify.yaml (PHASE 2).
//
// Phase 1 (promptfooconfig.yaml) seeds the workspaces and runs the solvers,
// leaving each agent's solution in workspaces/<agent>/app. Phase 2 grades those
// solutions with the VERIFIER providers (anthropic:claude-agent-sdk, one per
// workspace). Before the verifiers run, this hook prepares each workspace:
//
//   1. Restore rubric.md into the workspace. seed.js STRIPS rubric.md so the
//      solver never sees the grading criteria; the verifier's prompt expects
//      `rubric.md` in its cwd, so we copy it back now (after the solve, before
//      the verify). This is why the restore lives here and not in seed.js.
//   2. Free the workspace's baked server port. The solver may have left a dev
//      server running on it; the verifier runs app/run.sh which must bind that
//      port. (Mirrors the old grade_rubric.py _free_port watchdog.)
//
// Wired in verify.yaml as:  extensions: ['file://seed_verify.js:seed']
// Source location is the sibling agentic-dx-improvement checkout by default;
// override with AGENTIC_DX_DIR.

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const HERE = __dirname; // promptfoo/basic_layout
const REPO_ROOT = path.dirname(HERE); // promptfoo
const AGENTIC_DX_DIR = process.env.AGENTIC_DX_DIR
  ? path.resolve(process.env.AGENTIC_DX_DIR)
  : path.resolve(REPO_ROOT, '..', 'agentic-dx-improvement');
const PROBLEM = process.env.PROBLEM || 'basic_layout';
const RUBRIC_SRC = path.join(AGENTIC_DX_DIR, 'problems', PROBLEM, 'rubric.md');

// Keep in sync with seed.js SOLVERS and the verify.yaml providers.
const WORKSPACES = ['codex', 'claude', 'claude-no-skills'];

function freePort(port) {
  if (!port) return;
  try {
    const out = execSync(`lsof -ti tcp:${port}`, {
      stdio: ['ignore', 'pipe', 'ignore'],
    })
      .toString()
      .trim();
    for (const pid of out.split(/\s+/).filter(Boolean)) {
      try {
        process.kill(Number(pid), 'SIGTERM');
      } catch {
        /* already gone */
      }
    }
  } catch {
    /* nothing bound to the port */
  }
}

function prepareWorkspace(agent) {
  const ws = path.join(HERE, 'workspaces', agent);
  if (!fs.existsSync(path.join(ws, 'app'))) {
    console.error(
      `[seed_verify] ${agent}: no workspaces/${agent}/app — did phase 1 ` +
        `(promptfooconfig.yaml) run and the solver produce a solution? ` +
        `Skipping; the verify-${agent} row will score 0.`,
    );
    return;
  }

  // Clear any stale verdict from a prior verify run. grade_verdict.py falls back to
  // verify-result.json on disk when the provider returns no structured output; if
  // THIS run's verifier also fails to rewrite it, a leftover file would be read as
  // this run's verdict. Within run.sh, phase-1 seed.js already wipes the workspace —
  // this also covers a standalone `eval -c verify.yaml` re-run against old workspaces.
  fs.rmSync(path.join(ws, 'verify-result.json'), { force: true });

  // Restore the rubric the solver never saw, into the verifier's cwd.
  if (fs.existsSync(RUBRIC_SRC)) {
    fs.copyFileSync(RUBRIC_SRC, path.join(ws, 'rubric.md'));
  } else {
    console.error(`[seed_verify] rubric source not found at ${RUBRIC_SRC} (set AGENTIC_DX_DIR)`);
  }

  // Free the baked port so the verifier's app/run.sh can bind it.
  let port = 0;
  try {
    port = parseInt(fs.readFileSync(path.join(ws, '.run-port'), 'utf8').trim(), 10);
  } catch {
    /* no .run-port — leave port handling to app/run.sh */
  }
  freePort(port);
  console.error(`[seed_verify] ${agent}: rubric restored, port ${port || '?'} cleared`);
}

module.exports.seed = async function seed(hookName /* , context */) {
  if (hookName !== 'beforeAll') return;
  for (const agent of WORKSPACES) prepareWorkspace(agent);
};
