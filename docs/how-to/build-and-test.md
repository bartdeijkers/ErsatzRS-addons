# Build and test the repository

Run all commands from the repository root. The offline-bundle builder uses only
the Python standard library and works on Linux and Windows.

## Build the offline bundle

Linux:

```sh
python3 tools/build_repository_bundle.py
```

Windows PowerShell or Command Prompt:

```powershell
py -3 tools/build_repository_bundle.py
```

The default output is `dist/ErsatzRS-addons.zip`. Select another location with
`--output <path>`:

```sh
python3 tools/build_repository_bundle.py --output dist/candidate.zip
```

The script packages the current working tree, including uncommitted add-on or
manifest changes. Build releases only from the intended clean release commit.

## Run the cross-platform tests

Linux:

```sh
python3 -m unittest discover -s tests
```

Windows:

```powershell
py -3 -m unittest discover -s tests
```

Install Deno before running the complete provider-adapter coverage. Some
platform- or runtime-specific cases are skipped when their declared external
runtime is unavailable.

## Verify adaptive source checks

Run the normalized fixtures, POSIX or Windows entrypoint, bounded-output,
deadline, cancellation and bundle tests:

```sh
python3 -m unittest discover -s tests -p test_yt_dlp_source_check.py
```

On Windows without Python, use the native executable fixture (Deno and Windows
PowerShell required):

```powershell
powershell.exe -NoProfile -File tests/test_yt_dlp_source_check_windows.ps1
```

For newer capabilities unsupported by the pinned standalone validator, use the
current ErsatzRS checkout's `cargo xtask validate-addon-manifest <addon.toml>`.
The host's ignored `installed_yt_dlp_candidate_adaptive_unchanged_then_changed`
test accepts `ERSATZRS_YT_DLP_CANDIDATE=<package-directory>` and installs a copy
in a throwaway database. It checks the Adaptive capability predicate and real
scheduler admission with synthetic extraction; it does not alter an operator's
installation. Run it through the host's `./run.sh test -p ersatzrs-infra --lib
installed_yt_dlp_candidate_adaptive --run-ignored ignored-only` wrapper.

## Validate manifests on Linux x86-64

The checked-in host validator is a Linux x86-64 binary. Verify its digest from
its own directory, then validate every add-on manifest:

```sh
(cd tools/validator && sha256sum --check SHA256SUMS)
tools/validator/ersatzrs-addon-validator-x86_64-unknown-linux-gnu \
  addons/*/addon.toml
```

The Python repository tests validate `repository.toml` and the local repository
layout on both Linux and Windows.

## Inspect the result

Test the ZIP with Python on either platform:

```sh
python3 -m zipfile -t dist/ErsatzRS-addons.zip
```

On Windows, replace `python3` with `py -3`. The builder prints the archive's
SHA-256 digest. Rebuilding an unchanged working tree produces the same bytes.

The [repository layout reference](../reference/repository-layout.md) describes
the entries and invariants enforced by the builder.
