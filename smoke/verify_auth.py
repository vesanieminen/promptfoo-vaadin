"""Smoke assertion: does the agentic VERIFIER's auth path work?

The real rubric verifier (basic_layout/grade_rubric.py) runs `claude` with an
ISOLATED CLAUDE_CONFIG_DIR. On macOS a non-default CLAUDE_CONFIG_DIR does NOT read
the Keychain login, so the verifier needs CLAUDE_CODE_OAUTH_TOKEN (injected
run-scoped by run.sh). This reproduces that exact context with a trivial prompt
and reports whether the isolated-config `claude` authenticated.
"""
import os
import shutil
import subprocess
import tempfile

EXPECT = "VERIFIER_OK"


def get_assert(output, context=None):
    home = tempfile.mkdtemp(prefix="smoke-claude-home-")
    env = dict(os.environ)
    env["CLAUDE_CONFIG_DIR"] = home  # isolated — exactly like the real verifier
    try:
        proc = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "-p",
             "Reply with exactly this and nothing else: " + EXPECT],
            cwd=home, env=env, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=120,
        )
        out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    except Exception as e:
        return {"pass": False, "score": 0.0,
                "reason": "verifier `claude` did not run: %r" % e}
    finally:
        shutil.rmtree(home, ignore_errors=True)

    low = out.lower()
    token_set = bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"))

    if "not logged in" in low or "please run /login" in low:
        hint = ("No token in the environment. Provide one run-scoped: "
                "`claude setup-token > basic_layout/.bench-token`, then run via "
                "`bash smoke/run.sh`."
                if not token_set else
                "A CLAUDE_CODE_OAUTH_TOKEN is set but was rejected — it may be "
                "expired/invalid; re-mint with `claude setup-token`.")
        return {"pass": False, "score": 0.0,
                "reason": "VERIFICATION auth FAILED — the isolated CLAUDE_CONFIG_DIR "
                          "is not authenticated. " + hint + " | claude: " + out[:200]}

    if EXPECT in out:
        return {"pass": True, "score": 1.0,
                "reason": "VERIFICATION auth OK — isolated-config `claude` "
                          "authenticated (token %s) and replied %s." %
                          ("present" if token_set else "absent", EXPECT)}

    return {"pass": False, "score": 0.0,
            "reason": "VERIFICATION `claude` ran but produced unexpected output: "
                      + out[:200]}
