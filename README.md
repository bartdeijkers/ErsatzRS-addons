# Official ErsatzRS add-ons

This repository publishes the add-ons maintained by the ErsatzRS project. One
signed repository index can contain multiple independently versioned add-ons.
ErsatzRS installs packages explicitly and starts them as bounded child
processes; packages are never loaded into the server process.

The repository contains:

- `org.ersatzrs.addon.beeldengeluid`: enumerates Schatkamer series, public
  user-made lists, and saved searches, and streams their programmes. Its Remote
  Stream path does not require Python or yt-dlp.
- `org.ersatzrs.addon.yt-dlp`: streams a remote video through an
  operator-installed yt-dlp and the ErsatzRS-managed FFmpeg runtime.
- `org.ersatzrs.addon.trakt`: imports public Trakt lists through the
  provider-neutral media-list contract, with its client ID resolved only from
  an environment or file secret reference.

The two streaming add-ons send video directly to ErsatzRS for immediate playback, much like
casting a video to a Chromecast. They are streaming integrations and are not
designed to download videos or create a permanent local video collection.

Package contracts are owned by the `ersatzrs-addon-contract` crate in the
[ErsatzRS repository](https://github.com/bartdeijkers/ErsatzRS). Each package
keeps its runtime self-contained below `addons/<id>/`. Repository tooling and
the Beeld & Geluid provider-list adapter use Python; the Trakt adapter is a
native Rust executable, and the Beeld & Geluid Remote Stream enumeration and
playback path remains implemented directly for POSIX and Windows.

## Build the unsigned repository

Python 3.11 or newer is required only for release tooling:

```sh
python3 tools/build_repository.py \
  --sequence 1 \
  --base-url https://bartdeijkers.github.io/ErsatzRS-addons \
  --output dist \
  --native-artifacts native-artifacts
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
cargo fmt --manifest-path native/trakt/Cargo.toml -- --check
cargo test --locked --manifest-path native/trakt/Cargo.toml
cargo clippy --locked --manifest-path native/trakt/Cargo.toml --all-targets -- -D warnings
python3 -m unittest discover -s tests
```

A complete unsigned repository build additionally needs the six native Trakt
binaries staged below `native-artifacts/org.ersatzrs.addon.trakt/bin/<rid>/`.
The publishing workflow builds those binaries for every supported ErsatzRS RID
before packaging and signing the repository.

Live playback tests require authorized provider access and the external tools
declared by each manifest. Do not place credentials, cookies, private media
URLs, or local machine paths in fixtures or logs.

## License

[Zlib](LICENSE). Provider names and services remain the property of their
respective owners. Users are responsible for authorization and service terms.
