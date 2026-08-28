function seconds(value: string): number {
  if (/^\d+(?:\.\d+)?$/.test(value)) return Number(value);
  const parts = value.split(":");
  if (parts.length !== 3 || parts.some((part) => !/^\d+(?:\.\d+)?$/.test(part))) {
    throw new Error("the seek timestamp is invalid");
  }
  return Number(parts[0]) * 3600 + Number(parts[1]) * 60 + Number(parts[2]);
}

const source = Deno.env.get("ERSATZRS_REMOTE_STREAM_URL");
const ytDlp = Deno.env.get("YT_DLP_BIN");
const ffmpeg = Deno.env.get("FFMPEG_BIN");
if (!source || !ytDlp || !ffmpeg) throw new Error("the playback environment is incomplete");

const url = new URL(source);
const fragmentStart = url.searchParams.has("start") ? seconds(url.searchParams.get("start")!) : 0;
const fragmentEnd = url.searchParams.has("end") ? seconds(url.searchParams.get("end")!) : undefined;
url.searchParams.delete("start");
url.searchParams.delete("end");
const absoluteSeek = fragmentStart + seconds(Deno.env.get("ERSATZRS_REMOTE_STREAM_SEEK") ?? "0");
if (fragmentEnd !== undefined && fragmentEnd <= absoluteSeek) {
  throw new Error("the fragment ends before the requested seek position");
}
const downloaderArgs = [`-ss ${absoluteSeek}`];
if (fragmentEnd !== undefined) downloaderArgs.push(`-t ${fragmentEnd - absoluteSeek}`);

const command = new Deno.Command(ytDlp, {
  args: [
    "--no-config", "--no-update", "--quiet", "--no-playlist",
    "--ffmpeg-location", ffmpeg,
    "--downloader", "ffmpeg",
    "--downloader-args", `ffmpeg_i:${downloaderArgs.join(" ")}`,
    "--hls-use-mpegts",
    // Prefer an adaptive manifest. A progressive rendition is served from a
    // media URL bound to the requesting player client, which the managed
    // FFmpeg downloader is refused when it fetches that URL itself; the
    // manifest formats carry no such binding. The progressive renditions stay
    // as fallbacks for sources that publish nothing else.
    //
    // The manifest legs pair a video-only with an audio-only rendition instead
    // of asking for one combined stream. Providers are dropping muxed
    // renditions: YouTube now publishes its manifest and progressive formats
    // as separate video-only and audio-only entries, so every combined
    // selector fails outright with "Requested format is not available" and the
    // add-on cannot play anything. yt-dlp merges the pair through the managed
    // FFmpeg runtime, and --hls-use-mpegts keeps that merge streamable to
    // stdout. Preferring avc1 keeps the consumer pipeline off the VP9 rendition
    // the provider marks Premium. The combined legs stay behind them for the
    // sources that still publish one.
    "--format", [
      "bestvideo[protocol^=m3u8][vcodec^=avc1]+bestaudio[protocol^=m3u8]",
      "bestvideo[protocol^=m3u8]+bestaudio[protocol^=m3u8]",
      "best[protocol^=m3u8][vcodec!=none][acodec!=none]",
      "best[ext=mp4][vcodec*=avc1][acodec*=mp4a]",
      "best[acodec!=none][vcodec!=none]",
    ].join("/"),
    "--output", "-",
    url.toString(),
  ],
  stdin: "null",
  stdout: "inherit",
  stderr: "inherit",
});
const status = await command.spawn().status;
Deno.exit(status.code);
