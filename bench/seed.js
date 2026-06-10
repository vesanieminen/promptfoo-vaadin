// seed.js — promptfoo `beforeAll` extension hook for the agentic-dx bench (all problems)
// (PHASE 1: solve). Phase 2's grading-time prep lives in seed_verify.js.
//
// Replaces the seeding half of the old solve.sh. Before the eval runs, it
// (re)creates one fresh, writable workspace per solver provider, namespaced under
// the problem (workspaces/<problem>/<agent>, agents: codex, claude,
// claude-no-skills), from the agentic-dx-improvement sources:
//   - copies task.md + the reference PNGs and the Vaadin skeleton into app/,
//   - strips rubric.md so the solver never sees the grading criteria
//     (seed_verify.js restores it before phase 2),
//   - records the seeded reference PNGs in .reference-images.json so the graders
//     exclude them from screenshot galleries without hardcoding filenames,
//   - bakes a per-(problem,agent) server port (bench.portFor → 8081..8089) so rows
//     never collide on 8080 when run with --max-concurrency 3,
//   - writes workspaces/<problem>/available.json: an availability manifest
//     (agent-skills SHA + skill list + plugin-declared MCP servers) so each run
//     records what the skills/MCP SOURCE provided and its version (see writeManifest).
//
// The problem (PROBLEM env, default basic_layout) and the per-problem port/workspace
// layout come from bench.js, shared with promptfooconfig.js / verify.js.
//
// The old per-workspace .claude-home is gone: the rubric verifier is now a
// promptfoo PROVIDER (verify.js), not a subprocess, so it needs no isolated
// CLAUDE_CONFIG_DIR — see docs/ADR-verifier-as-provider.md.
//
// Wired in promptfooconfig.js as:  extensions: ['file://seed.js:seed']
// promptfoo invokes every extension for every hook using the legacy convention
// seed(hookName, context); we act only on beforeAll and return nothing.
//
// Source location is the sibling agentic-dx-improvement checkout by default;
// override with AGENTIC_DX_DIR.

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const bench = require('./bench.js'); // SOLVERS, portFor, workspaceRel, currentProblem

const HERE = __dirname; // promptfoo/bench (the bench dir)
const REPO_ROOT = path.dirname(HERE); // promptfoo
const AGENTIC_DX_DIR = process.env.AGENTIC_DX_DIR
  ? path.resolve(process.env.AGENTIC_DX_DIR)
  : path.resolve(REPO_ROOT, '..', 'agentic-dx-improvement');
const PROBLEM = bench.currentProblem(); // one of bench.PROBLEMS (env PROBLEM, default basic_layout)
const TECHSTACK = process.env.TECHSTACK || 'vaadin';

const PROBLEM_DIR = path.join(AGENTIC_DX_DIR, 'problems', PROBLEM);
const SKELETON_DIR = path.join(AGENTIC_DX_DIR, 'skeletons', TECHSTACK);
const BASE_PROMPT_FILE = path.join(AGENTIC_DX_DIR, 'problems', `base_prompt_${TECHSTACK}.md`);
// The agent-skills plugin's skills/ dir. The Claude provider loads agent-skills
// as a plugin; Codex has no plugin loader, so we install these skills into the
// Codex workspace's `.agents/skills/` (Codex's own discovery location) for parity.
const SKILLS_DIR = path.join(AGENTIC_DX_DIR, 'agent-skills', 'skills');
const AGENT_SKILLS_ROOT = path.join(AGENTIC_DX_DIR, 'agent-skills'); // plugin root: holds .mcp.json + .claude-plugin/plugin.json

// One workspace per solver provider, namespaced under the problem
// (workspaces/<problem>/<agent>) so all problems coexist on disk and in `promptfoo
// view`. Each gets a deterministic, collision-free port from bench.portFor. The
// matching provider `working_dir` (promptfooconfig.js) and the graders'
// provider->workspace map re-derive the SAME layout from PROBLEM + bench.js.
//   claude-no-skills is the BASELINE row: same agentic Claude solver, but WITHOUT
//   the Vaadin agent-skills plugin / docs MCP — it isolates how much the skills
//   actually move the rubric.
const SOLVERS = bench.SOLVERS;

// The cwd preamble run_task_local.sh prepends to the base prompt. prompt.txt is
// what the verifier reads as "the task"; the run-environment note lives only in
// the YAML prompt the solver receives.
const CWD_PREAMBLE =
  'The task description and any reference assets are in the current working directory.\n\n';

function rmrf(p) {
  fs.rmSync(p, { recursive: true, force: true });
}

// Skip build output and VCS/dependency noise when copying the skeleton.
const SKELETON_EXCLUDE = new Set(['target', '.git', 'node_modules']);

function seedWorkspace(agent, port) {
  const ws = path.join(HERE, bench.workspaceRel(PROBLEM, agent)); // workspaces/<problem>/<agent>
  rmrf(ws);
  fs.mkdirSync(ws, { recursive: true });

  // task.md + reference PNGs (+ rubric.md, which we strip below).
  fs.cpSync(PROBLEM_DIR, ws, { recursive: true });
  fs.rmSync(path.join(ws, 'rubric.md'), { force: true }); // solver must NOT see the rubric

  // Record the seeded reference images (the problem's wireframe PNGs) so the
  // graders can exclude exactly these from their "solver/verifier screenshots"
  // galleries WITHOUT hardcoding filenames per problem. Captured now, before any
  // solver runs, so it lists only seeded refs — never the agent's own captures.
  // (md_ui_spec ships no PNGs → an empty list, which is correct.)
  const refPngs = fs
    .readdirSync(ws)
    .filter((n) => n.toLowerCase().endsWith('.png'))
    .sort();
  fs.writeFileSync(path.join(ws, '.reference-images.json'), JSON.stringify(refPngs) + '\n');

  // The project the agent edits in place.
  const app = path.join(ws, 'app');
  fs.cpSync(SKELETON_DIR, app, {
    recursive: true,
    filter: (src) => !SKELETON_EXCLUDE.has(path.basename(src)),
  });

  // Bake the per-provider port so dev.sh/run.sh (and the verifier) bind it with
  // no PORT-env juggling; keep the ${PORT:...} form so PORT can still override.
  const propsPath = path.join(app, 'src/main/resources/application.properties');
  const props = fs
    .readFileSync(propsPath, 'utf8')
    .replace(/server\.port=\$\{PORT:\d+\}/, `server.port=\${PORT:${port}}`);
  fs.writeFileSync(propsPath, props);
  fs.writeFileSync(path.join(ws, '.run-port'), `${port}\n`);

  // prompt.txt: the task as the verifier reads it.
  fs.writeFileSync(
    path.join(ws, 'prompt.txt'),
    CWD_PREAMBLE + fs.readFileSync(BASE_PROMPT_FILE, 'utf8'),
  );

  // Codex has no plugin loader, so the agent-skills plugin can't deliver the
  // Vaadin skills the way it does for the Claude row. Install them into Codex's
  // own discovery location instead, for an apples-to-apples comparison.
  if (agent === 'codex') seedCodexSkills(ws);
}

// Point the Codex workspace's `.agents/skills/` at agent-skills' skills/ via a
// symlink. Codex discovers skills from `<workingDir>/.agents/skills/<name>/SKILL.md`
// (alongside $CODEX_HOME/skills and ~/.codex/skills); promptfoo recognises the
// same prefix, so their use is auto-counted into metadata.skillCalls (→ the
// `skill_calls` column). A symlink (vs a copy) means edits to the submodule are
// always reflected without re-seeding.
//   Caveat: skill_calls detection matches the `.agents/skills/<name>/SKILL.md`
//   path. If Codex canonicalises the symlink when it reports a tool command, the
//   reported path resolves outside `.agents/`, which would under-count
//   skill_calls — the skills still load and work, only the metric is affected.
//   Switch back to `fs.cpSync(SKILLS_DIR, dest, { recursive: true })` if so.
function seedCodexSkills(ws) {
  if (!fs.existsSync(SKILLS_DIR)) {
    console.error(
      `[seed] agent-skills skills/ not found at ${SKILLS_DIR} — ` +
        `Codex will solve WITHOUT the Vaadin skills (set AGENTIC_DX_DIR / update the submodule)`,
    );
    return;
  }
  const dest = path.join(ws, '.agents', 'skills');
  fs.mkdirSync(path.dirname(dest), { recursive: true }); // the `.agents` parent
  rmrf(dest); // workspace is fresh, but stay idempotent
  fs.symlinkSync(SKILLS_DIR, dest, 'dir'); // SKILLS_DIR is absolute
}

// ---------------------------------------------------------------------------
// Availability manifest — workspaces/<problem>/available.json records WHAT the
// skills/MCP SOURCE provided for this run, and its version. It exists because "available" was
// previously unrecorded: we discovered by hand that the agent-skills plugin's
// .mcp.json Vaadin server is NOT auto-loaded by the claude-agent-sdk provider (the
// skills load via `plugins:`, the MCP does not — it must be wired explicitly in
// promptfooconfig.js). The manifest makes the source inventory + submodule SHA
// auditable per run so that gap is visible up front.
//
// IMPORTANT: this is the SOURCE inventory, NOT per-agent wiring. Which MCP servers a
// provider actually exposes is in promptfooconfig.js; whether the agent actually
// CALLED them is in the run trace (the mcp_calls / skill_calls columns). And
// `reachable` is a best-effort endpoint ping from the seed host — "the endpoint
// answers", which is NOT the same as "the agent had it registered".
// ---------------------------------------------------------------------------
function gitSha(dir) {
  try {
    return execSync('git rev-parse HEAD', { cwd: dir, stdio: ['ignore', 'pipe', 'ignore'] })
      .toString()
      .trim();
  } catch {
    return null;
  }
}

function declaredSkills() {
  // Prefer the Claude plugin manifest's skills list; fall back to listing skills/.
  try {
    const m = JSON.parse(
      fs.readFileSync(path.join(AGENT_SKILLS_ROOT, '.claude-plugin', 'plugin.json'), 'utf8'),
    );
    if (Array.isArray(m.skills)) return m.skills.map((s) => path.basename(s)).sort();
  } catch {
    /* fall through to dir listing */
  }
  try {
    return fs
      .readdirSync(SKILLS_DIR)
      .filter((n) => fs.existsSync(path.join(SKILLS_DIR, n, 'SKILL.md')))
      .sort();
  } catch {
    return [];
  }
}

function pluginDeclaredMcp() {
  try {
    const m = JSON.parse(fs.readFileSync(path.join(AGENT_SKILLS_ROOT, '.mcp.json'), 'utf8'));
    return m.mcpServers || {};
  } catch {
    return {};
  }
}

async function reachable(url) {
  if (typeof fetch !== 'function' || !url) return null; // node < 18 (no global fetch): skip
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 5000);
  try {
    const res = await fetch(url, { method: 'GET', signal: ctrl.signal });
    return res.status < 500; // any non-5xx = the endpoint answered
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

async function writeManifest() {
  const declared = pluginDeclaredMcp();
  const mcp = {};
  for (const [name, cfg] of Object.entries(declared)) {
    mcp[name] =
      cfg && cfg.url
        ? { transport: 'http', url: cfg.url, reachable: await reachable(cfg.url) }
        : { transport: 'stdio' };
  }
  const manifest = {
    seededAt: new Date().toISOString(),
    problem: PROBLEM,
    techstack: TECHSTACK,
    agentSkills: {
      root: AGENT_SKILLS_ROOT,
      sha: gitSha(AGENT_SKILLS_ROOT),
      skills: declaredSkills(),
    },
    pluginDeclaredMcpServers: mcp,
    note:
      'Records the skills/MCP SOURCE (the agent-skills bundle) and its version for ' +
      'this run — NOT per-agent wiring. The claude-agent-sdk provider does NOT ' +
      'auto-load the plugin .mcp.json, so an MCP listed here is only actually ' +
      'available to an agent if promptfooconfig.js wires it explicitly. `reachable` ' +
      'is a seed-host endpoint ping, not proof the agent registered it. Actual ' +
      'per-agent usage is in the run trace (mcp_calls / skill_calls).',
  };
  const out = path.join(HERE, 'workspaces', PROBLEM, 'available.json');
  fs.writeFileSync(out, JSON.stringify(manifest, null, 2) + '\n');
  console.error(
    `[seed] availability manifest → ${out} ` +
      `(skills=${manifest.agentSkills.skills.length}, sha=${(manifest.agentSkills.sha || '?').slice(0, 8)}, ` +
      `declaredMcp=${Object.keys(mcp).join(',') || 'none'})`,
  );
}

module.exports.seed = async function seed(hookName /* , context */) {
  if (hookName !== 'beforeAll') return;

  for (const dir of [PROBLEM_DIR, SKELETON_DIR, BASE_PROMPT_FILE]) {
    if (!fs.existsSync(dir)) {
      throw new Error(
        `[seed] missing required source: ${dir}\n` +
          `Set AGENTIC_DX_DIR to your agentic-dx-improvement checkout ` +
          `(currently ${AGENTIC_DX_DIR}).`,
      );
    }
  }

  for (const agent of SOLVERS) {
    const port = bench.portFor(PROBLEM, agent);
    seedWorkspace(agent, port);
    console.error(`[seed] ${PROBLEM}/${agent}: workspace ready on port ${port}`);
  }

  await writeManifest();
};
