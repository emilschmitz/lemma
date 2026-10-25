# The prover image (lemma.toml [run] prover = "docker"): the pinned Verus release, the Rust toolchain it was built with, and a C linker,
# so Verus and the compile of every proved program run here instead of on the user's machine. Nothing is fetched at run time
# (scripts/ram/verus_guarded.sh starts it with --network none, a read-only root, the source files read-only and the output directory
# writable, under the verus_mem_max cap).
#
# Base: ubuntu:24.04 (glibc 2.39), the oldest Ubuntu the Verus release binary runs on (its `verus` needs GLIBC_2.39). Programs compiled
# here need the glibc of the symbols rustc's std links (2.34 for a binary/cdylib), so they run on the user's machine with glibc >= 2.34.
#
# Build: lemma setup (or docker build -t lemma-prover:0.2026.07.18.3a4d30b docker/prover). Every download is pinned by sha256.
FROM ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac

ARG VERUS_VERSION=0.2026.07.18.3a4d30b
ARG VERUS_SHA256=7097a91ea4bf5896a418d90743626cbe5c085ce5ef8a64ed8d84c0aa5e49ac55
ARG RUST_TOOLCHAIN=1.96.0-x86_64-unknown-linux-gnu
ARG RUSTUP_VERSION=1.29.2
ARG RUSTUP_SHA256=5be191e8c70a5007074254cb74d78dbfdd25cd5a61c27de7b8e5410122ec24f4

ENV RUSTUP_HOME=/opt/rustup CARGO_HOME=/opt/cargo
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends gcc libc6-dev ca-certificates curl unzip \
    && curl -fsSL -o /tmp/verus.zip "https://github.com/verus-lang/verus/releases/download/release/${VERUS_VERSION}/verus-${VERUS_VERSION}-x86-linux.zip" \
    && echo "${VERUS_SHA256}  /tmp/verus.zip" | sha256sum -c - \
    && unzip -q /tmp/verus.zip -d /tmp/verus && mv /tmp/verus/verus-x86-linux /opt/verus \
    && curl -fsSL -o /tmp/rustup-init "https://static.rust-lang.org/rustup/archive/${RUSTUP_VERSION}/x86_64-unknown-linux-gnu/rustup-init" \
    && echo "${RUSTUP_SHA256}  /tmp/rustup-init" | sha256sum -c - \
    && chmod +x /tmp/rustup-init \
    && /tmp/rustup-init -y --no-modify-path --profile minimal --default-toolchain "${RUST_TOOLCHAIN}" \
    && /opt/cargo/bin/rustup toolchain list | grep -q "${RUST_TOOLCHAIN}" \
    && rm -rf /tmp/verus.zip /tmp/verus /tmp/rustup-init /opt/rustup/downloads /opt/rustup/tmp \
    && apt-get purge -y curl unzip && apt-get autoremove -y && rm -rf /var/lib/apt/lists/* \
    && chmod -R a+rX /opt/verus /opt/rustup /opt/cargo

ENV PATH=/opt/verus:/opt/cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    RUSTUP_TOOLCHAIN=${RUST_TOOLCHAIN} \
    HOME=/tmp
# The version the CLI checks (lemma_cli/setup_cmd.py) and the guard's sanity check read this label.
LABEL org.lemma.verus_version=${VERUS_VERSION} org.lemma.rust_toolchain=${RUST_TOOLCHAIN}
RUN verus --version | grep -q "Version: ${VERUS_VERSION}"
ENTRYPOINT ["/opt/verus/verus"]
