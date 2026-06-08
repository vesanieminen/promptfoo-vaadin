"""Smoke assertion: does Claude's TOKEN auth path work under an isolated config dir?

This forces the strictest auth condition — an ISOLATED CLAUDE_CONFIG_DIR. On macOS a
non-default CLAUDE_CONFIG_DIR does NOT read the Keychain login, so the `claude` here
must authenticate from CLAUDE_CODE_OAUTH_TOKEN (injected run-scoped by run.sh).

The basic_layout rubric verifier USED to run exactly like this (the old
grade_rubric.py subprocess). It no longer does: the verifier is now a promptfoo
provider that reads the Keychain login or an env token, so a token is OPTIONAL for
the benchmark (see docs/ADR-verifier-as-provider.md). This check is kept as a
defensive test of the token path itself — relevant for API-key / token billing or a
login-less CI box. It reproduces the isolated-config context with a trivial prompt
and reports whether token auth succeeded.
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
        hint = ("No token in the environment. Run `claude setup-token` "
                "(interactive), copy the printed sk-ant-oat01-... value into "
                "basic_layout/.bench-token, then run `bash smoke/run.sh`."
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
