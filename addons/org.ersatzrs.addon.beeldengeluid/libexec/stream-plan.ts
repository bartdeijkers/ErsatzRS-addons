// Turn one getProgramStreamById Server Action response into an ordered
// playback plan.
//
// A Schatkamer episode that was archived across several analogue carriers is
// published as several streams under one episode ID. They form one continuous
// programme: the concatenated timeline is what the episode duration, the
// operator's seek position, and any authored chapter bounds all refer to.
// This module owns that mapping so neither platform entrypoint repeats it.
//
// Input:  the response body, plus EPISODE_URL and SEEK_POSITION.
// Output: one tab-separated row per part that has to play, in playout order:
//           <base url> <cookie header> <-ss> <-t> <-output_ts_offset>
//         All three timing columns are expressed in seconds. An unbounded
//         part reports "-" rather than an empty column, because cmd.exe
//         collapses adjacent delimiters and would shift the later columns.

const STREAM_HOST = "sk-video.cdn.beeldengeluid.nl";

interface ProviderStream {
  playoutOrder: number;
  durationSeconds?: number;
  url: string;
  cookie: string;
}

interface PlannedPart extends ProviderStream {
  seekSeconds: number;
  durationLimit?: number;
  timestampOffset?: number;
}

class DefinitionError extends Error {}

function fail(error: unknown): never {
  const message = error instanceof Error ? error.message : String(error);
  console.error(`beeldengeluid: ${message}`);
  Deno.exit(error instanceof DefinitionError ? 64 : 69);
}

function seconds(value: string): number {
  if (/^\d+(?:\.\d+)?$/.test(value)) return Number(value);
  const parts = value.split(":");
  if (parts.length !== 3 || parts.some((part) => !/^\d+(?:\.\d+)?$/.test(part))) {
    throw new DefinitionError("the seek timestamp is invalid");
  }
  return Number(parts[0]) * 3600 + Number(parts[1]) * 60 + Number(parts[2]);
}

// React flight rows are "<id>:<payload>". A text row declares its exact byte
// length ("<id>:T<hex>,"), so it is read by length rather than scanned for --
// a signed URL ends in base64 that can otherwise look like the next row.
function parseFlightRows(body: Uint8Array): Map<string, string> {
  const rows = new Map<string, string>();
  const decoder = new TextDecoder();
  let position = 0;
  while (position < body.length) {
    let cursor = position;
    while (cursor < body.length && body[cursor] !== 0x3a) cursor++;
    if (cursor >= body.length) break;
    const id = decoder.decode(body.subarray(position, cursor));
    if (!/^[0-9a-f]+$/i.test(id)) break;
    cursor += 1;
    if (body[cursor] === 0x54) {
      let lengthEnd = cursor + 1;
      while (lengthEnd < body.length && body[lengthEnd] !== 0x2c) lengthEnd++;
      const size = Number.parseInt(
        decoder.decode(body.subarray(cursor + 1, lengthEnd)),
        16,
      );
      if (!Number.isSafeInteger(size) || size < 0) break;
      const start = lengthEnd + 1;
      const end = start + size;
      if (end > body.length) break;
      rows.set(id, decoder.decode(body.subarray(start, end)));
      position = body[end] === 0x0a ? end + 1 : end;
    } else {
      let lineEnd = cursor;
      while (lineEnd < body.length && body[lineEnd] !== 0x0a) lineEnd++;
      rows.set(id, decoder.decode(body.subarray(cursor, lineEnd)));
      position = lineEnd + 1;
    }
  }
  return rows;
}

function signedStream(raw: string): { url: string; cookie: string } {
  const candidate = raw.trim().replaceAll("\\u0026", "&");
  let parsed: URL;
  try {
    parsed = new URL(candidate);
  } catch {
    throw new Error("the Server Action returned an unexpected stream URL");
  }
  if (
    parsed.protocol !== "https:" || parsed.hostname !== STREAM_HOST ||
    !parsed.pathname.endsWith(".m3u8")
  ) {
    throw new Error("the Server Action returned an unexpected stream URL");
  }
  const names = [
    "CloudFront-Policy",
    "CloudFront-Signature",
    "CloudFront-Key-Pair-Id",
  ];
  const cookie = names.map((name) => {
    const value = parsed.searchParams.get(name);
    if (!value) throw new Error(`the stream URL has no ${name}`);
    return `${name}=${value}`;
  }).join("; ");
  return { url: parsed.origin + parsed.pathname, cookie };
}

function providerStreams(rows: Map<string, string>): ProviderStream[] {
  for (const row of rows.values()) {
    if (!row.startsWith("{")) continue;
    let payload: { streams?: unknown };
    try {
      payload = JSON.parse(row);
    } catch {
      continue;
    }
    if (!Array.isArray(payload.streams)) continue;
    const streams: ProviderStream[] = [];
    for (const [index, entry] of payload.streams.entries()) {
      if (entry === null || typeof entry !== "object") continue;
      const stream = entry as Record<string, unknown>;
      const reference = typeof stream.url === "string" ? stream.url : undefined;
      if (!reference) continue;
      const raw = reference.startsWith("$")
        ? rows.get(reference.slice(1))
        : reference;
      if (raw === undefined) {
        throw new Error("a Schatkamer stream URL is missing from the response");
      }
      const duration = stream.durationNumber;
      streams.push({
        playoutOrder: typeof stream.playoutOrder === "number"
          ? stream.playoutOrder
          : index,
        durationSeconds: typeof duration === "number" && duration > 0
          ? Math.round(duration)
          : undefined,
        ...signedStream(raw),
      });
    }
    if (streams.length) {
      return streams.sort((left, right) => left.playoutOrder - right.playoutOrder);
    }
  }
  // The provider stopped publishing the stream index. Playing the signed URLs
  // in the order they arrive keeps the episode watchable; without per-part
  // durations the plan below degrades to seeking only the opening part.
  const recovered: ProviderStream[] = [];
  for (const row of rows.values()) {
    if (!row.includes(STREAM_HOST) || !row.includes(".m3u8")) continue;
    recovered.push({ playoutOrder: recovered.length, ...signedStream(row) });
  }
  if (!recovered.length) throw new Error("no signed HLS stream URL was found");
  return recovered;
}

function plan(
  streams: ProviderStream[],
  windowStart: number,
  windowEnd: number | undefined,
): PlannedPart[] {
  if (streams.some((stream) => stream.durationSeconds === undefined)) {
    return streams.map((stream, index) => ({
      ...stream,
      seekSeconds: index === 0 ? windowStart : 0,
      durationLimit: index === 0 && windowEnd !== undefined
        ? windowEnd - windowStart
        : undefined,
    }));
  }
  const parts: PlannedPart[] = [];
  let elapsed = 0;
  for (const stream of streams) {
    const partStart = elapsed;
    const partEnd = partStart + (stream.durationSeconds ?? 0);
    elapsed = partEnd;
    if (partEnd <= windowStart) continue;
    if (windowEnd !== undefined && partStart >= windowEnd) break;
    const from = Math.max(partStart, windowStart);
    parts.push({
      ...stream,
      seekSeconds: from - partStart,
      durationLimit: windowEnd === undefined
        ? undefined
        : Math.min(partEnd, windowEnd) - from,
      timestampOffset: from - windowStart,
    });
  }
  if (!parts.length) {
    throw new DefinitionError("the seek position is outside the episode");
  }
  return parts;
}

function number(value: number): string {
  return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(3)));
}

function main(): void {
  const [responsePath] = Deno.args;
  const episodeUrl = Deno.env.get("EPISODE_URL");
  if (!responsePath || !episodeUrl) {
    throw new DefinitionError("the playback environment is incomplete");
  }
  const url = new URL(episodeUrl);
  const rawStart = url.searchParams.get("start");
  const rawEnd = url.searchParams.get("end");
  if (rawStart !== null && !/^\d+$/.test(rawStart)) {
    throw new DefinitionError("fragment start must be whole seconds");
  }
  if (rawEnd !== null && !/^\d+$/.test(rawEnd)) {
    throw new DefinitionError("fragment end must be whole seconds");
  }
  if (rawEnd !== null && rawStart === null) {
    throw new DefinitionError("fragment end requires fragment start");
  }
  const fragmentStart = rawStart === null ? 0 : Number(rawStart);
  const fragmentEnd = rawEnd === null ? undefined : Number(rawEnd);
  if (fragmentEnd !== undefined && fragmentEnd <= fragmentStart) {
    throw new DefinitionError("fragment end must be after fragment start");
  }
  const windowStart = fragmentStart +
    seconds(Deno.env.get("SEEK_POSITION") || "0");
  if (fragmentEnd !== undefined && fragmentEnd <= windowStart) {
    throw new DefinitionError("the seek position is outside the fragment");
  }
  const rows = parseFlightRows(Deno.readFileSync(responsePath));
  const parts = plan(providerStreams(rows), windowStart, fragmentEnd);
  const lines = parts.map((part) =>
    [
      part.url,
      part.cookie,
      number(part.seekSeconds),
      part.durationLimit === undefined ? "-" : number(part.durationLimit),
      // Offsetting by zero is a no-op, so a plan that could not establish a
      // timeline still reports a usable column.
      number(part.timestampOffset ?? 0),
    ].join("\t")
  );
  console.log(lines.join("\n"));
}

try {
  main();
} catch (error) {
  fail(error);
}
