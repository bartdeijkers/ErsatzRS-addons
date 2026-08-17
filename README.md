# Official ErsatzRS add-ons

This repository publishes the add-ons maintained by the ErsatzRS project. One
signed repository index can contain multiple independently versioned add-ons.
ErsatzRS installs packages explicitly and starts them as bounded child
processes; packages are never loaded into the server process.

The repository contains:

- `org.ersatzrs.addon.beeldengeluid`: enumerates Schatkamer series, individual
  episodes, public user-made lists, and saved searches, and streams their programmes. Its Remote
  Stream and media-list paths do not require Python or yt-dlp.
- `org.ersatzrs.addon.yt-dlp`: streams a remote video through an
  operator-installed yt-dlp and the ErsatzRS-managed FFmpeg runtime. It also
  requires an operator-installed deno, the JavaScript runtime yt-dlp enables by
  default; readiness reports its absence because playback cannot succeed
  without it.

The two streaming add-ons send video straight to ErsatzRS for immediate
playback; no permanent file is written.

Each package keeps its runtime self-contained below `addons/<id>/`. The
repository publisher is Rust; Python remains only for source-level provider
tests and is not an add-on runtime dependency. Beeld & Geluid enumeration and
playback are implemented directly for POSIX and Windows.

## Build the unsigned repository

Rust 1.97.1 builds the unsigned repository. The publisher requires the pinned
host validator so manifest and catalog checks use the same implementation as
ErsatzRS:

```sh
cargo run --locked --package repository-publisher -- \
  --sequence 1 \
  --base-url https://bartdeijkers.github.io/ErsatzRS-addons \
  --output dist \
  --validator tools/validator/ersatzrs-addon-validator-x86_64-unknown-linux-gnu
```

This creates deterministic ZIP packages, bounded PNG icon assets, and the exact
schema-v2 `index-v1.json` bytes that must be signed. The publishing workflow supplies the Ed25519 private key
only through the `ADDON_REPOSITORY_SIGNING_KEY_PEM` GitHub Actions secret. A
private key must never be committed, logged, or supplied as an add-on setting.

## Trust bootstrap

Before the first publication, the maintainer must create the Ed25519 key
outside any AI session, store its private PEM value directly in the GitHub
secret store, and copy only the raw 32-byte public-key value (standard Base64)
into ErsatzRS's official repository seed. Until that public key is installed,
the default repository is visible but intentionally cannot refresh.

## Development

Run the source-level checks without contacting provider services:

```sh
cargo fmt --all -- --check
cargo clippy --all-targets -- -D warnings
cargo test --locked
python3 -m unittest discover -s tests
```

A complete unsigned repository build needs no native artifacts. The publishing
workflow validates the package sources before packaging and signing the
repository.

Live playback tests require authorized provider access and the external tools
declared by each manifest. Do not place credentials, cookies, private media
URLs, or local machine paths in fixtures or logs.

## License

[Zlib](LICENSE). Provider names and services remain the property of their
respective owners. Users are responsible for authorization and service terms.
