"""Host-only workspace artifacts (raw column data, timing bar) are invisible inside the agent container."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from research_loop.agent_sandbox import CLAUDE_IMAGE, docker_image_built
from research_loop.sandbox_hide import HOST_ONLY_DIRS, shadow_mount_args
from tests.test_claude_sandbox import _captured_docker_cmd


def test_launcher_docker_args_shadow_every_host_only_dir_after_the_workspace_mount(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cmd = _captured_docker_cmd(monkeypatch, tmp_path, mock=False)
    ws_mount = cmd.index(f"{tmp_path / 'ws'}:/workspace:rw")
    for rel in HOST_ONLY_DIRS:
        i = next(i for i, a in enumerate(cmd) if a.startswith(f"type=tmpfs,destination=/workspace/{rel},"))
        assert cmd[i - 1] == "--mount" and i > ws_mount  # a nested mount only shadows if it comes after
        assert "readonly" in cmd[i]
    assert (tmp_path / "ws" / "decl_data").is_dir()  # created by the host user, not by docker as root


def test_shadow_args_cover_each_hidden_dir_and_create_the_host_mountpoint(tmp_path: Path) -> None:
    args = shadow_mount_args(tmp_path)
    assert args.count("--mount") == len(HOST_ONLY_DIRS)
    for rel in HOST_ONLY_DIRS:
        assert (tmp_path / rel).is_dir()
        assert any(a.startswith(f"type=tmpfs,destination=/workspace/{rel},") for a in args)


@pytest.mark.skipif(not docker_image_built(CLAUDE_IMAGE), reason="lemma-agent:claude image not built")
def test_real_docker_hides_host_only_dir_and_keeps_editable_file_and_context(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    (ws / "context" / "ro").mkdir(parents=True)
    (ws / "decl_data").mkdir()
    (ws / "decl_data" / "bar.json").write_text("SECRET-BAR")
    (ws / "decl_data" / "cols_num.bin").write_bytes(b"RAWDATA")
    (ws / "context" / "ro" / "query.sql").write_text("select 1\n")
    (ws / "runquery_agent.rs").write_text("old")
    ro = ws / "context" / "ro"
    script = (
        "ls -A /workspace/decl_data | wc -l; "
        "cat /workspace/decl_data/bar.json 2>&1 | grep -c SECRET; "
        "touch /workspace/decl_data/x 2>&1 | grep -c -i 'read-only\\|denied'; "
        "cat /workspace/context/ro/query.sql; cat /context/ro/query.sql; "
        "echo new > /workspace/runquery_agent.rs && cat /workspace/runquery_agent.rs; "
        "grep -rl 'SECRET-BAR\\|RAWDATA' /workspace 2>/dev/null | wc -l"
    )
    cmd = [
        "docker", "run", "--rm", "--network", "none", "--cap-drop", "ALL", "--cap-add", "DAC_OVERRIDE",
        "-v", f"{ws}:/workspace:rw", *shadow_mount_args(ws),
        "-v", f"{ro}:/workspace/context/ro:ro", "-v", f"{ro}:/context/ro:ro",
        "--entrypoint", "/bin/bash", CLAUDE_IMAGE, "-c", script,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.split()
    assert out == ["0", "0", "1", "select", "1", "select", "1", "new", "0"]
    # The host still sees the real files: nothing was moved or removed.
    assert (ws / "decl_data" / "bar.json").read_text() == "SECRET-BAR"
    assert (ws / "runquery_agent.rs").read_text().strip() == "new"


# --- the host-side routes: the body is compiled and run on the host, and the MCP `path` argument ---


@pytest.mark.parametrize(
    "body",
    [
        'let b = include_bytes!("../decl_data/cols_num.bin");',
        'let s = std::fs::read("/x");',
        'let v = std::env::var("LEMMA_MEASURE_DB");',
        'let b = include_str!("../decl_data/expect.json");',
        "unsafe { }",
        'core::arch::asm!("nop");',
    ],
)
def test_admission_rejects_host_access_in_the_body(body: str) -> None:
    from declarative_spec.admit import admit_declarative_body

    res = admit_declarative_body(body)
    assert not res.ok and any("host access" in v or "unsafe" in v for v in res.violations)


def test_admission_still_accepts_plain_compute() -> None:
    from declarative_spec.admit import admit_declarative_body

    assert admit_declarative_body("let mut i: usize = 0; while i < n { i = i + 1; }").ok


def test_mcp_path_into_host_only_dir_is_refused_even_through_a_symlink(tmp_path: Path) -> None:
    from db_extension.agent.measure_core import _resolve_under_workspace

    ws = tmp_path.resolve()
    (ws / "decl_data").mkdir()
    (ws / "decl_data" / "cols_num.bin").write_bytes(b"\xff")
    (ws / "link.rs").symlink_to("decl_data/cols_num.bin")
    (ws / "ok.rs").write_text("x")
    for p in ("decl_data/cols_num.bin", "link.rs"):
        with pytest.raises(PermissionError):
            _resolve_under_workspace(p, ws)
    assert _resolve_under_workspace("ok.rs", ws) == ws / "ok.rs"
