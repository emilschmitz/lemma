"""Host HTTPS CONNECT proxy with hostname allowlist (Cursor-in-Docker egress).

Sandbox stays ``--network none``. Sidecar exposes ``HTTP(S)_PROXY`` on localhost;
only allowlisted hosts (default: Cursor API) are dialed from the host.

This is what you want for Cursor CLI: mount ``~/.cursor``, talk to Cursor's API,
but block general web fetches at the network layer (curl google.com fails).
"""
from __future__ import annotations

import argparse
import json
import os
import select
import socket
import threading
import time
from pathlib import Path

DEFAULT_SOCK = Path(os.environ.get("LEMMA_EGRESS_SOCK", "/tmp/lemma-egress.sock"))

# Best-effort vendor API hosts.
# Cursor list mined from local install:
#   ~/.local/share/cursor-agent/versions/*/  (strings/URLs in cursor-agent JS)
# Staging hosts omitted; add via LEMMA_EGRESS_ALLOWLIST if needed.
VENDOR_ALLOWLISTS: dict[str, tuple[str, ...]] = {
    "cursor": (
        # Core product / auth pages
        "cursor.com",
        "www.cursor.com",
        "origin.cursor.com",
        # Agent / backend APIs (suffix match: *.cursor.sh)
        "cursor.sh",
        "api2.cursor.sh",
        "api2direct.cursor.sh",
        "api3.cursor.sh",
        "api5.cursor.sh",
        "repo42.cursor.sh",
        # Telemetry used by the CLI (deny breaks nothing critical for inference, but
        # the binary references these; keep so agent startup is quiet)
        "api.statsigcdn.com",
        "statsigapi.net",
        # Optional update blob; keep so version checks do not spuriously fail
        "cursor.blob.core.windows.net",
    ),
    "anthropic": (
        "anthropic.com",
        "api.anthropic.com",
    ),
    "openai": (
        "openai.com",
        "api.openai.com",
        "auth.openai.com",
    ),
    "openrouter": (
        "openrouter.ai",
        "api.openrouter.ai",
    ),
    "google": (
        "googleapis.com",
        "generativelanguage.googleapis.com",
    ),
}

DEFAULT_ALLOWLIST = VENDOR_ALLOWLISTS["cursor"]


def allowlist_for_profile(profile: str) -> tuple[str, ...]:
    """Resolve AGENT_EGRESS_PROFILE (comma-separated vendor names) to host suffixes."""
    names = [p.strip().lower() for p in profile.replace(";", ",").split(",") if p.strip()]
    if not names:
        return DEFAULT_ALLOWLIST
    out: list[str] = []
    seen: set[str] = set()
    for name in names:
        alias = {"claude": "anthropic", "codex": "openai", "agy": "google"}.get(name, name)
        hosts = VENDOR_ALLOWLISTS.get(alias)
        if hosts is None:
            continue
        for h in hosts:
            if h not in seen:
                seen.add(h)
                out.append(h)
    return tuple(out) if out else DEFAULT_ALLOWLIST


def infer_egress_profile(agent_cmd: str, explicit: str | None = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    # The executable decides the vendor; a model slug like claude-sonnet-5 in an
    # ``agent`` command must not select the anthropic profile.
    cmd = agent_cmd.lower()
    exe = cmd.split(None, 1)[0]
    if exe == "claude":
        return "anthropic"
    if exe == "codex":
        return "openai"
    if exe in ("agy", "gemini"):
        return "google"
    if "openrouter" in cmd:
        return "openrouter"
    # Default Cursor `agent` CLI
    return "cursor"


def _parse_allowlist(raw: str | None, *, profile: str | None = None) -> tuple[str, ...]:
    if raw and raw.strip():
        parts = [p.strip().lower().lstrip(".") for p in raw.replace(";", ",").split(",")]
        return tuple(p for p in parts if p)
    if profile:
        return allowlist_for_profile(profile)
    return DEFAULT_ALLOWLIST


def host_allowed(hostname: str, allowlist: tuple[str, ...]) -> bool:
    host = hostname.lower().rstrip(".")
    for entry in allowlist:
        if host == entry or host.endswith("." + entry):
            return True
    return False


class EgressBridge:
    """Minimal HTTP proxy: CONNECT + plain HTTP, allowlisted Host only."""

    def __init__(
        self,
        sock_path: Path,
        allowlist: tuple[str, ...] = DEFAULT_ALLOWLIST,
        log_path: Path | None = None,
    ) -> None:
        self.sock_path = sock_path
        self.allowlist = allowlist
        self.log_path = log_path
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._server: socket.socket | None = None
        self._lock = threading.Lock()

    def _log(self, record: dict) -> None:
        record = dict(record)
        record.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        line = json.dumps(record, ensure_ascii=False)
        # Always surface denials on stderr (host process running the bridge).
        if record.get("denied"):
            print(f"[egress-denied] {line}", flush=True, file=__import__("sys").stderr)
        if self.log_path is None:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            # Mirror denials into a dedicated file for easy grepping.
            if record.get("denied"):
                denied_path = self.log_path.with_name("egress_denied.jsonl")
                with open(denied_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")

    def start(self) -> threading.Thread:
        if self.sock_path.exists():
            self.sock_path.unlink()
        self.sock_path.parent.mkdir(parents=True, exist_ok=True)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(self.sock_path))
        srv.listen(32)
        srv.settimeout(0.5)
        self._server = srv
        self._thread = threading.Thread(target=self._serve, daemon=True, name="egress-bridge")
        self._thread.start()
        return self._thread

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2)
        try:
            self.sock_path.unlink()
        except FileNotFoundError:
            pass

    def _serve(self) -> None:
        assert self._server is not None
        while not self._stop.is_set():
            try:
                conn, _ = self._server.accept()
            except (TimeoutError, OSError):
                continue
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        t0 = time.perf_counter()
        remote: socket.socket | None = None
        try:
            conn.settimeout(60)
            data = b""
            while b"\r\n\r\n" not in data and len(data) < 65536:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            if not data:
                return
            header_blob, _, rest = data.partition(b"\r\n\r\n")
            lines = header_blob.decode("iso-8859-1", errors="replace").split("\r\n")
            req_line = lines[0]
            parts = req_line.split()
            if len(parts) < 2:
                conn.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
                return
            method, target = parts[0].upper(), parts[1]
            if method == "CONNECT":
                hostport = target
                host, _, port_s = hostport.partition(":")
                port = int(port_s or "443")
                if not host_allowed(host, self.allowlist):
                    self._log(
                        {
                            "ok": False,
                            "method": "CONNECT",
                            "host": host,
                            "denied": True,
                            "latency_ms": (time.perf_counter() - t0) * 1000,
                        }
                    )
                    conn.sendall(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
                    return
                remote = socket.create_connection((host, port), timeout=30)
                conn.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                self._log(
                    {
                        "ok": True,
                        "method": "CONNECT",
                        "host": host,
                        "port": port,
                        "latency_ms": (time.perf_counter() - t0) * 1000,
                    }
                )
                _relay(conn, remote)
                return

            # Plain HTTP proxy: absolute-form URL
            # GET http://host/path HTTP/1.1
            if target.startswith("http://"):
                without = target[len("http://") :]
                host_path = without
                hostport, _, path = host_path.partition("/")
                path = "/" + path if path or path == "" else "/"
                if not path.startswith("/"):
                    path = "/" + path
                host, _, port_s = hostport.partition(":")
                port = int(port_s or "80")
                if not host_allowed(host, self.allowlist):
                    self._log(
                        {
                            "ok": False,
                            "method": method,
                            "host": host,
                            "denied": True,
                            "latency_ms": (time.perf_counter() - t0) * 1000,
                        }
                    )
                    conn.sendall(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
                    return
                remote = socket.create_connection((host, port), timeout=30)
                new_req = f"{method} {path} HTTP/1.1\r\n"
                # rebuild headers, force Host
                hdrs = []
                for line in lines[1:]:
                    if not line or line.lower().startswith("proxy-"):
                        continue
                    if line.lower().startswith("host:"):
                        continue
                    hdrs.append(line)
                hdrs.insert(0, f"Host: {hostport}")
                payload = (new_req + "\r\n".join(hdrs) + "\r\n\r\n").encode("iso-8859-1") + rest
                remote.sendall(payload)
                self._log(
                    {
                        "ok": True,
                        "method": method,
                        "host": host,
                        "latency_ms": (time.perf_counter() - t0) * 1000,
                    }
                )
                _relay(conn, remote)
                return

            conn.sendall(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
        except Exception as exc:
            self._log(
                {
                    "ok": False,
                    "error": str(exc),
                    "latency_ms": (time.perf_counter() - t0) * 1000,
                }
            )
            try:
                conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            except OSError:
                pass
        finally:
            try:
                conn.close()
            except OSError:
                pass
            if remote is not None:
                try:
                    remote.close()
                except OSError:
                    pass


def _relay(a: socket.socket, b: socket.socket) -> None:
    sockets = [a, b]
    try:
        while True:
            r, _, _ = select.select(sockets, [], [], 60)
            if not r:
                break
            for s in r:
                other = b if s is a else a
                data = s.recv(65536)
                if not data:
                    return
                other.sendall(data)
    except OSError:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Lemma allowlist egress bridge (UDS)")
    parser.add_argument("--sock", type=Path, default=DEFAULT_SOCK)
    parser.add_argument(
        "--allowlist",
        default=os.environ.get("LEMMA_EGRESS_ALLOWLIST", ""),
        help="Comma-separated host suffixes (overrides profile)",
    )
    parser.add_argument(
        "--profile",
        default=os.environ.get("AGENT_EGRESS_PROFILE", "cursor"),
        help="Vendor profile: cursor, anthropic, openai, openrouter, google (comma-ok)",
    )
    parser.add_argument("--log", type=Path, default=None)
    args = parser.parse_args()
    log = args.log
    if log is None:
        ws = os.environ.get("LEMMA_AGENT_WORKSPACE", "").strip()
        if ws:
            log = Path(ws) / "mcp_results" / "egress_bridge.jsonl"
    allow = _parse_allowlist(args.allowlist, profile=args.profile)
    bridge = EgressBridge(args.sock, allow, log)
    print(f"egress bridge on uds://{args.sock} allow={bridge.allowlist}", flush=True)
    bridge.start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        bridge.stop()


if __name__ == "__main__":
    main()
