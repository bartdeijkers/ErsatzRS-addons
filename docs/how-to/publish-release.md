# Publish an offline-bundle release

The private repository does not build on ordinary pushes to `main`. Publishing
a GitHub release starts validation, builds `ErsatzRS-addons.zip`, and attaches
that ZIP directly to the release.

## Prepare the release commit

1. Confirm each changed add-on manifest has the intended version and metadata.
2. Run the cross-platform repository tests on the platforms affected by the
   change.
3. Build and inspect the offline bundle:

   ```sh
   python3 -m unittest discover -s tests
   python3 tools/build_repository_bundle.py
   python3 -m zipfile -t dist/ErsatzRS-addons.zip
   ```

4. Commit and push the reviewed release state.
5. Tag the exact commit intended for publication and push the tag.

The [build and test guide](build-and-test.md) contains the equivalent Windows
commands and the Linux host-validator check.

## Publish the GitHub release

Create and publish a release for the pushed tag through GitHub, or with the
GitHub CLI:

```sh
gh release create <tag> --verify-tag --title "<title>" --notes-file <notes-file>
```

The `Validate and bundle private add-on repository` workflow then:

1. runs the Python suite with the Windows entrypoints on native Windows;
2. verifies the pinned Linux validator and validates manifests/provider output;
3. runs the complete Python suite on Linux;
4. builds `dist/ErsatzRS-addons.zip` with the repository-root build script;
5. stores the ZIP as an Actions artifact;
6. downloads that exact artifact in a write-scoped job and attaches it to the
   published release.

Only the final attachment job receives `contents: write`; validation and bundle
creation run with read-only repository permission.

## Verify the published bundle

Wait for the workflow to finish, then download and test the release asset:

```sh
gh release download <tag> --pattern ErsatzRS-addons.zip --dir dist/release
python3 -m zipfile -t dist/release/ErsatzRS-addons.zip
```

Confirm the asset contains `repository.toml` and the complete `addons/` tree.
If the workflow is rerun for the same release, its attachment step replaces the
asset with the newly validated workflow artifact.

## Build without publishing a release

Start the workflow manually when CI proof or a downloadable candidate is
needed without creating or changing a release:

```sh
gh workflow run publish.yml --ref main
```

A manual run performs the Windows and Linux validation and uploads an Actions
artifact. The release-attachment job is skipped.

## Recover an interrupted release attachment

If a published release is missing its bundle because attachment failed, run:

```sh
gh workflow run publish.yml --ref main -f release_tag=<existing-release-tag>
```

The workflow checks out that existing tag for both Windows and Linux validation,
then attaches its bundle using the current publishing workflow. It does not move
the tag or build the package from current `main`. Verify the downloaded archive
after the workflow finishes, as for an ordinary release.
