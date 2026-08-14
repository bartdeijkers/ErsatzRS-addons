# yt-dlp Remote Streams add-on

This add-on resolves and plays a finite remote video through an
operator-installed yt-dlp. Always download or update to the
[latest official yt-dlp release](https://github.com/yt-dlp/yt-dlp/releases/latest)
before configuring the add-on. ErsatzRS supplies its managed FFmpeg runtime;
yt-dlp is deliberately not bundled or updated automatically by the add-on.

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
Diagnostics go to stderr and standard output contains only media bytes. Access
and stream material only when authorized and in accordance with the provider's
terms and applicable law.
