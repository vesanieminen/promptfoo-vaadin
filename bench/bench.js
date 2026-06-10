// bench.js — single source of truth for the multi-problem agentic-dx benchmark.
//
// Imported by BOTH the promptfoo configs (promptfooconfig.js, verify.js) and the
// seed hooks (seed.js, seed_verify.js) so the problem list, the solver/agent list,
// the per-(problem,agent) port assignment, and the workspace path layout are
// defined in exactly ONE place. Keep the Python graders (grade_static.py,
// grade_verdict.py) in sync with PROBLEMS / SOLVERS / the workspace layout — they
// re-derive the same paths from PROBLEM (env) + the provider label.
//
// Adding a 4th problem is a drop-in: append its name to PROBLEMS, drop a
// problems/<name>/ (task.md + rubric.md [+ PNGs]) into the agentic-dx-improvement
// checkout, and add checks/<name>.py. Ports and workspace dirs follow automatically.

const path = require('path');

// Canonical problem order. Port offsets derive from a problem's INDEX here, so the
// order is load-bearing: appending keeps existing problems' ports stable.
const PROBLEMS = ['basic_layout', 'basic_form', 'md_ui_spec'];

// Solver providers (= workspace names), in port order within a problem. `claude`
// and `claude-no-skills` are the skills A/B; codex is the cross-agent comparison.
const SOLVERS = ['codex', 'claude', 'claude-no-skills'];

// First port (basic_layout/codex). Each problem reserves SOLVERS.length consecutive
// ports, so the three problems occupy 8081..8089 and never collide — even if two
// problems' rows were somehow run concurrently.
const PORT_BASE = 8081;

function problemIndex(problem) {
  const i = PROBLEMS.indexOf(problem);
  if (i < 0) throw new Error(`[bench] unknown PROBLEM '${problem}' (known: ${PROBLEMS.join(', ')})`);
  return i;
}

// Deterministic, collision-free port for a (problem, agent) pair.
function portFor(problem, agent) {
  const a = SOLVERS.indexOf(agent);
  if (a < 0) throw new Error(`[bench] unknown agent '${agent}' (known: ${SOLVERS.join(', ')})`);
  return PORT_BASE + problemIndex(problem) * SOLVERS.length + a;
}

// workspaces/<problem>/<agent>, RELATIVE to the bench dir. Used verbatim as a
// promptfoo provider `working_dir` (promptfoo resolves it against the config dir)
// and joined under __dirname in the seed hooks.
function workspaceRel(problem, agent) {
  return path.posix.join('workspaces', problem, agent);
}

// The problem this invocation is for. run.sh sets PROBLEM per problem; default
// keeps a bare `eval -c promptfooconfig.js` working as the original basic_layout run.
function currentProblem() {
  const p = process.env.PROBLEM || 'basic_layout';
  problemIndex(p); // validate (throws on typo) before the config is handed to promptfoo
  return p;
}

module.exports = {
  PROBLEMS,
  SOLVERS,
  PORT_BASE,
  problemIndex,
  portFor,
  workspaceRel,
  currentProblem,
};
