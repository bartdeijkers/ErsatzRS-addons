# Official ErsatzRS add-ons

This private repository contains the add-ons maintained for ErsatzRS. Operators
acquire it themselves as a Git checkout or a complete offline ZIP; ErsatzRS
does not receive Git credentials or contact a repository catalog.

Installing the repository discovers add-on offers. Each add-on is installed
and updated separately in **Settings > Add-ons**, and the running installation
remains an immutable host-managed copy until an operator confirms an update.

## Add-ons

- [Beeld & Geluid](addons/org.ersatzrs.addon.beeldengeluid/README.md) enumerates
  Schatkamer series, episodes, public shared lists, and saved searches, and
  streams their programmes.
- [yt-dlp](addons/org.ersatzrs.addon.yt-dlp/README.md) streams supported remote
  media through an operator-installed yt-dlp and imports public playlists or
  individual videos as add-on lists.

## Documentation

- [Install or update the repository](docs/how-to/install-repository.md)
- [Build and test the repository](docs/how-to/build-and-test.md)
- [Publish an offline-bundle release](docs/how-to/publish-release.md)
- [Repository layout and bundle format](docs/reference/repository-layout.md)

## License

[Zlib](LICENSE). Provider names and services remain the property of their
respective owners. Users are responsible for authorization, provider terms,
and applicable law.
