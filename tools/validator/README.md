# Pinned host validator

`ersatzrs-addon-validator-x86_64-unknown-linux-gnu` is built from the private
ErsatzRS host repository's `ersatzrs-addon-contract` crate. The private release
workflow verifies the checked-in SHA-256 before using it, so add-on manifests
and captured provider output are checked against a reviewed host contract
without giving this repository access to the host source.

The current pin is built from host commit `e445ace3`, including manifest v6
and its permission-reviewed `tool.update.v1` contract. On Linux x64, rebuild
from the intended host checkout using its configured target directory:

```sh
CARGO_BUILD_JOBS=1 RUSTFLAGS="--remap-path-prefix=$HOME=/build" \
  cargo build --locked --release -p ersatzrs-addon-contract \
  --bin ersatzrs-addon-validator
```

Path remapping keeps maintainer-machine paths out of the distributed binary.

The active release workflow uses the binary for:

- every `addons/<id>/addon.toml` document;
- normalized media-list NDJSON through `--kind media-list-output`.

The local `repository.toml` schema and directory identity rules are covered by
`tests/test_repository.py`. No catalog or signature document is produced by
the current repository model.

Verify the pinned binary from this directory:

```sh
cd tools/validator
sha256sum --check SHA256SUMS
```

Replace the binary only from a reviewed host contract build. Update
`SHA256SUMS`, run the complete repository tests, validate all add-on manifests,
and build the deterministic offline bundle before publishing a release.
