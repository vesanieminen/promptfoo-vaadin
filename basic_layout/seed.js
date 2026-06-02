// seed.js — promptfoo `beforeAll` extension hook for the basic_layout eval.
//
// Replaces the seeding half of the old solve.sh and all of claude-home.sh.
// Before the eval runs, it (re)creates one fresh, writable workspace per solver
// provider (codex, claude) from the agentic-dx-improvement sources:
//   - copies task.md + the reference PNGs and the Vaadin skeleton into app/,
//   - strips rubric.md so the solver never sees the grading criteria,
//   - bakes a per-provider server port so the two rows never collide on 8080
//     when run with --max-concurrency 2,
//   - builds an isolated Claude config dir for that workspace's rubric verifier
//     (Playwright MCP made --isolated so parallel verifiers don't deadlock).
//
// Wired in promptfooconfig.yaml as:  extensions: ['file://seed.js:seed']
// promptfoo invokes every extension for every hook using the legacy convention
// seed(hookName, context); we act only on beforeAll and return nothing.
//
// Source location is the sibling agentic-dx-improvement checkout by default;
// override with AGENTIC_DX_DIR (and BENCH_CLAUDE_HOME for the Claude home).

const fs = require('fs');
const path = require('path');

const HERE = __dirname; // promptfoo/basic_layout
const REPO_ROOT = path.dirname(HERE); // promptfoo
const AGENTIC_DX_DIR = process.env.AGENTIC_DX_DIR
  ? path.resolve(process.env.AGENTIC_DX_DIR)
  : path.resolve(REPO_ROOT, '..', 'agentic-dx-improvement');
const PROBLEM = process.env.PROBLEM || 'basic_layout';
const TECHSTACK = process.env.TECHSTACK || 'vaadin';
const BENCH_CLAUDE_HOME =
  process.env.BENCH_CLAUDE_HOME || path.join(AGENTIC_DX_DIR, '.bench-claude-home');

const PROBLEM_DIR = path.join(AGENTIC_DX_DIR, 'problems', PROBLEM);
const SKELETON_DIR = path.join(AGENTIC_DX_DIR, 'skeletons', TECHSTACK);
const BASE_PROMPT_FILE = path.join(AGENTIC_DX_DIR, 'problems', `base_prompt_${TECHSTACK}.md`);
// The agent-skills plugin's skills/ dir. The Claude provider loads agent-skills
// as a plugin; Codex has no plugin loader, so we install these skills into the
// Codex workspace's `.agents/skills/` (Codex's own discovery location) for parity.
const SKILLS_DIR = path.join(AGENTIC_DX_DIR, 'agent-skills', 'skills');

// One workspace per solver provider, each on a dedicated port. The matching
// provider `working_dir` and the graders' provider->workspace map use the same
// names; keep them in sync with promptfooconfig.yaml.
const SOLVERS = { codex: 8081, claude: 8082 };

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
  const ws = path.join(HERE, 'workspaces', agent);
  rmrf(ws);
  fs.mkdirSync(ws, { recursive: true });

  // task.md + reference PNGs (+ rubric.md, which we strip below).
  fs.cpSync(PROBLEM_DIR, ws, { recursive: true });
  fs.rmSync(path.join(ws, 'rubric.md'), { force: true }); // solver must NOT see the rubric

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

  // Isolated Claude home for THIS workspace's rubric verifier (needed for BOTH
  // rows — the verifier is always Claude, even when grading Codex's solution).
  buildClaudeHome(ws);

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

// Mirrors the old claude-home.sh: copy the bench home (Vaadin plugin + base
// config) and rewrite the Playwright MCP to an in-memory (--isolated) profile
// with a per-workspace output dir, so concurrent verifiers can't deadlock on a
// shared browser profile's singleton lock.
function buildClaudeHome(ws) {
  const dest = path.join(ws, '.claude-home');
  rmrf(dest);
  fs.mkdirSync(dest, { recursive: true });
  if (fs.existsSync(BENCH_CLAUDE_HOME)) {
    fs.cpSync(BENCH_CLAUDE_HOME, dest, { recursive: true });
  } else {
    console.error(
      `[seed] bench Claude home not found at ${BENCH_CLAUDE_HOME} (set BENCH_CLAUDE_HOME)`,
    );
  }
  const cfgPath = path.join(dest, '.claude.json');
  let cfg = {};
  try {
    if (fs.existsSync(cfgPath)) cfg = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
  } catch {
    cfg = {};
  }
  if (!cfg || typeof cfg !== 'object') cfg = {};
  cfg.mcpServers = cfg.mcpServers || {};
  cfg.mcpServers.playwright = {
    type: 'stdio',
    command: 'npx',
    args: [
      '--yes',
      '@playwright/mcp@latest',
      '--browser',
      'chromium',
      '--headless',
      '--isolated',
      '--output-dir',
      path.join(ws, '.pw-verify'),
    ],
    env: {},
  };
  fs.writeFileSync(cfgPath, JSON.stringify(cfg, null, 2));
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

  for (const [agent, port] of Object.entries(SOLVERS)) {
    seedWorkspace(agent, port);
    console.error(`[seed] ${agent}: workspace ready on port ${port}`);
  }
};
