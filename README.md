# Official ErsatzRS add-ons

This repository publishes the add-ons maintained by the ErsatzRS project. One
signed repository index can contain multiple independently versioned add-ons.
ErsatzRS installs packages explicitly and starts them as bounded child
processes; packages are never loaded into the server process.

The initial repository contains:

- `org.ersatzrs.addon.beeldengeluid`: enumerates and plays Beeld & Geluid
  Schatkamer programmes without Python or yt-dlp.
- `org.ersatzrs.addon.yt-dlp`: plays a remote video through an
  operator-installed yt-dlp and the ErsatzRS-managed FFmpeg runtime.

Package contracts are owned by the `ersatzrs-addon-contract` crate in the
[ErsatzRS repository](https://github.com/bartdeijkers/ErsatzRS). Each package
keeps its runtime self-contained below `addons/<id>/`; repository tooling may
use Python but the Beeld & Geluid add-on does not.

## Build the unsigned repository

Python 3.11 or newer is required only for release tooling:

```sh
python3 tools/build_repository.py \
  --sequence 1 \
  --base-url https://bartdeijkers.github.io/ErsatzRS-addons \
  --output dist
```

This creates deterministic ZIP packages and the exact `index-v1.json` bytes
that must be signed. The publishing workflow supplies the Ed25519 private key
only through the `ADDON_REPOSITORY_SIGNING_KEY_PEM` GitHub Actions secret. A
private key must never be committed, logged, or supplied as an add-on setting.

## Trust bootstrap

Before the first publication, the maintainer must create the Ed25519 key
outside any AI session, store its private PEM value directly in the GitHub
secret store, and copy only the raw 32-byte public-key value (standard Base64)
into ErsatzRS's official repository seed. Until that public key is installed,
the default repository is visible but intentionally cannot refresh.

## Development

Run the repository checks without contacting provider services:

```sh
python3 -m unittest discover -s tests
python3 tools/build_repository.py --sequence 1 --base-url https://example.test/addons --output dist
```

Live playback tests require authorized provider access and the external tools
declared by each manifest. Do not place credentials, cookies, private media
URLs, or local machine paths in fixtures or logs.

## License

GPL-3.0-or-later. Provider names and services remain the property of their
respective owners. Users are responsible for authorization and service terms.
