# Pinned host validator

`ersatzrs-addon-validator-x86_64-unknown-linux-gnu` is the thin validator built
from the private ErsatzRS host repository's `ersatzrs-addon-contract` crate.
The official public workflow verifies its checked-in SHA-256 before execution,
so it runs the host's exact Rust contract without receiving credentials for the
private repository.

The binary handles public manifest and catalog data only. Replace it only from
a reviewed host contract version, update `SHA256SUMS`, and rerun the complete
repository test and deterministic-build gates before publishing.

The current binary was built from ErsatzRS commit
`8a008c3bb95830bfeb48e636640a246984e97033`; it adds exact runtime conformance
validation for captured media-list NDJSON through `--kind media-list-output`.
