# Official ErsatzRS add-ons

This private repository contains the add-ons maintained for ErsatzRS. Operators
acquire it themselves as a Git checkout or a complete offline ZIP; ErsatzRS
does not receive Git credentials or contact a repository catalog.

Installing the repository discovers add-on offers. Each add-on is installed
and updated separately in **Settings > Add-ons**, and the running installation
remains an immutable host-managed copy until an operator confirms an update.

## Add-ons

- [TV-guide teletext](addons/org.ersatzrs.addon.tvguide-teletext/README.md) (0.1.2) creates
  profile-scoped teletext guides with page-range/index selection, themes and
  custom zones from the host's read-only programme context.
- [yt-dlp](addons/org.ersatzrs.addon.yt-dlp/README.md) streams supported remote
  media through an operator-installed yt-dlp and imports public playlists or
  individual videos as add-on lists.

Beeld & Geluid is retired and unsupported by maintainer decision. Do not
access that service for development or acceptance. The v0.11.12 repository
bundle contains TV-guide teletext 0.1.2 and yt-dlp 0.11.12. Repository release
versions are independent of each add-on version; the older v0.11.11 bundle
contains only yt-dlp.

Before upgrading ErsatzRS to 1.2, import or refresh this repository and explicitly
update the installed add-ons in **Settings > Add-ons**. These versions also retain
their previous host compatibility. Repository refresh and application upgrade do
not automatically replace installed packages or operator data.

## Documentation

- [Install or update the repository](docs/how-to/install-repository.md)
- [Build and test the repository](docs/how-to/build-and-test.md)
- [Publish an offline-bundle release](docs/how-to/publish-release.md)
- [Repository layout and bundle format](docs/reference/repository-layout.md)

## License

[Zlib](LICENSE). Provider names and services remain the property of their
respective owners. Users are responsible for authorization, provider terms,
and applicable law.
