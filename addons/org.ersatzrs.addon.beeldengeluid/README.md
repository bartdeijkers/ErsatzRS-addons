# Beeld & Geluid add-on

This add-on enumerates a Schatkamer series or public shared list as NDJSON and
streams individual episodes as MPEG-TS. Its Unix and Windows implementations perform the complete
provider flow directly; they do not require Python, yt-dlp, browser cookies,
or stored media URLs.

Video is streamed directly through ErsatzRS for immediate playback, comparable
to casting it to a Chromecast. The add-on does not save a permanent video file
and is not designed for downloading or building a local video collection.

Required network destinations and executables are declared in `addon.toml`.
ErsatzRS supplies its managed FFmpeg path. The optional curl path and emergency
Server Action ID can be configured on **Settings > Add-ons**.

A managed playlist uses the stable add-on identity:

```yaml
name: Example series
url: https://schatkamer.beeldengeluid.nl/serie/<series-id>/<series-slug>
addon: org.ersatzrs.addon.beeldengeluid
folder: episodes
sync:
  interval: 24h
  order: upstream
  on_removed: trash
create_playlist: true
```

A public user-made list uses its shared `/lijst/<uuid>` URL. The generated
playlist follows the user's order; duplicate programmes keep their first
position, and programmes that Schatkamer marks unavailable are skipped:

```yaml
name: Example shared list
url: https://schatkamer.beeldengeluid.nl/lijst/<list-uuid>
addon: org.ersatzrs.addon.beeldengeluid
folder: shared-list
sync:
  interval: 24h
  order: upstream
  on_removed: trash
create_playlist: true
```

Only public shared lists are supported. Private lists that require a signed-in
browser session are rejected without replacing the last successful sync.

An individual episode definition uses the same identity:

```yaml
url: https://schatkamer.beeldengeluid.nl/serie/<series-id>/<series-slug>/aflevering/<episode-id>
addon: org.ersatzrs.addon.beeldengeluid
is_live: false
title: Episode title
```

Diagnostics go to stderr. Standard output is reserved for NDJSON during
`list` and media bytes during `play`.
