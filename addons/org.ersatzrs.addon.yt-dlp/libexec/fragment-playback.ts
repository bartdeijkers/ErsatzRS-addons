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
    "--format", "best[ext=mp4][vcodec*=avc1][acodec*=mp4a]/best[acodec!=none][vcodec!=none]",
    "--output", "-",
    url.toString(),
  ],
  stdin: "null",
  stdout: "inherit",
  stderr: "inherit",
});
const status = await command.spawn().status;
Deno.exit(status.code);
