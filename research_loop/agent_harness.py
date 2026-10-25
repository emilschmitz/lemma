"""Agent harnesses: which CLI runs the prover inside the sandbox container ([agent] harness in lemma.toml).

Every harness gets the same sandbox (``agent_sandbox.run_agent_docker``): ``--network none``, egress only to that vendor's API hosts through
the host allowlist bridge, the workspace and the commit's agent code mounted, the lemma-host MCP tools over the Unix socket. What differs per
harness is the image, the command, the MCP config file the entrypoint writes, the credential, and what the CLI's event stream reports.

Credentials (``agent_auth``) never switch silently and are never read here: ``api_key`` passes the harness's key variable to docker by NAME
(docker copies the value from this process's environment), ``login`` mounts that CLI's login file read-only. A missing credential raises.
"""

from __future__ import annotations

import json
import os
import shlex
from pathlib import Path

import lemma_config

HARNESSES = ("claude", "codex", "gemini")
IMAGES = lemma_config.LOCAL_AGENT_IMAGES  # the local research tags; image_for() applies [run] image_registry
# Default model per harness (written by `lemma setup --harness X` when no model is given). Sources, checked 2026-10-24:
#   claude: lemma.toml agent_model (the frozen run's model).
#   codex:  https://learn.chatgpt.com/docs/models  -- "gpt-6.1-sol" is the model recommended for complex coding and agentic work.
#   gemini: https://ai.google.dev/gemini-api/docs/models  -- "gemini-3.8-flash" is recommended for new projects (the CLI docs say it is not
#           optimized for the flagship gemini-4-argon yet: https://geminicli.com/docs/cli/model/).
DEFAULT_MODELS = {"claude": "claude-sonnet-5-5", "codex": "gpt-6.1-sol", "gemini": "gemini-3.8-flash"}
# The cheapest model of each vendor, for smoke prompts only (same sources): never a default for a proof run.
SMOKE_MODELS = {"claude": "claude-haiku-4-5-20251001", "codex": "gpt-6-luna", "gemini": "gemini-3.5-flash-lite"}
API_KEY_ENV = {"claude": "ANTHROPIC_API_KEY", "codex": "CODEX_API_KEY", "gemini": "GEMINI_API_KEY"}
# Every credential variable of every harness: a harness gets at most its own, and only in api_key mode.
SECRET_ENVS = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN", "CODEX_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")
EGRESS_PROFILES = {"claude": "anthropic", "codex": "openai", "gemini": "google"}
# A ChatGPT-plan Codex login talks to chatgpt.com (backend-api) as well as auth.openai.com; an API key needs only api.openai.com.
CODEX_LOGIN_EGRESS_PROFILE = "openai,chatgpt"
# The host the sandbox self-test must reach through the bridge.
API_HOSTS = {"claude": "api.anthropic.com", "codex": "api.openai.com", "gemini": "generativelanguage.googleapis.com"}
RAW_STREAMS = {"claude": "claude_raw.jsonl", "codex": "codex_raw.jsonl", "gemini": "gemini_raw.jsonl"}
LOGIN_COMMANDS = {"claude": "claude login", "codex": "codex login", "gemini": "gemini (choose 'Login with Google' once, interactively)"}
CONTAINER_LOGIN_DIRS = {"codex": "/root/.codex-host", "gemini": "/root/.gemini-host"}
COST_NOT_REPORTED = "not reported by harness"
# MCP tool calls (run_runquery = Verus + compile + timed run) may take minutes; the CLIs' defaults are 60 s (codex) and 10 min (gemini).
MCP_TOOL_TIMEOUT_SEC = 3600


def image_for(harness: str) -> str:
    """The sandbox image of ``harness``: ``IMAGES[harness]``, or the published ``<image_registry>/lemma-agent-<harness>:<version>`` when
    lemma.toml ``image_registry`` is set (lemma_config.agent_image)."""
    return lemma_config.agent_image(harness)


def selected_harness() -> str:
    return str(lemma_config.get("harness"))


def check_model(harness: str, model: str) -> None:
    """A model slug that belongs to another vendor than ``harness`` is a loud error, never a silent switch of harness."""
    if harness not in HARNESSES:
        raise ValueError(f"harness must be one of {HARNESSES}, got {harness!r}")
    if harness == "codex" and (model.startswith("claude-") or model.startswith("gemini-")):
        raise ValueError(f"harness codex cannot run model {model!r}: set agent_model to an OpenAI model (default {DEFAULT_MODELS['codex']})")
    if harness == "gemini" and not model.startswith("gemini-"):
        raise ValueError(f"harness gemini cannot run model {model!r}: set agent_model to a gemini-* model (default {DEFAULT_MODELS['gemini']})")


def harness_of_cmd(agent_cmd: str) -> str:
    """The harness an AGENT_CMD runs (its first word): claude, codex, gemini, or cursor (the legacy ``agent`` CLI)."""
    exe = agent_cmd.split(None, 1)[0] if agent_cmd.strip() else ""
    return exe if exe in HARNESSES else "cursor"


def codex_agent_cmd(model: str) -> str:
    """Headless Codex inside the container, prompt on stdin. Docker is the sandbox, so Codex's own (landlock/seccomp) sandbox and its approval
    prompts are off (``--dangerously-bypass-approvals-and-sandbox``: "intended solely for environments that are externally sandboxed").
    The JSONL event stream goes to stdout (the entrypoint tees it to ``agent_stream.jsonl``) and to ``logs/codex_raw.jsonl``."""
    return (
        f"codex exec --json --model {shlex.quote(model)} --skip-git-repo-check --dangerously-bypass-approvals-and-sandbox "
        "--cd /workspace - < PROMPT.txt "
        f"| tee -a /workspace/logs/{RAW_STREAMS['codex']}"
    )


def gemini_agent_cmd(model: str) -> str:
    """Headless Gemini CLI inside the container: the prompt file on stdin, ``-p`` appended to it (that is how ``-p`` combines with stdin).
    ``--approval-mode yolo`` runs the tools without prompts (Docker is the sandbox); ``--skip-trust`` trusts /workspace for this session."""
    return (
        f"gemini --model {shlex.quote(model)} --output-format stream-json --approval-mode yolo --skip-trust "
        "-p 'Do the task described above.' < PROMPT.txt "
        f"| tee -a /workspace/logs/{RAW_STREAMS['gemini']}"
    )


def agent_cmd_for(harness: str, model: str) -> str:
    check_model(harness, model)
    if harness == "codex":
        return codex_agent_cmd(model)
    if harness == "gemini":
        return gemini_agent_cmd(model)
    from research_loop.agent_sandbox import claude_agent_cmd

    return claude_agent_cmd(model)


def login_files(harness: str) -> list[tuple[Path, bool]]:
    """(host path, required) of the login files ``agent_auth = login`` mounts read-only for ``harness`` (codex, gemini)."""
    home = Path.home()
    if harness == "codex":
        return [(Path(os.environ.get("CODEX_HOME") or home / ".codex") / "auth.json", True)]
    if harness == "gemini":
        return [(home / ".gemini" / "oauth_creds.json", True), (home / ".gemini" / "google_accounts.json", False)]
    raise ValueError(f"no login files for harness {harness!r}")


def credential_status(harness: str, auth: str) -> str:
    """One line saying which credential the run will use; raises when it is missing. Values are never read."""
    if auth == "api_key":
        name = API_KEY_ENV[harness]
        if not os.environ.get(name, ""):
            raise RuntimeError(
                f"agent_auth = api_key and harness = {harness} but {name} is not set in the environment "
                f"(no fallback to the login: export {name} in your own shell, or use agent_auth = login)"
            )
        return f"{name} is set in the environment (passed to the container by name only)"
    if harness == "claude":
        from research_loop.agent_sandbox import claude_docker_args

        claude_docker_args()  # raises when there is no login
        return "Claude Code login found (mounted read-only into the container)"
    missing = [str(p) for p, required in login_files(harness) if required and not p.is_file()]
    if missing:
        raise RuntimeError(f"agent_auth = login and harness = {harness} but there is no login at {', '.join(missing)}: run `{LOGIN_COMMANDS[harness]}` "
                           f"in your own terminal, or export {API_KEY_ENV[harness]} and use agent_auth = api_key")
    return f"{harness} login found at {', '.join(str(p) for p, _ in login_files(harness) if p.is_file())} (mounted read-only into the container)"


def harness_docker_args(harness: str) -> list[str]:
    """Docker args for a codex or gemini container: the credential (by name, or a read-only login file) and the auth mode for the entrypoint.

    Every other harness's credential stays out (``run_agent_docker`` skips all of ``SECRET_ENVS`` from its env pass-through)."""
    if harness == "claude":
        from research_loop.agent_sandbox import claude_docker_args

        return claude_docker_args()
    auth = str(lemma_config.get("agent_auth"))
    credential_status(harness, auth)  # raises when missing
    args = ["-e", f"LEMMA_AGENT_AUTH={auth}", "-e", f"LEMMA_HARNESS={harness}"]
    if auth == "api_key":
        return args + ["-e", API_KEY_ENV[harness]]  # the name only: docker reads the value from this process's environment
    for path, _required in login_files(harness):
        if path.is_file():
            args += ["-v", f"{path.resolve()}:{CONTAINER_LOGIN_DIRS[harness]}/{path.name}:ro"]
    return args


def egress_profile(harness: str) -> str:
    if harness == "codex" and str(lemma_config.get("agent_auth")) == "login":
        return CODEX_LOGIN_EGRESS_PROFILE
    return EGRESS_PROFILES[harness]


# --- what the harness's event stream reports (the session loop records it; cost only Claude reports) ---


def _events(raw: Path) -> list[dict]:
    if not raw.is_file():
        return []
    out = []
    for line in raw.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a CLI may print a non-JSON line into the stream (warnings); it is not an event
    return out


def _is_end(harness: str, event: dict) -> bool:
    kind = event.get("type")
    if harness == "codex":
        return kind in ("turn.completed", "turn.failed")
    return kind == "result"


def result_count(harness: str, raw: Path) -> int:
    """Sessions in ``raw`` that ended by themselves (a codex turn end, a gemini result event)."""
    return sum(1 for e in _events(raw) if _is_end(harness, e))


def tokens(harness: str, raw: Path) -> dict[str, int]:
    """Token totals the harness reported. codex: the ``usage`` of every ``turn.completed``; gemini: ``stats`` of every ``result`` event."""
    total: dict[str, int] = {}
    for e in _events(raw):
        usage = None
        if harness == "codex" and e.get("type") == "turn.completed":
            usage = e.get("usage") or {}
        elif harness == "gemini" and e.get("type") == "result":
            usage = {k: v for k, v in (e.get("stats") or {}).items() if k.endswith("tokens") and isinstance(v, int)}
        for k, v in (usage or {}).items():
            if isinstance(v, int):
                total[k] = total.get(k, 0) + v
    return total


# Auth / connectivity failures as codex 0.162 and gemini-cli 0.63 word them (seen with a dummy key: codex "401 Unauthorized: Incorrect API key",
# gemini "API key not valid" / "API_KEY_INVALID").
API_ERROR_MARKERS = ("401", "403", "Unauthorized", "API key", "API_KEY_INVALID", "PERMISSION_DENIED", "UNAUTHENTICATED", "ERR_PROXY",
                     "stream disconnected", "error sending request", "fetch failed")


def api_error(harness: str, raw: Path, results_before: int) -> str | None:
    """``INFRA: agent API error: <text>`` when an error event after the first ``results_before`` session ends names an auth/connectivity
    failure (the session never reached the model), else None."""
    seen = 0
    for e in _events(raw):
        earlier = seen < results_before  # an event of an earlier session
        if _is_end(harness, e):
            seen += 1
        if earlier:
            continue
        # Only the final event of a session counts: codex retries a dropped stream itself ("Reconnecting... n/5" error events).
        kind = e.get("type")
        text = ""
        if harness == "codex" and kind == "turn.failed":
            text = str((e.get("error") or {}).get("message") or e)
        elif harness == "gemini" and kind == "result" and e.get("status") == "error":
            text = str(e.get("error") or e)
        if text and any(m in text for m in API_ERROR_MARKERS):
            return f"INFRA: agent API error: {text[:200]}"
    return None
