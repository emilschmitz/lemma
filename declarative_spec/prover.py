"""Where Verus (and the rustc build of every proved program) runs, and where the spec emitter reads the Verus source from.

lemma.toml ``[run] prover``:
  * ``host``   Verus at ``[prover] verus_home`` (default ``~/tools/verus``) with the rustup toolchain it was built with, on this machine.
  * ``docker`` the pinned image ``[prover] prover_image`` (docker/prover/Dockerfile: the same Verus release, its toolchain, a linker), run by
               scripts/ram/verus_guarded.sh with no network, a read-only root, the source files read-only and the output directory writable.
               The vstd / builtin source the emitter reads (vstd_index, schema_types, the agent's docs) is copied once out of that image into
               ``~/.cache/lemma/prover/<image tag>/``, so the spec is emitted from exactly the vstd the image proves with.

Both run the same Verus release (the image checks ``verus --version`` at build time and its zip's sha256 is pinned), so the same program
gives the same ``N verified, M errors`` either way. Stdlib + lemma_config only.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import lemma_config

# What the emitter and the CLI read from a Verus install (never the binaries in docker mode).
SOURCE_PARTS = ("vstd", "builtin", "version.txt", "version.json")
IMAGE_VERUS_HOME = "/opt/verus"


def mode() -> str:
    return str(lemma_config.get("prover"))


def image() -> str:
    """The prover image: ``[prover] prover_image``, under ``[run] image_registry`` when one is set (lemma_config.prover_image)."""
    return lemma_config.prover_image()


def host_verus_home() -> Path:
    """``[prover] verus_home`` with ``~`` expanded: the host install (prover = host)."""
    return Path(os.path.expanduser(str(lemma_config.get("verus_home"))))


def image_source_dir(tag: str | None = None) -> Path:
    tag = image() if tag is None else tag
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return cache / "lemma" / "prover" / re.sub(r"[^A-Za-z0-9_.-]", "_", tag)


def extract_image_source(tag: str | None = None) -> Path:
    """Copy ``SOURCE_PARTS`` of the image's Verus into ``image_source_dir`` (once; staged, then renamed). Fails loudly when the image is
    missing: ``lemma setup`` builds it."""
    tag = image() if tag is None else tag
    dest = image_source_dir(tag)
    if (dest / "version.json").is_file():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    created = subprocess.run(["docker", "create", tag], capture_output=True, text=True, check=False)
    if created.returncode != 0:
        raise RuntimeError(f"prover = docker but the prover image {tag} is not available ({created.stderr.strip()[-300:]}): run `lemma setup`")
    cid = created.stdout.strip()
    stage = Path(tempfile.mkdtemp(prefix=".extract-", dir=dest.parent))
    try:
        for part in SOURCE_PARTS:
            subprocess.run(["docker", "cp", "-q", f"{cid}:{IMAGE_VERUS_HOME}/{part}", str(stage / part)], capture_output=True, text=True, check=True)
        shutil.rmtree(dest, ignore_errors=True)
        stage.rename(dest)
    finally:
        subprocess.run(["docker", "rm", cid], capture_output=True, check=False)
        shutil.rmtree(stage, ignore_errors=True)
    return dest


def verus_home() -> Path:
    """The Verus tree the emitter reads vstd / builtin source and the version from: the host install, or the image's copy."""
    return host_verus_home() if mode() == "host" else extract_image_source()
