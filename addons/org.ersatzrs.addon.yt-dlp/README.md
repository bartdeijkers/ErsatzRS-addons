# yt-dlp Remote Streams add-on

This add-on resolves and plays a remote video through an
operator-installed yt-dlp. Always download or update to the
[latest official yt-dlp release](https://github.com/yt-dlp/yt-dlp/releases/latest)
before configuring the add-on. ErsatzRS supplies its managed FFmpeg runtime;
yt-dlp is deliberately not bundled or updated automatically by the add-on.

Prepared downloads load only this package's local yt-dlp postprocessor plugin;
they do not load default plugin directories or replace the installed executable.
The plugin subclasses the stock chapter cutter: native yt-dlp still owns media
downloads, merging and SponsorBlock cuts. It corrects range handling and clips
manual SRT cues on the same retained timeline without losing font, color or
positioning markup. Captions entirely removed by cuts are valid absence, not a
failed download. The preparation child disables Python bytecode writes so the
installed add-on package stays unchanged. Subtitle-only acquisition does not
activate the plugin or download video/audio.

The stock-runtime regression is
`python -m unittest discover -s tests -p test_yt_dlp_item_operations.py`;
the native preparation test requires installed yt-dlp and explicit
`FFMPEG_BIN`/`FFPROBE_BIN` or those tools on `PATH`. Cue-only regressions live in
`tests/test_yt_dlp_caption_plugin.py`. All media fixtures are temporary and all
native fixture transfers are local files; provider network access is rejected.

## Prerequisites

Two programs must be installed by the operator and discoverable on the `PATH`
of the account that runs ErsatzRS:

- **yt-dlp**, which resolves the media.
- **[deno](https://deno.com/)**, a JavaScript runtime. yt-dlp enables only this
  runtime by default, so installing a different one is not equivalent.

Without a JavaScript runtime, some providers return a player response whose
media URL is bound to a restricted client. The managed FFmpeg runtime is then
refused when it fetches that URL, and playback fails with a provider
authorization error rather than an obvious configuration message. **Check**
therefore reports a missing runtime as unavailable, and the add-on cannot be
enabled until one is installed.

Because the runtime is resolved from `PATH`, confirm it is visible to the
*service* account rather than only to an interactive login shell. A unit file
or scheduler that does not read the usual shell profile needs the runtime's
directory added to its own `PATH`.

Direct video is streamed through ErsatzRS. SponsorBlock-enabled finite playback
requires host interval-streaming integration or the separate prepared-file path;
the add-on never silently returns an uncut stdout stream for that request.

## Per-item options

Hosts supporting manifest schema 5 render list defaults and item overrides for
**Browser cookies** (`none`, `firefox`, `chrome`, or `chromium`) and **Remove
SponsorBlock segments** (checked by default for finite items). Existing
publications keep their saved behavior until the operator saves and publishes.
The selected browser must be available to the service account. Only the browser
name is passed to yt-dlp; profile paths, cookie exports, and cookie values are
not accepted as settings. **Test access** returns typed outcomes for inaccessible
or locked profiles, decryption failure, provider restrictions, and other failure.
It does not return provider stderr, cookies, headers, or temporary media URLs.

`media-list.interval-metadata.v1` provides metadata-only discovery for host-owned
streaming cuts. It returns whole-source duration and at most 1,024 half-open
millisecond intervals, bound to the requested provider, option context and tool
version. The host clips those intervals to its saved chapter window. Successful
empty intervals are distinct from unsupported extractors or failed discovery;
neither failure becomes successful uncut playback. The operation simulates
yt-dlp with downloads disabled and never creates a processed media file.
Its marking categories match `--sponsorblock-remove default`, excluding filler,
highlights and chapter markers. Streaming transport and channel integration are
still being implemented in ErsatzRS; this metadata operation alone does not
make the existing stdout playback stream seekable.

`remote-stream.play.v4` uses the `play-intervals` operation with bounded JSON
stdin containing frozen source intervals. Native yt-dlp owns extraction,
authentication and every media transfer. One extraction checks the source
duration before stdout begins; a private temporary info file avoids repeated
extraction for each retained section. Sections are emitted sequentially as NUT
with raw `yuv420p` video and `pcm_f32le` audio, with cumulative timestamps and
bounded preroll. The host owns the one final lossy encoder. No transport URLs or
headers are returned to the host, and no removed interval becomes an uncut fallback.
This initial transport is SDR-only: detected HDR sources are refused. Raw video
avoids another lossy codec, but conversion to 8-bit `yuv420p` is not universally
lossless: higher bit depth and other pixel formats may lose information. Missing
HDR labels are not evidence of SDR; host admission must not assume HDR support.
Audio language, title and channel-layout preservation require fresh output-probe
validation; this operation selects one native yt-dlp audio track. Exact
cross-platform, profile and uninterrupted host playback acceptance remains open.
The wrapper removes its private info file on normal/error completion; abrupt
process-tree termination requires host-owned temporary-directory cleanup. Native
yt-dlp remains the transfer owner for subsequent managed-media work.

The separate full-file preparation operation declares generic Download ahead
support through `media-list.prepare.v2`. It uses native yt-dlp download/merge,
with `--sponsorblock-remove default` only when removal is enabled and
`--no-sponsorblock` when disabled. Enabled removal retains standard processing,
including yt-dlp's ordinary no-segments success. Provider/API or processing
failure cannot admit an unprocessed substitute. The final file is probed for
duration and hashed; the host checks and owns its storage budget, cancellation,
publication, and retention. Live or unknown-liveness items keep direct playback.
An options-aware direct stdout playback request requiring removal is rejected;
the host must resolve its published playback selection instead.

For chapter fragments, preparation downloads the whole source within the same
host storage and time budgets. Standard yt-dlp `--remove-chapters` ranges remove
the content before and after the fragment alongside SponsorBlock removal, using
one original-source timeline. This avoids applying original offsets to an
already shortened file. It can cost more bandwidth and temporary space than
direct fragment playback. If yt-dlp reports that the requested cuts remove all
content, preparation fails instead of admitting the unchanged original.

Both platform entrypoints use the same Deno adapters. The host supplies managed
FFmpeg and ffprobe, and limits the child process tree and staging usage during
preparation. Automatic yt-dlp updates remain disabled.

`media-list.subtitles.v1` adds a separate `subtitles` operation that acquires
only explicitly requested manual subtitle tracks with `--skip-download`,
`--write-subs`, and `--no-write-auto-subs`. It accepts at most two distinct
canonical primary/fallback languages. Native metadata selects one exact track,
or a deterministic regional match, per requested language; automatic captions,
machine translations and unrelated languages are never fallbacks. Successful
absence returns an empty artifact list. The host owns scratch storage, process
termination, byte quotas, caching and publication.

The operation converts manual tracks to SRT with native yt-dlp/FFmpeg and returns
their actual language, manual provenance, relative path, size and digest on the
original source clock. Optional `requested_subtitle_languages` on preparation
acquires the same selected tracks before native `ModifyChaptersPP` cuts video
and sidecars together. Preparation descriptors use the final prepared clock;
the host must not apply source offsets again. Empty optional request/result
fields preserve legacy preparation JSON. A requested conversion or processing
failure never admits an out-of-sync subtitle substitute.

For live HLS playback, play contract v2 accepts a host-selected maximum video
height. ErsatzRS normally requests up to 1080p and can temporarily retry at
720p when measured segment delivery cannot keep pace with wall time. The bound
is a ceiling rather than a required exact rendition, and all provider-specific
format selection remains inside this add-on.

yt-dlp's reusable client and signature cache is stored in the host-provided
add-on cache directory. The installed package remains immutable, including on
Windows where the host deliberately does not expose an operator home directory
to the child process.

The add-on can enumerate public playlists and individual public video links
through **Media Sources > Add-on Lists**. A direct video becomes a one-item
list, with live and finite state retained from yt-dlp; playlist entries retain
their provider order. When enabled, ErsatzRS creates a managed local source
named `yt-dlp` under `<ErsatzRS profile>/yt-dlp_media` by default. Each imported
link gets its own subfolder and Remote Streams library containing generated
definitions; the storage path is configurable and no video is downloaded
permanently.

On hosts that support incremental imports, the add-on uses the host-provided
staged yt-dlp archive to emit only identities that have not been imported yet.
It still examines the complete bounded playlist window because YouTube
playlists can be reordered; encountering a known identity therefore never
stops discovery before a later unseen item. The host owns archive promotion,
so a cancelled or invalid import cannot advance the live checkpoint. A separate
one-entry flat probe refreshes playlist title, description, tags, people,
artwork, and stable identifiers even when the archive suppresses every item.

Configure the yt-dlp executable under **Settings > Add-ons**, run **Check**,
then enable the add-on. A Remote Stream definition selects it by identity:

```yaml
url: https://media.example.org/public-domain/<video-id>
addon: org.ersatzrs.addon.yt-dlp
is_live: false
duration: "00:20:00"
title: Example public-domain video
```

For legacy stdout playback, temporary media URLs and request headers stay inside
yt-dlp's streaming flow. Seekable resolution returns them only as invocation-local
transport data to the host.
Media-list v4 supplies provider metadata to the same ErsatzRS review editor as
other add-ons. The operator-installed `yt-dlp` executable performs the complete
playlist and video extraction, so updating yt-dlp remains the way provider
changes are repaired. The shared Deno helper only maps yt-dlp's JSON fields to
the stable provider-neutral document; it does not scrape or implement a
YouTube client. Media-list v6 maps yt-dlp authentication and content restriction
signals to typed item availability reasons. It emits neither cookie material
nor provider stderr, and one restricted item does not turn the whole list into
a provider failure. For retained playlist items, the add-on performs one full
metadata extraction and emits provider chapters as bounded timestamp/title text through
`remote-stream.item.v2`. Both entrypoints round fractional starts to whole
seconds before emission; ErsatzRS owns validation and fragment derivation.
Diagnostics go to stderr and standard output contains only media bytes. Access
and stream material only when authorized and in accordance with the provider's
terms and applicable law.
