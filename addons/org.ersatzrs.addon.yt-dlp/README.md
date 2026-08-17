# yt-dlp Remote Streams add-on

This add-on resolves and plays a finite remote video through an
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

The add-on can enumerate public playlists through **Media Sources > Add-on
Lists**. When enabled, ErsatzRS creates a managed local source named `yt-dlp`
under `<ErsatzRS profile>/yt-dlp_media` by default. Each imported playlist gets
its own subfolder and Remote Streams library containing generated definitions;
the storage path is configurable and no video is downloaded permanently.

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
For retained playlist items, the add-on performs one full metadata extraction
and emits provider chapters as bounded timestamp/title text through
`remote-stream.item.v2`. Both entrypoints round fractional starts to whole
seconds before emission; ErsatzRS owns validation and fragment derivation.
Diagnostics go to stderr and standard output contains only media bytes. Access
and stream material only when authorized and in accordance with the provider's
terms and applicable law.
