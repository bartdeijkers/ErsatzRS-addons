import { join } from "node:path";
import { boundedCommand } from "./item-options.ts";

type ObjectValue = Record<string, unknown>;
type Interval = { start: number; end: number };

function object(value: unknown): ObjectValue {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("invalid playback data");
  return value as ObjectValue;
}

function milliseconds(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) throw new Error("invalid playback time");
  return value;
}

function seconds(value: number): string { return (value / 1000).toFixed(3); }

// Native FFmpeg writes this container identifier once per invocation. Only the
// first belongs in the joined stream; retain all subsequent native packets.
export function nativeNutSection(dropIdentifier: boolean): TransformStream<Uint8Array, Uint8Array> {
  const identifier = new TextEncoder().encode("nut/multimedia container\0");
  let matched = 0;
  return new TransformStream({
    transform(chunk, controller) {
      let consumed = 0;
      while (matched < identifier.length && consumed < chunk.length) {
        if (chunk[consumed++] !== identifier[matched++]) throw new Error("invalid native media identifier");
        if (matched === identifier.length && !dropIdentifier) controller.enqueue(identifier);
      }
      if (consumed < chunk.length) controller.enqueue(chunk.subarray(consumed));
    },
    flush() {
      if (matched !== identifier.length) throw new Error("truncated native media identifier");
    },
  });
}

// The host owns the process group/job and its cancellation lease. Media uses
// bounded stream backpressure, retaining only the fixed identifier above.
async function streamSection(executable: string, args: string[], timeout: number, dropIdentifier: boolean): Promise<void> {
  const child = new Deno.Command(executable, { args, stdin: "null", stdout: "piped", stderr: "piped" }).spawn();
  const controller = new AbortController();
  const kill = () => {
    controller.abort();
    try { child.kill("SIGKILL"); } catch { /* Already exited. */ }
  };
  let expired = false;
  const timer = setTimeout(() => { expired = true; kill(); }, timeout);
  let size = 0;
  const diagnostics = (async () => {
    for await (const chunk of child.stderr) {
      size += chunk.length;
      if (size > 4 * 1024 * 1024) { kill(); throw new Error("playback diagnostic limit"); }
    }
  })();
  const media = child.stdout.pipeThrough(nativeNutSection(dropIdentifier)).pipeTo(Deno.stdout.writable, {
    preventClose: true, preventAbort: true, signal: controller.signal,
  });
  try {
    const [status] = await Promise.all([child.status, diagnostics, media]);
    if (!status.success || expired) throw new Error("section playback failed");
  } finally {
    clearTimeout(timer);
    kill();
    await Promise.allSettled([child.status, diagnostics, media]);
  }
}

/// Native yt-dlp owns extraction, authentication, protocol handling and seeks.
/// Only raw video/PCM NUT media crosses stdout; frozen cuts are never requeried.
export async function playIntervals(request: ObjectValue, source: string, common: string[]): Promise<void> {
  const allowed = ["source_url", "provider_id", "context_fingerprint", "source_duration_milliseconds", "options", "max_video_height", "retained_intervals_milliseconds"];
  if (Object.keys(request).some(key => !allowed.includes(key)) ||
    typeof request.provider_id !== "string" || !request.provider_id.trim() ||
    new TextEncoder().encode(request.provider_id).length > 384 || /[\x00-\x1f\x7f]/.test(request.provider_id) ||
    typeof request.context_fingerprint !== "string" || !/^[a-f0-9]{64}$/.test(request.context_fingerprint)) {
    throw new Error("invalid playback identity");
  }
  const duration = milliseconds(request.source_duration_milliseconds);
  if (!duration) throw new Error("invalid source duration");
  const ceiling = request.max_video_height ?? 1080;
  if (typeof ceiling !== "number" || !Number.isInteger(ceiling) || ceiling < 1 || ceiling > 4320) throw new Error("invalid playback ceiling");
  if (!Array.isArray(request.retained_intervals_milliseconds) || !request.retained_intervals_milliseconds.length ||
    request.retained_intervals_milliseconds.length > 1025) throw new Error("invalid playback intervals");
  let previous = 0;
  const intervals: Interval[] = request.retained_intervals_milliseconds.map(value => {
    const range = object(value);
    if (Object.keys(range).some(key => !["start", "end"].includes(key))) throw new Error("invalid playback interval");
    const start = milliseconds(range.start), end = milliseconds(range.end);
    if (start < previous || end <= start || end > duration) throw new Error("invalid playback interval");
    previous = end;
    return { start, end };
  });
  const executable = Deno.env.get("YT_DLP_BIN") || "yt-dlp";
  const ffmpeg = Deno.env.get("FFMPEG_BIN");
  if (!ffmpeg) throw new Error("managed FFmpeg unavailable");
  // Match the existing native playback preference, including separate manifest
  // legs; do not duplicate yt-dlp's URL/protocol implementation in the host.
  const height = `[height<=${ceiling}]`;
  const format = [
    `bestvideo[protocol^=m3u8][vcodec^=avc1]${height}+bestaudio[protocol^=m3u8]`,
    `bestvideo[protocol^=m3u8]${height}+bestaudio[protocol^=m3u8]`,
    `best[protocol^=m3u8][vcodec!=none][acodec!=none]${height}`,
    `best[ext=mp4][vcodec*=avc1][acodec*=mp4a]${height}`,
    `bestvideo${height}+bestaudio/best[acodec!=none][vcodec!=none]${height}`,
  ].join("/");
  // Native metadata includes captions and format tables. Keep it intact for
  // --load-info-json; only this extraction needs the larger bounded envelope.
  const metadata = await boundedCommand(executable, [
    ...common, "--simulate", "--skip-download", "--dump-single-json", "--format", format, source,
  ], 15_000, 16 * 1024 * 1024);
  if (!metadata.success) throw new Error("playback extraction failed");
  const info = object(JSON.parse(metadata.stdout));
  if (!["not_live", "post_live", "was_live"].includes(String(info.live_status)) || info.is_live === true ||
    typeof info.duration !== "number" || !Number.isFinite(info.duration) ||
    Math.round(info.duration * 1000) !== duration) throw new Error("source timing changed");
  const selected = Array.isArray(info.requested_formats) ? info.requested_formats.map(object) : [info];
  const videos = selected.filter(value => typeof value.vcodec === "string" && value.vcodec !== "none");
  // Native bestaudio may omit codec fields for manifest audio. The host probes
  // the actual raw NUT prefix before admitting audio; do not second-guess that
  // selection from incomplete serialized format metadata.
  if (videos.length !== 1) {
    throw new Error("unsupported playback layout");
  }
  const video = videos[0];
  // This raw transport prototype is SDR-only. Do not silently strip known HDR
  // transfer characteristics by forcing its pixels into an 8-bit format.
  if (typeof video.height !== "number" || video.height <= 0 || video.height > ceiling ||
    (video.dynamic_range !== undefined && video.dynamic_range !== null && video.dynamic_range !== "SDR") ||
    [video.color_transfer, info.color_transfer].some(value => ["smpte2084", "arib-std-b67"].includes(String(value)))) {
    throw new Error("unsupported playback video metadata");
  }
  const directory = await Deno.makeTempDir({ prefix: "ersatzrs-playback-" });
  try {
    const path = join(directory, "source.info.json");
    await Deno.writeTextFile(path, metadata.stdout, { mode: 0o600, createNew: true });
    let offset = 0;
    for (const interval of intervals) {
      const preroll = Math.min(interval.start, 2000);
      const length = interval.end - interval.start;
      await streamSection(executable, [
        ...common, "--no-simulate", "--load-info-json", path, "--format", format,
        "--ffmpeg-location", ffmpeg, "--downloader", "ffmpeg",
        "--download-sections", `*${seconds(interval.start - preroll)}-${seconds(interval.end)}`,
        "--force-keyframes-at-cuts", "--downloader-args", "ffmpeg_i:-threads 1",
        "--downloader-args", `ffmpeg_o:-threads 1 -xerror -ss ${seconds(preroll)} -c:v rawvideo -pix_fmt yuv420p -c:a pcm_f32le -f nut -write_index 0 -output_ts_offset ${seconds(offset)}`,
        "--output", "-",
      ], Math.min(2_147_483_647, length + 60_000), offset !== 0);
      offset += length;
    }
  } finally {
    await Deno.remove(directory, { recursive: true });
  }
}
