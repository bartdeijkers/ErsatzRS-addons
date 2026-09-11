import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { basename, join, resolve } from "node:path";
import { boundedCommand, browserArguments, itemOptions } from "./item-options.ts";
import { playIntervals } from "./stream-playback.ts";

type Request = Record<string, unknown>;
const ytDlp = Deno.env.get("YT_DLP_BIN") || "yt-dlp";
const encoder = new TextEncoder();

function required(value: unknown): string {
  if (typeof value !== "string" || !value.trim() || /[\x00-\x1f\x7f]/.test(value)) {
    throw new Error("invalid request field");
  }
  return value;
}

function positive(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value <= 0) {
    throw new Error("invalid operation budget");
  }
  return value;
}

async function requestInput(maximumBytes = 1024 * 1024): Promise<Request> {
  const chunks: Uint8Array[] = [];
  let size = 0;
  for await (const chunk of Deno.stdin.readable) {
    size += chunk.length;
    if (size > maximumBytes) throw new Error("request too large");
    chunks.push(chunk);
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  const value = JSON.parse(new TextDecoder().decode(bytes));
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("invalid request");
  return value;
}

async function toolVersion(): Promise<string> {
  const result = await boundedCommand(ytDlp, ["--no-config", "--no-update", "--version"], 10_000, 4096);
  const version = result.stdout.trim();
  if (!result.success || !/^[A-Za-z0-9._-]{1,128}$/.test(version)) throw new Error("tool unavailable");
  return version;
}

function identity(request: Request, version: string) {
  const providerId = required(request.provider_id);
  const fingerprint = required(request.context_fingerprint);
  if (providerId.length > 1024 || !/^[a-f0-9]{64}$/.test(fingerprint) || request.tool_version !== version) {
    throw new Error("item context changed");
  }
  return { provider_id: providerId, context_fingerprint: fingerprint, tool_version: version };
}

function sourceUrl(request: Request): string {
  const source = required(request.source_url);
  const url = new URL(source);
  if (source.length > 8192 || !["http:", "https:"].includes(url.protocol) || url.username || url.password) {
    throw new Error("invalid source URL");
  }
  return source;
}

function providerArguments(request: Request): string[] {
  return [
    "--no-config", "--no-update", "--cache-dir", required(Deno.env.get("YT_DLP_CACHE_DIR")),
    "--quiet", "--no-progress", "--no-playlist", "--abort-on-error",
    ...browserArguments(request.options),
  ];
}

// Match only known failure classes. Never return diagnostic text, paths or headers.
function accessOutcome(stderr: string): string {
  if (/could not find.*(?:cookies|profile)|(?:cookies|profile).*(?:not found|does not exist)|no such file/i.test(stderr)) {
    return "profile_unavailable";
  }
  if (/database is locked|could not copy.*cookie|(?:cookie|profile).*(?:locked|being used)/i.test(stderr)
    || /(?:PermissionError|permission denied)[^\r\n]*\bcookies\.sqlite(?:['"\s]|$)/i.test(stderr)) {
    return "profile_locked";
  }
  if (/decrypt|keyring|keychain|DPAPI/i.test(stderr)) return "decryption_failed";
  if (/sign.?in|log.?in|private video|members.only|age.?restrict|not available|HTTP Error (?:401|403)|confirm.*bot/i.test(stderr)) {
    return "provider_restricted";
  }
  return "failed";
}

async function testAccess(request: Request, version: string): Promise<unknown> {
  const echo = identity(request, version);
  const result = await boundedCommand(ytDlp, [
    ...providerArguments(request), "--simulate", "--skip-download", "--print", "id", sourceUrl(request),
  ]);
  const outcome = result.success && result.stdout.trim() ? "accessible" : accessOutcome(result.stderr);
  const retry = result.stderr.match(/retry[- ]after[^0-9]{0,16}(\d{1,5})/i);
  return {
    ...echo, outcome,
    ...(outcome !== "accessible" && retry
      ? { retry_after_seconds: Math.max(1, Math.min(3600, Number(retry[1]))) }
      : {}),
  };
}

async function intervalMetadata(request: Request, version: string): Promise<unknown> {
  const echo = identity(request, version);
  if (!itemOptions(request.options).remove) throw new Error("interval removal not requested");
  // Strip chapter parameters only. Report whole-source coordinates; the host
  // clips them to the saved chapter window bound into context_fingerprint.
  const source = fragmentPreparation(sourceUrl(request)).source;
  const common = providerArguments(request);
  try {
    const result = await boundedCommand(ytDlp, [
      ...common, "--simulate", "--skip-download", "--dump-single-json",
      // An explicit selector avoids yt-dlp's default FFmpeg merge-capability probe.
      "--format", "bestvideo*+bestaudio/best",
      // In yt-dlp 2026.08.19, mark's "default" means all categories, whereas
      // remove's "default" excludes filler and the non-skippable categories.
      "--sponsorblock-mark", "all,-filler,-poi_highlight,-chapter", source,
    ]);
    if (!result.success) {
      const retry = result.stderr.match(/retry[- ]after[^0-9]{0,16}(\d{1,5})/i);
      return { ...echo, outcome: {
        kind: "failed",
        ...(retry ? { retry_after_seconds: Math.max(1, Math.min(3600, Number(retry[1]))) } : {}),
      } };
    }
    // after_filter --print runs BEFORE SponsorBlock. dump-single-json observes
    // the completed preprocessing result, and only a successful exit counts.
    const info = JSON.parse(result.stdout);
    if (!info || typeof info !== "object" || Array.isArray(info)) throw new Error("invalid metadata");
    if (!["not_live", "post_live", "was_live"].includes(info.live_status) || info.is_live === true ||
      !Object.hasOwn(info, "sponsorblock_chapters")) {
      return { ...echo, outcome: { kind: "unsupported" } };
    }
    function milliseconds(value: unknown): number {
      if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
        throw new Error("invalid interval time");
      }
      const converted = Math.round(value * 1000);
      if (!Number.isSafeInteger(converted)) throw new Error("interval time exceeds bounds");
      return converted;
    }
    const duration = milliseconds(info.duration);
    const chapters = info.sponsorblock_chapters;
    if (duration <= 0 || !Array.isArray(chapters) || chapters.length > 1024) {
      throw new Error("invalid interval metadata");
    }
    const intervals = chapters.map((chapter: unknown) => {
      if (!chapter || typeof chapter !== "object" || Array.isArray(chapter)) {
        throw new Error("invalid interval");
      }
      const entry = chapter as Record<string, unknown>;
      const start = milliseconds(entry.start_time);
      const end = milliseconds(entry.end_time);
      if (start >= end || end > duration) throw new Error("invalid interval bounds");
      return { start, end };
    });
    const output = { ...echo, outcome: {
      kind: "ready", source_duration_milliseconds: duration,
      excluded_intervals_milliseconds: intervals,
    } };
    if (encoder.encode(JSON.stringify(output)).length + 1 > 64 * 1024) {
      throw new Error("interval result exceeds bounds");
    }
    return output;
  } catch {
    // Malformed/oversized metadata and process failures never become empty cuts.
    return { ...echo, outcome: { kind: "failed" } };
  }
}

async function stagingBytes(directory: string): Promise<number> {
  let bytes = 0;
  for await (const entry of Deno.readDir(directory)) {
    const path = join(directory, entry.name);
    const info = await Deno.lstat(path);
    if (info.isSymlink || (!info.isFile && !info.isDirectory)) throw new Error("invalid staging entry");
    bytes += info.isDirectory ? await stagingBytes(path) : info.size;
  }
  return bytes;
}

function subtitleLanguages(value: unknown, allowEmpty = false): string[] {
  if (value === undefined && allowEmpty) return [];
  if (!Array.isArray(value) || value.length > 2 || (!allowEmpty && !value.length) ||
    value.some((language) => typeof language !== "string" || !validSubtitleLanguage(language))) {
    throw new Error("invalid requested subtitle languages");
  }
  const languages = value as string[];
  if (new Set(languages.map(logicalLanguage)).size !== languages.length) {
    throw new Error("duplicate requested subtitle language");
  }
  return languages;
}

function logicalLanguage(value: string): string { return value.split("-")[0].toLowerCase(); }

function validSubtitleLanguage(value: string): boolean {
  return value.length <= 35 && /^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8})*$/.test(value) &&
    !["all", "und", "zxx", "mul"].includes(logicalLanguage(value));
}

function selectedManualLanguages(info: Record<string, unknown>, requested: string[]): string[] {
  // yt-dlp keeps automatic captions and machine translations in automatic_captions.
  // Choose a single manual track per logical language, never the extractor's full map.
  const subtitles = info.subtitles;
  if (subtitles === undefined || subtitles === null) return [];
  if (typeof subtitles !== "object" || Array.isArray(subtitles)) throw new Error("invalid subtitle metadata");
  const available = Object.keys(subtitles).filter((language) => validSubtitleLanguage(language) &&
    Array.isArray((subtitles as Record<string, unknown>)[language]) &&
    ((subtitles as Record<string, unknown[]>)[language]).length > 0).sort();
  return requested.flatMap((language) => {
    const exact = available.find((actual) => actual.toLowerCase() === language.toLowerCase());
    const primary = available.find((actual) => actual.toLowerCase() === logicalLanguage(language));
    const regional = available.find((actual) => logicalLanguage(actual) === logicalLanguage(language));
    const chosen = exact ?? primary ?? regional;
    return chosen ? [chosen] : [];
  });
}

function subtitleArguments(languages: string[]): string[] {
  if (!languages.length) return ["--no-write-subs", "--no-write-auto-subs"];
  // Restricted anchored expressions: tags have already rejected regex punctuation.
  return ["--write-subs", "--no-write-auto-subs", "--sub-langs",
    languages.map((language) => "^" + language + "$").join(","),
    "--sub-format", "srt/vtt/ttml/ass/ssa", "--convert-subs", "srt"];
}

async function subtitleArtifacts(
  value: unknown, languages: string[], stage: string, maximumFile: number,
  remaining: () => number, timeline: "source" | "prepared",
): Promise<Record<string, unknown>[]> {
  if (value === undefined || value === null) return [];
  if (typeof value !== "object" || Array.isArray(value)) throw new Error("invalid subtitle result");
  const artifacts: Record<string, unknown>[] = [];
  for (const [language, raw] of Object.entries(value)) {
    if (!languages.includes(language) || !raw || typeof raw !== "object" || Array.isArray(raw)) {
      throw new Error("unrequested subtitle result");
    }
    const subtitle = raw as Record<string, unknown>;
    if (subtitle.ext !== "srt") throw new Error("subtitle conversion did not produce SRT");
    const path = resolve(required(subtitle.filepath));
    const relativePath = basename(path);
    if (path !== join(stage, relativePath) || !/^(?:prepared|subtitles)\.[A-Za-z0-9-]+\.srt$/.test(relativePath)) {
      throw new Error("invalid subtitle path");
    }
    const fileInfo = await Deno.lstat(path);
    if (!fileInfo.isFile || fileInfo.isSymlink || fileInfo.size <= 0 || fileInfo.size > maximumFile) {
      throw new Error("subtitle exceeds budget");
    }
    const digest = createHash("sha256");
    const file = await Deno.open(path, { read: true });
    for await (const chunk of file.readable) { remaining(); digest.update(chunk); }
    artifacts.push({ language, format: "srt", provenance: "manual", timeline,
      relative_path: relativePath, byte_length: fileInfo.size, sha256: digest.digest("hex") });
  }
  return artifacts;
}

async function subtitles(request: Request, version: string): Promise<unknown> {
  const echo = identity(request, version);
  const requested = subtitleLanguages(request.requested_languages);
  const timeout = positive(request.timeout_seconds);
  if (timeout > 3600) throw new Error("invalid timeout");
  const deadline = Date.now() + timeout * 1000;
  const remaining = () => {
    const value = deadline - Date.now();
    if (value <= 0) throw new Error("subtitle acquisition timed out");
    return value;
  };
  const maximumFile = positive(request.maximum_file_bytes);
  const maximumStaging = positive(request.maximum_staging_bytes);
  if (maximumStaging < maximumFile) throw new Error("invalid staging budget");
  const stage = resolve(required(request.staging_directory));
  const stageInfo = await Deno.lstat(stage);
  if (!stageInfo.isDirectory || stageInfo.isSymlink) throw new Error("invalid staging directory");
  for await (const _entry of Deno.readDir(stage)) throw new Error("staging directory must be empty");
  // Keep complete source coordinates. The host owns streamed chapter/SponsorBlock mapping.
  const source = fragmentPreparation(sourceUrl(request)).source;
  const common = providerArguments(request);
  const probe = await boundedCommand(ytDlp, [
    ...common, "--simulate", "--skip-download", "--dump-single-json",
    "--format", "bestvideo*+bestaudio/best", "--no-sponsorblock", source,
  ], Math.min(remaining(), 60_000));
  if (!probe.success) throw new Error("subtitle metadata probe failed");
  const info = JSON.parse(probe.stdout);
  if (!info || typeof info !== "object" || Array.isArray(info)) throw new Error("invalid subtitle metadata");
  const languages = selectedManualLanguages(info, requested);
  if (!languages.length) return { ...echo, subtitles: [] };
  const result = await boundedCommand(ytDlp, [
    ...common, "--no-simulate", "--skip-download", "--ffmpeg-location", required(Deno.env.get("FFMPEG_BIN")),
    "--format", "bestvideo*+bestaudio/best",
    "--max-filesize", String(maximumFile), "--no-overwrites", "--no-sponsorblock",
    "--no-write-info-json", "--no-write-thumbnail", ...subtitleArguments(languages),
    "--output", join(stage, "subtitles.%(ext)s"),
    // skip_download runs before_dl conversion and MoveFiles, but not after_move PPs.
    "--print", "after_video:%(requested_subtitles)j", source,
  ], remaining(), 64 * 1024);
  if (!result.success) throw new Error("subtitle acquisition failed");
  if (await stagingBytes(stage) > maximumStaging) throw new Error("subtitle staging exceeds budget");
  const artifacts = await subtitleArtifacts(JSON.parse(result.stdout.trim()), languages,
    stage, maximumFile, remaining, "source");
  return { ...echo, subtitles: artifacts };
}

function fragmentPreparation(source: string) {
  // Match the start/end query convention used by fragment-playback.ts. These
  // are original-source coordinates, never offsets in an already cut artifact.
  function seconds(value: string): number {
    let result: number;
    if (/^\d+(?:\.\d+)?$/.test(value)) {
      result = Number(value);
    } else {
      const parts = value.split(":");
      if (parts.length !== 3 || parts.some((part) => !/^\d+(?:\.\d+)?$/.test(part))) {
        throw new Error("invalid fragment boundary");
      }
      result = Number(parts[0]) * 3600 + Number(parts[1]) * 60 + Number(parts[2]);
    }
    if (!Number.isFinite(result) || result < 0) throw new Error("invalid fragment boundary");
    return result;
  }
  const url = new URL(source);
  const start = url.searchParams.has("start") ? seconds(url.searchParams.get("start")!) : 0;
  const end = url.searchParams.has("end") ? seconds(url.searchParams.get("end")!) : undefined;
  if (end !== undefined && end <= start) throw new Error("empty fragment");
  url.searchParams.delete("start");
  url.searchParams.delete("end");
  const arguments_: string[] = [];
  if (start > 0) arguments_.push("--remove-chapters", `*0-${start}`);
  if (end !== undefined) arguments_.push("--remove-chapters", `*${end}-inf`);
  // yt-dlp 2026.08.19 parses time ranges separately but only registers
  // ModifyChaptersPP for a chapter regex or SponsorBlock. This impossible
  // pattern activates the native cutter without selecting any extra chapters
  // or enabling SponsorBlock when the operator has disabled it.
  if (arguments_.length) arguments_.push("--remove-chapters", "(?!)");
  return { source: url.toString(), start, arguments_ };
}

async function prepare(request: Request, version: string): Promise<unknown> {
  const echo = identity(request, version);
  const requestedLanguages = subtitleLanguages(request.requested_subtitle_languages, true);
  const remove = itemOptions(request.options).remove;
  const timeout = positive(request.timeout_seconds);
  if (timeout > 3600) throw new Error("invalid timeout");
  const deadline = Date.now() + timeout * 1000;
  const remaining = () => {
    const value = deadline - Date.now();
    if (value <= 0) throw new Error("preparation timed out");
    return value;
  };
  const maximumFile = positive(request.maximum_file_bytes);
  const maximumStaging = positive(request.maximum_staging_bytes);
  if (maximumStaging < maximumFile) throw new Error("invalid staging budget");
  const stage = resolve(required(request.staging_directory));
  const stageInfo = await Deno.lstat(stage);
  if (!stageInfo.isDirectory || stageInfo.isSymlink) throw new Error("invalid staging directory");
  for await (const _entry of Deno.readDir(stage)) throw new Error("staging directory must be empty");
  const height = request.max_video_height === undefined ? 1080 : positive(request.max_video_height);
  if (height > 4320) throw new Error("invalid height");
  const fragment = fragmentPreparation(sourceUrl(request));
  const source = fragment.source;
  const common = providerArguments(request);
  const format = `bestvideo[height<=${height}]+bestaudio/best[height<=${height}][vcodec!=none][acodec!=none]`;
  const probe = await boundedCommand(ytDlp, [
    ...common, "--simulate", "--skip-download", "--dump-single-json", "--format", format, source,
  ], Math.min(remaining(), 60_000));
  if (!probe.success) throw new Error("source probe failed");
  const info = JSON.parse(probe.stdout);
  if (!["not_live", "post_live", "was_live"].includes(info.live_status) || info.is_live === true) {
    throw new Error("preparation requires finite media");
  }
  if (typeof info.duration === "number" && info.duration > 0 && fragment.start >= info.duration) {
    throw new Error("fragment starts beyond the source");
  }
  const languages = selectedManualLanguages(info, requestedLanguages);
  // Standard yt-dlp processing: 404/no segments is a success, exhausted API
  // retries and FFmpeg errors remain failures. No --ignore-errors or stdout media.
  const download = await boundedCommand(ytDlp, [
    ...common, "--no-simulate", "--ffmpeg-location", required(Deno.env.get("FFMPEG_BIN")),
    "--no-plugin-dirs", "--plugin-dirs", fileURLToPath(new URL("./plugins", import.meta.url)),
    "--use-postprocessor", "ErsatzRSChapterGuard:when=before_dl",
    "--format", format, "--max-filesize", String(maximumFile), "--no-overwrites",
    "--no-write-info-json", "--no-write-thumbnail", ...subtitleArguments(languages),
    ...(remove ? ["--sponsorblock-remove", "default"] : ["--no-sponsorblock"]),
    "--merge-output-format", "mkv",
    // yt-dlp 2026.08.19 ModifyChaptersPP unions these ranges with SponsorBlock
    // cuts in original coordinates. --download-sections does not rebase them.
    ...fragment.arguments_,
    "--output", join(stage, "prepared.%(ext)s"),
    "--print", 'after_move:{"path":%(filepath)j,"format":%(format_id)j,"subtitles":%(requested_subtitles|{})j}', source,
  ], remaining(), 64 * 1024, { PYTHONDONTWRITEBYTECODE: "1", YTDLP_NO_PLUGINS: "" });
  // ModifyChaptersPP warns and leaves the original file when all content would
  // be removed. That successful process exit must not admit an uncut substitute.
  if (!download.success || /You have requested to remove the entire video/i.test(download.stderr)) {
    throw new Error("preparation failed");
  }
  const result = JSON.parse(download.stdout.trim());
  const path = resolve(required(result.path));
  const relativePath = basename(path);
  if (path !== join(stage, relativePath) || !/^prepared\.[a-zA-Z0-9]+$/.test(relativePath) ||
    typeof result.format !== "string" || !/^[A-Za-z0-9._+-]{1,128}$/.test(result.format)) {
    throw new Error("invalid prepared descriptor");
  }
  const fileInfo = await Deno.lstat(path);
  if (!fileInfo.isFile || fileInfo.isSymlink || fileInfo.size <= 0 || fileInfo.size > maximumFile ||
    await stagingBytes(stage) > maximumStaging) throw new Error("prepared file exceeds budget");
  const media = await boundedCommand(required(Deno.env.get("FFPROBE_BIN")), [
    "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", path,
  ], Math.min(remaining(), 30_000), 64 * 1024);
  if (!media.success) throw new Error("prepared media probe failed");
  const mediaInfo = JSON.parse(media.stdout);
  const duration = Math.round(Number(mediaInfo.format?.duration) * 1000);
  if (!Number.isSafeInteger(duration) || duration <= 0 ||
    !Array.isArray(mediaInfo.streams) || !mediaInfo.streams.some((stream: { codec_type: string }) => stream.codec_type === "video")) {
    throw new Error("invalid prepared media");
  }
  const digest = createHash("sha256");
  const file = await Deno.open(path, { read: true });
  for await (const chunk of file.readable) { remaining(); digest.update(chunk); }
  // yt-dlp converts in before_dl, then ModifyChaptersPP cuts video and supported
  // sidecars together. These descriptors are already on the prepared file clock.
  const artifacts = await subtitleArtifacts(result.subtitles, languages, stage, maximumFile, remaining, "prepared");
  return {
    ...echo, selected_format: result.format, relative_path: relativePath,
    byte_length: fileInfo.size, sha256: digest.digest("hex"), duration_milliseconds: duration,
    ...(artifacts.length ? { subtitles: artifacts } : {}),
  };
}

try {
  const request = await requestInput(Deno.args[0] === "play-intervals" ? 512 * 1024 : undefined);
  const version = Deno.args[0] === "play-intervals" ? "" : await toolVersion();
  let result: unknown;
  switch (Deno.args[0]) {
    case "runtime-info":
      if (Object.keys(request).length) throw new Error("invalid runtime request");
      result = { tool_version: version };
      break;
    case "test-access": result = await testAccess(request, version); break;
    case "interval-metadata": result = await intervalMetadata(request, version); break;
    case "play-intervals":
      await playIntervals(request, fragmentPreparation(sourceUrl(request)).source, providerArguments(request));
      Deno.exit(0);
      break;
    case "prepare": result = await prepare(request, version); break;
    case "subtitles": result = await subtitles(request, version); break;
    default: throw new Error("unsupported operation");
  }
  await Deno.stdout.write(encoder.encode(JSON.stringify(result) + "\n"));
} catch {
  // Never interpolate child errors or untrusted fields into provider diagnostics.
  console.error('{"code":"item-operation-failed","message":"The item operation failed or its context changed."}');
  Deno.exit(70);
}
