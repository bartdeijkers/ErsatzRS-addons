# Beeld & Geluid add-on

This add-on enumerates a Schatkamer series, individual episode, public shared list, or saved-search
link as NDJSON and streams individual episodes as MPEG-TS. Its Unix and Windows
Remote Stream implementations perform the complete provider flow directly;
they do not require Python, yt-dlp, browser cookies, or stored media URLs. The
same platform scripts feed one shared Deno adapter, which normalizes both
entrypoints to the provider-neutral media-list contract. Media-list v4 supplies
list and item titles, summaries, classification, credits, provenance, and
artwork candidates to ErsatzRS's shared metadata review editor on Windows and
POSIX platforms. The adapter also prefers each programme card's episode still
over a generic broadcaster image from the episode detail page.

Video is streamed straight through ErsatzRS for immediate playback; no
permanent file is written.

When enabled, ErsatzRS creates a managed local source named `beeldengeluid`.
Its default root is `<ErsatzRS profile>/beeldengeluid_media`; the path can be
changed under **Settings > Add-ons**. Every link added through **Media Sources
> Add-on Lists** gets its own subfolder and Remote Streams library. The folder
contains only the managed playlist manifest and generated stream definitions,
not downloaded video files.

Required network destinations and executables are declared in `addon.toml`.
ErsatzRS supplies its managed FFmpeg path. Deno must be discoverable on the
service account's `PATH`; the same Deno installation required by the yt-dlp
add-on can be shared. An optional custom curl path can be configured on
**Settings > Add-ons**.

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
playlist follows the user's order across every result page; duplicate
programmes keep their first position, and unavailable programmes retain their
provider identity for diagnostics and local replacement:

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

The add-on list manager also accepts saved-search links such as
`https://schatkamer.beeldengeluid.nl/zoeken?collectie=<name>`. It preserves the
search term, sorting, media type, date, broadcaster, collection, genre, person,
and subject filters (including repeated and Unicode values), then follows all
result pages in the programme order returned by Schatkamer. The host-owned list synchronizer links
the records to the Remote Streams generated in that list's managed library.

An individual episode definition uses the same identity:

```yaml
url: https://schatkamer.beeldengeluid.nl/serie/<series-id>/<series-slug>/aflevering/<episode-id>
addon: org.ersatzrs.addon.beeldengeluid
is_live: false
title: Episode title
```

The same episode URL can be imported as an add-on list. Its optional chapter
field accepts one `M:SS`, `MM:SS`, or `H:MM:SS` marker and title per line. The
host validates the complete input atomically and retains the unbounded full
episode alongside independently selectable fragments. Fragment playback uses
whole-second `start` and optional `end` query parameters; the final `end` is
omitted only when the provider does not expose a duration.

Diagnostics go to stderr. Standard output is reserved for NDJSON during
`list` and media bytes during `play`.
