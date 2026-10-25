"""A stand-in for the `docker` command in the lemma() cancel test: `run -d --label K=V ...` records a container, `ps -aq --filter label=K=V`
lists the matching ones, `rm -f ID...` removes them (printing each id, as docker does). State and a log of every call: $FAKE_DOCKER_STATE."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path


def main() -> int:
    state = Path(os.environ["FAKE_DOCKER_STATE"])
    (state / "containers").mkdir(parents=True, exist_ok=True)
    args = sys.argv[1:]
    with (state / "calls.log").open("a") as log:
        log.write(" ".join(args) + "\n")
    if args[:1] == ["run"]:
        label = args[args.index("--label") + 1] if "--label" in args else ""
        cid = uuid.uuid4().hex[:12]
        (state / "containers" / cid).write_text(label)
        print(cid)
    elif args[:1] == ["ps"]:
        want = args[args.index("--filter") + 1].removeprefix("label=")
        for c in sorted((state / "containers").iterdir()):
            if c.read_text() == want:
                print(c.name)
    elif args[:2] == ["rm", "-f"]:
        for cid in args[2:]:
            (state / "containers" / cid).unlink(missing_ok=True)
            print(cid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
