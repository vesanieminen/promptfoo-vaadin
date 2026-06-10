"""Smoke assertion: does Claude auth work for the path the benchmark will actually use?

The benchmark authenticates one of two ways, and this checks whichever is in play:

- LOGIN mode (no CLAUDE_CODE_OAUTH_TOKEN — the default after this PR): the solver and
  the provider-based verifier both read your Claude Code login from the DEFAULT config
  dir (macOS Keychain). This runs a trivial `claude -p` under that same default config
  and asserts it authenticates — NOT the obsolete isolated-CLAUDE_CONFIG_DIR path the
  old grade_rubric.py subprocess used (that can't read the Keychain, so it would always
  fail without a token). See docs/ADR-verifier-as-provider.md.
- TOKEN mode (CLAUDE_CODE_OAUTH_TOKEN set — run.sh's token / API-key billing, or a
  login-less CI box): runs the same probe under an ISOLATED CLAUDE_CONFIG_DIR (the
  strictest path, with no Keychain) and asserts the token authenticates it.

Either way a green row means Claude auth works the way you're about to run the
benchmark: token set → assert the token path; no token → assert the login path.
"""
import os
import shutil
import subprocess
import tempfile

EXPECT = "VERIFIER_OK"


def _probe_claude(isolated):
    """Run a trivial headless `claude -p` and return its combined stdout+stderr.

    isolated=True forces a fresh CLAUDE_CONFIG_DIR (no Keychain → needs a token);
    isolated=False uses your default config dir (the Keychain login path). A scratch
    cwd keeps it clear of any project-level .claude config either way.
    """
    scratch = tempfile.mkdtemp(prefix="smoke-claude-")
    env = dict(os.environ)
    if isolated:
        env["CLAUDE_CONFIG_DIR"] = scratch
    try:
        proc = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "-p",
             "Reply with exactly this and nothing else: " + EXPECT],
            cwd=scratch, env=env, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=120,
        )
        return ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def get_assert(output, context=None):
    token_set = bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"))
    mode = "token / isolated config" if token_set else "login / default config (Keychain)"

    try:
        out = _probe_claude(isolated=token_set)
    except Exception as e:
        return {"pass": False, "score": 0.0,
                "reason": "auth probe `claude` did not run [%s]: %r" % (mode, e)}

    low = out.lower()
    if "not logged in" in low or "please run /login" in low:
        hint = ("CLAUDE_CODE_OAUTH_TOKEN is set but was rejected under an isolated "
                "config dir — it may be expired/invalid; re-mint with "
                "`claude setup-token`." if token_set else
                "Not logged in to Claude Code. Run `claude /login` — or use token "
                "mode (export CLAUDE_CODE_OAUTH_TOKEN, or put a token in "
                "bench/.bench-token and run via bash smoke/run.sh).")
        return {"pass": False, "score": 0.0,
                "reason": "VERIFICATION auth FAILED [%s] — %s | claude: %s"
                          % (mode, hint, out[:200])}

    if EXPECT in out:
        return {"pass": True, "score": 1.0,
                "reason": "VERIFICATION auth OK [%s] — `claude` authenticated and "
                          "replied %s (the path the benchmark's verifier uses)."
                          % (mode, EXPECT)}

    return {"pass": False, "score": 0.0,
            "reason": "VERIFICATION `claude` ran but produced unexpected output "
                      "[%s]: %s" % (mode, out[:200])}
