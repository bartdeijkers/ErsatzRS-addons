# yt-dlp Remote Streams add-on

This add-on resolves and plays a remote video through an
operator-installed yt-dlp. Always download or update to the
[latest official yt-dlp release](https://github.com/yt-dlp/yt-dlp/releases/latest)
before configuring the add-on. ErsatzRS supplies its managed FFmpeg runtime;
yt-dlp is deliberately not bundled or updated automatically by the add-on.

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

Video is streamed straight through ErsatzRS for immediate playback; no
permanent file is written.

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
so a cancelled or invalid import cannot advance the live checkpoint.

Configure the yt-dlp executable under **Settings > Add-ons**, run **Check**,
then enable the add-on. A Remote Stream definition selects it by identity:

```yaml
url: https://media.example.org/public-domain/<video-id>
addon: org.ersatzrs.addon.yt-dlp
is_live: false
duration: "00:20:00"
title: Example public-domain video
```

Temporary media URLs and request headers stay inside yt-dlp's streaming flow.
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
