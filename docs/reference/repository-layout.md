# Repository layout and offline-bundle format

This repository is a local ErsatzRS add-on source. It has no public catalog,
index URL, signing key, detached signature, or GitHub Pages deployment.

## Source layout

```text
repository.toml
addons/
└── org.ersatzrs.addon.yt-dlp/
    ├── addon.toml
    └── ...package files...
```

`repository.toml` and `addons/` are direct children of the source root. Every
direct child below `addons/` is one independently versioned add-on, and its
directory name equals the `id` in `addon.toml`.

## Repository manifest

`repository.toml` uses local repository schema version 1 and contains exactly:

```toml
schema_version = 1
id = "org.ersatzrs.repository.official"
name = "Official ErsatzRS add-ons"

[description]
"en-US" = "Official add-ons maintained for ErsatzRS"
```

The repository identity is stable across Git checkouts and offline bundles.
ErsatzRS refuses a checkout and a bundle that claim the same identity at the
same time.

## Offline bundle

`ErsatzRS-addons.zip` contains only `repository.toml` and regular files below
`addons/`. The root README, development tools, tests, native build inputs, and
workflow files are not part of the runtime bundle.

The repository builder:

- rejects symlinks and unsupported filesystem entries;
- sorts paths lexically;
- records a fixed ZIP timestamp;
- uses DEFLATE compression;
- preserves modes recorded by Git when available;
- falls back to mode `0755` for shell entrypoints and `0644` for other files;
- writes through a temporary file and atomically replaces the selected output;
- prints the resulting SHA-256 digest.

The default output is `dist/ErsatzRS-addons.zip`. Output is forbidden inside
`repository.toml` or the `addons/` tree.

## Acquisition and installation

Git credentials remain exclusively in operator-owned Git tooling. ErsatzRS
scans a checkout after an explicit refresh but never runs Git or contacts a
repository service.

Offline bundles and checkouts are gated by the off-by-default **Unknown
sources** setting. Discovering a source does not install every package. Each
add-on installation or update is a separate operator action, and ErsatzRS runs
the resulting immutable managed copy rather than the source tree.
