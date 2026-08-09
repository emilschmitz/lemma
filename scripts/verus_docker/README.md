# Verus in Docker (with linker)

Remote Spot runs Verus inside Docker so the host stays minimal. A bare `ubuntu:24.04`
image has no C linker, so `verus --compile` fails with `linker cc not found`. This
image adds `gcc` and `libc6-dev` for rustc linking.

## One-time setup

Build the runtime image:

```bash
./scripts/verus_docker/build_image.sh
```

Install the wrapper (adjust paths if your Verus install differs):

```bash
mkdir -p ~/bin
cp scripts/verus_docker/verus ~/bin/verus
chmod +x ~/bin/verus
export PATH="$HOME/bin:$PATH"
```

Ensure Verus and rustup/cargo dirs exist on the host (see `research_loop/scripts/install_verus.md`).

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `VERUS_HOME` | `$HOME/tools/verus` | Host Verus install (mounted read-only at `/opt/verus`) |
| `RUSTUP_HOME` | `$HOME/tools/verus-rustup` | Rustup toolchain cache |
| `CARGO_HOME` | `$HOME/tools/verus-cargo` | Cargo cache |
| `LEMMA_VERUS_DOCKER_IMAGE` | `lemma-verus-runtime:24.04` | Docker image tag |

## Usage

```bash
verus --version
verus --compile path/to/file.rs
```

The wrapper runs `docker run --network=none` as your uid/gid with the current
working directory mounted.
