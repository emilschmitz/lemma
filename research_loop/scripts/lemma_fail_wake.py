#!/usr/bin/env python3
"""Laptop fail-wake: emit AGENT_LOOP_WAKE_* when overnight records a new fail or abort.

Polls VM (if RUNNING) then local harvest / GCS. Prints one sentinel line per new
lemma_ok=false qid and on aborted.json. Cursor must run this with notify_on_output.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

FAMILY = os.environ.get("LEMMA_LIVE_FAMILY", "r28rocket")
SENTINEL = os.environ.get("LEMMA_WAKE_SENTINEL", f"AGENT_LOOP_WAKE_{FAMILY}")
ZONE = os.environ.get("LEMMA_GCE_ZONE", "us-east1-c")
INSTANCE = os.environ.get("LEMMA_GCE_INSTANCE", "lemma-gendb-overnight")
VM_OUT = os.environ.get(
    "LEMMA_VM_OUT", f"/home/emil/lemma-overnight-out-{FAMILY}"
)
LOCAL = Path(os.environ.get("LEMMA_HARVEST_LOCAL", f"/home/emil/lemma-harvest/{FAMILY}"))
GS = os.environ.get(
    "LEMMA_HARVEST_GS", f"gs://poema-496023-lemma-harvest/{FAMILY}/"
)
STATE = Path(
    os.environ.get(
        "LEMMA_WAKE_STATE",
        f"/home/emil/lemma-harvest/watch/fail_wake_{FAMILY}.state.json",
    )
)
POLL_SEC = int(os.environ.get("LEMMA_WAKE_POLL_SEC", "20"))
LEASE_SEC = int(os.environ.get("LEMMA_LAPTOP_LEASE_SEC", "720"))
TICK_SEC = int(os.environ.get("LEMMA_TICK_SEC", "300"))
GCLOUD = os.environ.get("GCLOUD", str(Path.home() / "google-cloud-sdk/bin/gcloud"))


def emit(payload: dict) -> None:
    line = SENTINEL + " " + json.dumps(payload, default=str)
    print(line, flush=True)
    # Cursor notify_on_output has not been injecting idle turns; ntfy is the backup ping.
    topic = os.environ.get("LEMMA_NTFY_TOPIC", "lemma-update")
    title = f"{payload.get('kind', 'wake')} {payload.get('family', FAMILY)} {payload.get('qid', '')}".strip()
    body = str(payload.get("prompt") or line)[:400]
    subprocess.run(
        [
            "curl",
            "-sS",
            "-H",
            f"Title: {title}",
            "-d",
            body,
            f"https://ntfy.sh/{topic}",
        ],
        check=False,
        timeout=15,
        capture_output=True,
        text=True,
    )


def load_state() -> dict:
    if STATE.is_file():
        try:
            return json.loads(STATE.read_text())
        except json.JSONDecodeError:
            pass
    return {"seen_fails": [], "seen_abort": False, "smoke_done": False}


def save_state(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=2) + "\n")


def run(cmd: list[str], timeout: int = 45) -> tuple[int, str]:
    try:
        p = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except FileNotFoundError as e:
        return 127, str(e)


def vm_status() -> str:
    rc, out = run(
        [
            GCLOUD,
            "compute",
            "instances",
            "describe",
            INSTANCE,
            f"--zone={ZONE}",
            "--format=get(status)",
        ],
        timeout=30,
    )
    if rc != 0:
        return "UNKNOWN"
    return (out.strip().splitlines() or ["UNKNOWN"])[-1].strip() or "UNKNOWN"


def vm_cat(rel: str) -> str | None:
    remote = f"{VM_OUT}/{rel}"
    rc, out = run(
        [
            GCLOUD,
            "compute",
            "ssh",
            INSTANCE,
            f"--zone={ZONE}",
            "--strict-host-key-checking=no",
            "--command",
            f"sudo -u emil cat {remote} 2>/dev/null || true",
        ],
        timeout=60,
    )
    if rc != 0:
        return None
    return out


def parse_progress(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def fails_from_progress(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        ok = r.get("ok")
        if ok is False or ok == "false":
            out.append(r)
    return out


def prompt_for_fail(rec: dict, *, abort: bool = False) -> str:
    qid = rec.get("qid", "?")
    kind = "ABORT" if abort else "FAIL"
    return (
        f"{kind} wake {FAMILY} qid={qid} ok={rec.get('ok')} "
        f"proof={rec.get('proof')} lat={rec.get('latency_us')}. "
        "Pull traces. Reason+Response table (step N, blame, smarter-agent). "
        "If host: fix, commit, push, retry ONLY the failed qids "
        "(LEMMA_SQL_ONLY=1, new family, retry.json). Do not re-run greens. "
        "Start a fresh shuffle only after that retry exits 0. "
        "If agent too stupid: record, do not water down. One VM. Never sloppy."
    )


def refresh_lease() -> bool:
    """Touch the guest lease. False if the VM is up but the touch failed."""
    status = vm_status()
    if status != "RUNNING":
        return True
    remote = f"{VM_OUT}/laptop_lease"
    rc, _out = run(
        [
            GCLOUD,
            "compute",
            "ssh",
            INSTANCE,
            f"--zone={ZONE}",
            "--strict-host-key-checking=no",
            "--command",
            f"sudo -u emil touch {remote}",
        ],
        timeout=40,
    )
    return rc == 0


def stop_vm(reason: str) -> None:
    print(f"# laptop backstop stop: {reason}", flush=True)
    run(
        [
            GCLOUD,
            "compute",
            "instances",
            "stop",
            INSTANCE,
            f"--zone={ZONE}",
        ],
        timeout=120,
    )


def collect() -> tuple[list[dict], bool, str]:
    """Return (fail rows, aborted, source)."""
    status = vm_status()
    aborted = False
    rows: list[dict] = []
    source = f"vm_status={status}"

    if status == "RUNNING":
        prog = vm_cat("progress.ndjson") or ""
        rows = parse_progress(prog)
        ab = vm_cat("aborted.json") or ""
        aborted = bool(ab.strip().startswith("{"))
        source = "vm"
        if rows or aborted:
            return rows, aborted, source

    local_prog = LOCAL / "progress.ndjson"
    if local_prog.is_file():
        rows = parse_progress(local_prog.read_text(encoding="utf-8", errors="replace"))
        source = "local"
    local_ab = LOCAL / "aborted.json"
    if local_ab.is_file():
        aborted = True

    if not rows:
        rc, out = run(["gsutil", "cat", f"{GS}progress.ndjson"], timeout=40)
        if rc == 0 and out.strip():
            rows = parse_progress(out)
            source = "gcs"
        rc2, out2 = run(["gsutil", "cat", f"{GS}aborted.json"], timeout=40)
        if rc2 == 0 and out2.strip().startswith("{"):
            aborted = True
            source = "gcs"

    return rows, aborted, source


def main() -> int:
    st = load_state()
    seen = set(st.get("seen_fails") or [])
    if not st.get("smoke_done"):
        emit(
            {
                "kind": "smoke",
                "family": FAMILY,
                "prompt": (
                    "SMOKE: fail-wake watcher started and notify fired. "
                    "This proves a box fail can ping this session. Continue the "
                    "paper-grade goal (harvest, fix/retest, fresh SEC+Immanuel+TPC-H)."
                ),
            }
        )
        st["smoke_done"] = True
        save_state(st)

    last_tick = 0.0
    lease_fail_since: float | None = None
    while True:
        try:
            now = time.time()
            if refresh_lease():
                lease_fail_since = None
            else:
                lease_fail_since = lease_fail_since or now
                if now - lease_fail_since >= LEASE_SEC:
                    stop_vm(f"lease refresh failed for {int(now - lease_fail_since)}s")
                    lease_fail_since = now
            if now - last_tick >= TICK_SEC:
                last_tick = now
                status = vm_status()
                print(
                    f"AGENT_LOOP_TICK_lemma family={FAMILY} vm={status} "
                    f"instance={INSTANCE} zone={ZONE}",
                    flush=True,
                )
            rows, aborted, source = collect()
            new_fails = []
            for rec in fails_from_progress(rows):
                qid = str(rec.get("qid") or "")
                if not qid or qid in seen:
                    continue
                seen.add(qid)
                new_fails.append(rec)
            if new_fails:
                st["seen_fails"] = sorted(seen)
                save_state(st)
                for rec in new_fails:
                    emit(
                        {
                            "kind": "fail",
                            "family": FAMILY,
                            "source": source,
                            "qid": rec.get("qid"),
                            "ok": rec.get("ok"),
                            "proof": rec.get("proof"),
                            "latency_us": rec.get("latency_us"),
                            "prompt": prompt_for_fail(rec),
                        }
                    )
            if aborted and not st.get("seen_abort"):
                st["seen_abort"] = True
                save_state(st)
                emit(
                    {
                        "kind": "abort",
                        "family": FAMILY,
                        "source": source,
                        "prompt": prompt_for_fail(
                            {"qid": "ABORT", "ok": False}, abort=True
                        ),
                    }
                )
        except Exception as e:
            print(f"# fail_wake error: {e}", flush=True)
        time.sleep(POLL_SEC)
    return 0


if __name__ == "__main__":
    sys.exit(main())
