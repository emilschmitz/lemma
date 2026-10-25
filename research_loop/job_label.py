"""The generation job a pipeline run belongs to: DuckDB's ``lemma('<sql>')`` starts ``lemma generate`` with ``LEMMA_JOB_ID`` set, and
every container the run starts carries the label ``lemma.job=<id>``, so cancelling the job (Ctrl-C of a blocking ``lemma(...)``, or the
job's generator dying) removes them: ``docker ps -aq --filter label=lemma.job=<id> | xargs docker rm -f`` (the extension and the job
runner both do it). Outside a job: no label."""

from __future__ import annotations

import os

JOB_ENV = "LEMMA_JOB_ID"
LABEL = "lemma.job"


def job_label_args() -> list[str]:
    job = os.environ.get(JOB_ENV, "").strip()
    return ["--label", f"{LABEL}={job}"] if job else []
