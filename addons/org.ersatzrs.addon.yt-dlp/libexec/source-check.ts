import { boundedCommand } from "./item-options.ts";

const SAMPLE_SIZE = 50;
const TIMEOUT_MS = 12_000;
const OUTPUT_BYTES = 1024 * 1024;
const REQUEST_BYTES = 64 * 1024;
const encoder = new TextEncoder();
type JsonObject = Record<string, unknown>;

function object(value: unknown): JsonObject {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("incomplete-extraction");
  }
  return value as JsonObject;
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function number(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? value
    : null;
}

// Do not derive an instant from a date or a relative/approximate date label.
function timestamp(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) &&
      value >= -62135596800 && value <= 253402300799
    ? value
    : null;
}

function normalized(entry: JsonObject, fallback: string | null) {
  const approximate = entry.approximate_date === true ||
    entry.approximate_timestamp === true;
  return {
    extractor: text(entry.extractor_key) ?? text(entry.ie_key) ??
      text(entry.extractor) ?? fallback,
    id: text(entry.id),
    title: text(entry.title),
    description: text(entry.description),
    timestamp: approximate ? null : timestamp(entry.timestamp),
    release_timestamp: approximate ? null : timestamp(entry.release_timestamp),
    duration: number(entry.duration),
    availability: text(entry.availability),
  };
}

async function digest(value: unknown): Promise<string> {
  const bytes = await crypto.subtle.digest(
    "SHA-256",
    encoder.encode(JSON.stringify(value)),
  );
  return Array.from(
    new Uint8Array(bytes),
    (byte) => byte.toString(16).padStart(2, "0"),
  ).join("");
}

export async function observation(
  source: string,
  value: unknown,
  previous: unknown,
  now = Date.now(),
) {
  const root = object(value);
  const list = root._type === "playlist" || root._type === "multi_video" ||
    Object.hasOwn(root, "entries");
  if (
    list && (!Array.isArray(root.entries) ||
      ![undefined, "playlist", "multi_video"].includes(root._type as string))
  ) {
    throw new Error("incomplete-extraction");
  }
  if (!list && root._type !== undefined && root._type !== "video") {
    throw new Error("incomplete-extraction");
  }
  const header = normalized(root, null);
  const entries = (list ? root.entries as unknown[] : [root])
    .slice(0, SAMPLE_SIZE).map((value) => {
      const entry = object(value);
      if (
        Object.hasOwn(entry, "entries") ||
        ![undefined, "video", "url", "url_transparent"].includes(
          entry._type as string,
        )
      ) {
        throw new Error("incomplete-extraction");
      }
      const item = normalized(entry, header.extractor);
      if (!item.id) throw new Error("incomplete-extraction");
      return item;
    });
  // Counts, view/like statistics, thumbnails, and signed media URLs are absent.
  const metadata = {
    ...header,
    channel_id: text(root.channel_id),
    channel: text(root.channel),
    uploader_id: text(root.uploader_id),
    uploader: text(root.uploader),
  };
  const binding = await digest(source);
  const validator = `yt-dlp-window-v1:${binding}:${await digest({
    metadata,
    entries,
  })}`;
  // Unknown versions, malformed validators, and validators from another source
  // are cold observations. Never trust them as evidence of unchanged content.
  const validPrevious = typeof previous === "string" &&
    /^yt-dlp-window-v1:[0-9a-f]{64}:[0-9a-f]{64}$/.test(previous);
  const instants = [
    ...new Set(
      entries.flatMap((item) =>
        [item.timestamp, item.release_timestamp].filter((seconds) =>
          seconds !== null && seconds * 1000 <= now
        ) as number[]
      ),
    ),
  ].sort((a, b) => b - a).slice(0, 16)
    .map((seconds) => new Date(seconds * 1000).toISOString());
  return {
    outcome: validPrevious && previous === validator ? "unchanged" : "changed",
    validator,
    ...(instants.length ? { source_updated_at: instants } : {}),
  };
}

export function probeArguments(source: string): string[] {
  return [
    "--no-config",
    "--no-update",
    "--no-plugin-dirs",
    "--no-cache-dir",
    "--quiet",
    "--flat-playlist",
    "--skip-download",
    "--simulate",
    "--dump-single-json",
    "--playlist-end",
    String(SAMPLE_SIZE),
    "--abort-on-error",
    "--socket-timeout",
    "5",
    "--retries",
    "0",
    "--extractor-retries",
    "0",
    "--fragment-retries",
    "0",
    "--",
    source,
  ];
}

async function request(): Promise<JsonObject> {
  const chunks: Uint8Array[] = [];
  let length = 0;
  for await (const chunk of Deno.stdin.readable) {
    length += chunk.length;
    if (length > REQUEST_BYTES) throw new Error("invalid-request");
    chunks.push(chunk);
  }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.length;
  }
  const input = object(
    JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)),
  );
  if (
    Object.keys(input).some((key) =>
      !["source_url", "validator"].includes(key)
    ) ||
    typeof input.source_url !== "string" ||
    encoder.encode(input.source_url).length > 8192
  ) {
    throw new Error("invalid-request");
  }
  const url = new URL(input.source_url);
  if (
    !["http:", "https:"].includes(url.protocol) || !url.hostname ||
    url.username || url.password
  ) throw new Error("invalid-request");
  return input;
}

function failure(code: string, permanent = false) {
  return {
    outcome: permanent ? "permanent_failure" : "transient_failure",
    code,
  };
}

if (import.meta.main) {
  const started = performance.now();
  // Includes stdin, subprocess pipes, parsing and hashing. The host owns the
  // process group/Job Object and removes descendants even after leader exit.
  const timer = setTimeout(() => {
    console.log(JSON.stringify(failure("source-check-timeout")));
    Deno.exit(0);
  }, TIMEOUT_MS);
  let result;
  try {
    let input;
    try {
      input = await request();
    } catch {
      console.log(
        JSON.stringify(failure("invalid-source-check-request", true)),
      );
      Deno.exit(0);
    }
    const output = await boundedCommand(
      Deno.env.get("YT_DLP_BIN") || "yt-dlp",
      probeArguments(input.source_url as string),
      Math.max(1, TIMEOUT_MS - (performance.now() - started) - 100),
      OUTPUT_BYTES,
    );
    if (!output.success) {
      result = failure("source-check-extraction-failed");
    } else {
      try {
        result = await observation(
          input.source_url as string,
          JSON.parse(output.stdout),
          input.validator,
        );
      } catch {
        result = failure("source-check-invalid-extraction");
      }
    }
  } catch {
    result = failure("source-check-execution-failed");
  } finally {
    clearTimeout(timer);
  }
  console.log(JSON.stringify(result));
}
