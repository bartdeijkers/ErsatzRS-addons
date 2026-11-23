// remote-stream.play.v1: stream one archive.org programme to standard output.
//
// The Archive serves plain files with byte-range support, so the managed
// FFmpeg reads the chosen file directly and remuxes it without re-encoding.
// ErsatzRS probes the container from the bytes it receives.

import { spawn } from "node:child_process";
import {
  downloadUrl,
  type Fetcher,
  fetchJson,
  itemAvailability,
  itemMetadata,
  parseSource,
  type Programme,
  programmes,
  ProviderError,
  USER_AGENT,
} from "./archive.mts";

/// Accept the host's seek value (`0`, seconds, or `HH:MM:SS.fff`) and return
/// it in a form FFmpeg parses, or undefined for the start of the programme.
export function seekArgument(raw: string | undefined): string | undefined {
  const value = (raw ?? "").trim();
  if (!value || value === "{seek}") return undefined;
  if (/^\d+(\.\d+)?$/.test(value)) return Number(value) > 0 ? value : undefined;
  if (/^\d+:\d{1,2}:\d{1,2}(\.\d+)?$/.test(value)) {
    return /^0+:0+:0+(\.0+)?$/.test(value) ? undefined : value;
  }
  throw new ProviderError("invalid-seek", "The seek position is invalid.", 64);
}

export type PlaybackPlan = {
  identifier: string;
  programme: Programme;
  input: string;
  container: "mpegts" | "matroska";
};

export async function planPlayback(sourceUrl: string, fetcher: Fetcher = fetchJson): Promise<PlaybackPlan> {
  const source = parseSource(sourceUrl);
  if (source.kind !== "details") {
    throw new ProviderError("unsupported-url", "Playback needs an archive.org item link.", 64);
  }
  const document = await itemMetadata(source.identifier, fetcher);
  const state = itemAvailability(document);
  if (state.availability === "unavailable") {
    throw new ProviderError(
      state.reason === "content_restricted" ? "content-restricted" : "item-unavailable",
      "This archive.org item is no longer publicly playable.",
      69,
    );
  }
  const found = programmes(document.files);
  const programme = source.file === undefined
    ? found[0]
    : found.find((candidate) => candidate.original === source.file || candidate.playable === source.file);
  if (!programme) {
    throw new ProviderError("no-video", "No playable video was found in this archive.org item.", 69);
  }
  return {
    identifier: source.identifier,
    programme,
    input: downloadUrl(source.identifier, programme.playable),
    // MPEG-TS carries H.264/AAC from MP4-family files; anything else (Ogg
    // Theora, WebM, MPEG-2 program streams) is remuxed into Matroska.
    container: /\.(mp4|m4v|mov)$/i.test(programme.playable) ? "mpegts" : "matroska",
  };
}

export function ffmpegArguments(plan: PlaybackPlan, seek: string | undefined): string[] {
  return [
    "-nostdin",
    "-hide_banner",
    "-loglevel",
    "error",
    "-user_agent",
    USER_AGENT,
    "-rw_timeout",
    "30000000",
    "-reconnect",
    "1",
    "-reconnect_on_network_error",
    "1",
    "-reconnect_delay_max",
    "10",
    ...(seek === undefined ? [] : ["-ss", seek]),
    "-i",
    plan.input,
    "-map",
    "0:v:0",
    "-map",
    "0:a:0?",
    "-c",
    "copy",
    "-f",
    plan.container,
    "pipe:1",
  ];
}

export async function runPlay(env: (key: string) => string | undefined): Promise<number> {
  const url = env("ERSATZRS_REMOTE_STREAM_URL");
  if (!url) throw new ProviderError("missing-setting", "A remote stream URL is required.", 64);
  const ffmpeg = env("FFMPEG_BIN");
  if (!ffmpeg) throw new ProviderError("missing-command", "The managed FFmpeg runtime is unavailable.", 69);
  const seek = seekArgument(env("ERSATZRS_REMOTE_STREAM_SEEK"));
  const plan = await planPlayback(url);
  const child = spawn(ffmpeg, ffmpegArguments(plan, seek), { stdio: ["ignore", "inherit", "inherit"] });
  return await new Promise<number>((resolve, reject) => {
    child.once("error", () =>
      reject(new ProviderError("missing-command", "The managed FFmpeg runtime could not be started.", 69))
    );
    child.once("exit", (code, signal) => resolve(code ?? (signal ? 143 : 70)));
  });
}
