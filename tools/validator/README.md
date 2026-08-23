# Pinned host validator

`ersatzrs-addon-validator-x86_64-unknown-linux-gnu` is the thin validator built
from the private ErsatzRS host repository's `ersatzrs-addon-contract` crate.
The official public workflow verifies its checked-in SHA-256 before execution,
so it runs the host's exact Rust contract without receiving credentials for the
private repository.

The binary handles public manifest and catalog data only. Replace it only from
a reviewed host contract version, update `SHA256SUMS`, and rerun the complete
repository test and deterministic-build gates before publishing.

The current binary was built from `ersatzrs-addon-contract` 0.2.0 after the
AMM-F/AMM-G contract update. It validates `media-list.list.v5` liveness and the
overview/detail records used by `media-list.import.v1`, in addition to exact
runtime conformance for captured media-list NDJSON through
`--kind media-list-output`.
