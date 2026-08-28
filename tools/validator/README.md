# Pinned host validator

`ersatzrs-addon-validator-x86_64-unknown-linux-gnu` is built from the private
ErsatzRS host repository's `ersatzrs-addon-contract` crate. The private release
workflow verifies the checked-in SHA-256 before using it, so add-on manifests
and captured provider output are checked against a reviewed host contract
without giving this repository access to the host source.

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
`SHA256SUMS`, run the complete repository tests, validate both add-on manifests,
and build the deterministic offline bundle before publishing a release.
