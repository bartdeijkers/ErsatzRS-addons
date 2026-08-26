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

## Episodes archived in several parts

A programme that was archived across several analogue carriers is published as
one episode with several streams. The add-on treats them as one continuous
programme: the reported duration is the sum of every part, and playback emits
the parts back to back in the provider's playout order as one MPEG-TS timeline.
A seek position and a chapter fragment both address that concatenated timeline,
so they select the part that actually contains the requested moment instead of
being applied to every part. Parts that end before the requested position are
skipped, and each part's output timestamps are offset by everything already
emitted so the timeline never steps backwards at a part boundary. A carrier
digitised with leader before the programme starts reports where its content
begins, and playback opens past it, so a part's position on the episode
timeline stays independent of its position inside its own asset.

Each part is streamed at its largest rendition. A Schatkamer master playlist
lists its renditions smallest first, and FFmpeg maps the first video stream it
finds, so the add-on resolves the master to the largest picture rather than
handing the master over as published. If a master cannot be read, playback
falls back to it and says so on stderr.

## Repeat digitisations

Some episodes list the same carrier several times, because the archive holds
more than one digitisation of it. Those copies are not marked as such: they are
recognisable only by durations that land within a few seconds of each other,
and their renditions are usually identical. Genuine parts of one episode rarely
have near-equal durations, but that is a likeness test rather than something
the provider states, so collapsing them is opt-in.

Set **Duplicate part tolerance (seconds)** under **Settings > Add-ons** to the
largest gap that should still count as the same carrier; `0`, the default,
keeps every copy. A tolerance of about 5 covers the spread seen in practice.
Copies within the tolerance of an earlier part are collapsed into it, the
episode keeps that part's place and length, and playback keeps the copy with
the largest rendition — falling back to the longest copy when the renditions
match, which they normally do. Each collapse is reported on stderr.

The tolerance applies to the imported duration as well as to playback, so the
schedule reserves exactly what is streamed. Change it and re-synchronize the
add-on list; stored durations are not rewritten until then.

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

Series, shared-list, and saved-search imports preserve every supplied query
parameter while replacing only Schatkamer's `pagina` parameter during
pagination. Aggregate discovery uses the provider's overview metadata without
requesting each episode detail page, deduplicates overlapping pages by episode
identity, and retains the first provider position. A series URL with
`alleenafspeelbaar=nee` therefore retains non-playable episodes in provider
order as `unavailable` / `not_playable`, so ErsatzRS can publish the row after a
Local replacement is selected. Direct episode discovery still requests that
episode page and returns its detail metadata and provider availability.

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
