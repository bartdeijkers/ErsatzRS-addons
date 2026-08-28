# Install or update the add-on repository

Use a Git checkout when the ErsatzRS host can access files maintained by your
normal Git tooling. Use an offline bundle when the host must not have repository
access. Both methods expose the same add-ons and require **Unknown sources**.

## Install from a private Git checkout

1. Open **Settings > Add-ons > Sources** in ErsatzRS.
2. Enable **Unknown sources** and accept the confirmation.
3. Copy the checkout directory shown on the Sources page.
4. Clone this repository as one direct child of that directory:

   ```sh
   git clone git@github.com:bartdeijkers/ErsatzRS-addons.git <checkout-directory>/official
   ```

5. Choose **Refresh** in ErsatzRS.
6. Open the desired add-on and install it.

ErsatzRS only scans the checkout. It never invokes Git, reads Git credentials,
or executes an add-on directly from the working tree.

## Update a Git checkout

1. Pull the repository with your normal Git credentials:

   ```sh
   git -C <checkout-directory>/official pull --ff-only
   ```

2. Choose **Refresh** under **Settings > Add-ons**.
3. Review and confirm the update for each add-on separately.

Pulling a checkout does not alter the installed package. ErsatzRS copies a new
immutable package only after that add-on's update is confirmed.

## Install from an offline bundle

1. Download `ErsatzRS-addons.zip` from a release in the private repository.
2. Open **Settings > Add-ons > Sources**.
3. Enable **Unknown sources**.
4. Select the ZIP as the **Repository package** and install it.
5. Open the desired add-on offer and install it separately.

The ZIP must contain `repository.toml` and `addons/` at its root. Do not wrap
those entries in another directory.

## Update an offline bundle

Upload the bundle from the newer release as the repository package. ErsatzRS
replaces the stored repository snapshot after complete validation, but it does
not update every installed add-on automatically. Confirm each desired update
from the manager.

An installation inherited from the former catalog model remains available as
legacy unmanaged. When a matching local offer is available, ErsatzRS requires
an explicit adoption confirmation and preserves the add-on settings and data
namespace.

## Troubleshoot discovery

- Confirm **Unknown sources** is enabled.
- For a checkout, confirm the repository is exactly one directory below the
  checkout path shown by ErsatzRS.
- Confirm `repository.toml` is at the source root and each add-on lives below
  `addons/<add-on-id>/`.
- Choose **Refresh** after every `git pull` or manual checkout change.
- Read the source row's scan error. A failed scan preserves the previous valid
  offers rather than partially applying the broken source.

See the [repository layout reference](../reference/repository-layout.md) for
the exact source and bundle structure.
