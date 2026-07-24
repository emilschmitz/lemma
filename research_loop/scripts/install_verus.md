# Installing Verus

Lemma’s Verus research loop uses the official binary release.

## Installed location (this machine)

```
/home/emil/tools/verus/verus
```

Version: `0.2026.07.18.3a4d30b` (needs rustup toolchain `1.96.0-x86_64-unknown-linux-gnu`).

```bash
source research_loop/scripts/env_verus.sh
verus --version
```

The harness also auto-discovers `~/tools/verus/verus` when `verus` is not on `PATH`.

## Fresh install

```bash
mkdir -p ~/tools && cd ~/tools
curl -L -o verus-linux.zip \
  https://github.com/verus-lang/verus/releases/download/release/0.2026.07.18.3a4d30b/verus-0.2026.07.18.3a4d30b-x86-linux.zip
unzip -o verus-linux.zip
# rename extracted dir to verus if needed
rustup install 1.96.0-x86_64-unknown-linux-gnu
export PATH="$HOME/tools/verus:$PATH"
verus --version
```

## Enable verification in the harness

`config.env`:

```
ENABLE_VERUS_VERIFY=1
```

Exec/bench still runs if verify fails; proof status is reported separately.
