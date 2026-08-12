# yt-dlp Remote Streams add-on

This add-on resolves and plays a finite remote video through an
operator-installed yt-dlp. ErsatzRS supplies its managed FFmpeg runtime; yt-dlp
is deliberately neither bundled nor updated by the add-on.

Video is streamed directly through ErsatzRS for immediate playback, comparable
to casting it to a Chromecast. The add-on does not save a permanent video file
and is not designed for downloading or building a local video collection.

Configure the yt-dlp executable under **Settings > Add-ons**, run **Check**,
then enable the add-on. A Remote Stream definition selects it by identity:

```yaml
url: https://www.youtube.com/watch?v=<video-id>
addon: org.ersatzrs.addon.yt-dlp
is_live: false
duration: "00:20:00"
title: Example remote video
```

Temporary media URLs and request headers stay inside yt-dlp's streaming flow.
Diagnostics go to stderr and standard output contains only media bytes. Access
and stream material only when authorized and in accordance with the provider's
terms and applicable law.
