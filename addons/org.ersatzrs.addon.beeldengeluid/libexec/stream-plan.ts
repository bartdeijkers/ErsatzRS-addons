// Turn one getProgramStreamById Server Action response into an ordered
// playback plan.
//
// A Schatkamer episode that was archived across several analogue carriers is
// published as several streams under one episode ID. They form one continuous
// programme: the concatenated timeline is what the episode duration, the
// operator's seek position, and any authored chapter bounds all refer to.
// This module owns that mapping so neither platform entrypoint repeats it.
//
// The archive also holds repeat digitisations of the same carrier under one
// episode. They are indistinguishable from genuine parts except that their
// durations nearly match, so collapsing them is opt-in through the
// DUPLICATE_TOLERANCE_SECONDS setting and off by default.
//
// Input:  the response body, plus EPISODE_URL and SEEK_POSITION.
// Output: one tab-separated row per part that has to play, in playout order:
//           <variant url> <cookie header> <-ss> <-t> <-output_ts_offset>
//         All three timing columns are expressed in seconds. An unbounded
//         part reports "-" rather than an empty column, because cmd.exe
//         collapses adjacent delimiters and would shift the later columns.

const STREAM_HOST = "sk-video.cdn.beeldengeluid.nl";
const TOLERANCE_SETTING = "ERSATZRS_ADDON_SETTING_DUPLICATE_TOLERANCE_SECONDS";

interface Variant {
  url: string;
  pixels: number;
  bandwidth: number;
}

interface ProviderStream {
  playoutOrder: number;
  // Where this part's programme content begins inside its own asset. Some
  // carriers were digitised with leader before the programme starts, so a
  // part's timeline position is not necessarily its asset's position.
  startSeconds: number;
  durationSeconds?: number;
  url: string;
  cookie: string;
  // Set when this part stands in for a group of near-identical copies. Its
  // own length may differ from the group's by a few seconds, so playback is
  // bounded to the length the episode duration was built from.
  boundSeconds?: number;
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

// A master playlist lists its renditions smallest first, and FFmpeg maps the
// first video stream it finds, so playing the master directly would always
// pick the smallest picture. Resolve the largest rendition instead.
const variantCache = new Map<string, Variant | undefined>();

async function bestVariant(
  master: string,
  cookie: string,
): Promise<Variant | undefined> {
  if (variantCache.has(master)) return variantCache.get(master);
  let chosen: Variant | undefined;
  try {
    const curl = Deno.env.get("CURL_BIN")?.trim() ||
      (Deno.build.os === "windows" ? "curl.exe" : "curl");
    const result = await new Deno.Command(curl, {
      args: [
        "--fail", "--silent", "--show-error", "--location", "--max-redirs", "5",
        "--proto", "=https", "--proto-redir", "=https",
        "--connect-timeout", "10", "--max-time", "20",
        "--header", `Cookie: ${cookie}`,
        master,
      ],
      stdin: "null",
      stdout: "piped",
      stderr: "null",
    }).output();
    if (result.success) {
      const playlist = new TextDecoder().decode(result.stdout);
      const lines = playlist.split(/\r?\n/);
      for (const [index, line] of lines.entries()) {
        if (!line.startsWith("#EXT-X-STREAM-INF:")) continue;
        const target = lines[index + 1]?.trim();
        if (!target || target.startsWith("#")) continue;
        const size = line.match(/RESOLUTION=(\d+)x(\d+)/i);
        const rate = line.match(/BANDWIDTH=(\d+)/i);
        const candidate: Variant = {
          url: new URL(target, master).toString(),
          pixels: size ? Number(size[1]) * Number(size[2]) : 0,
          bandwidth: rate ? Number(rate[1]) : 0,
        };
        if (
          !chosen || candidate.pixels > chosen.pixels ||
          (candidate.pixels === chosen.pixels &&
            candidate.bandwidth > chosen.bandwidth)
        ) {
          chosen = candidate;
        }
      }
    }
  } catch {
    chosen = undefined;
  }
  if (!chosen) {
    console.error(
      `beeldengeluid: could not read the renditions of ${master}; ` +
        "playing the master playlist as published",
    );
  }
  variantCache.set(master, chosen);
  return chosen;
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
        startSeconds: typeof stream.start === "number" && stream.start > 0
          ? stream.start
          : 0,
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
    recovered.push({
      playoutOrder: recovered.length,
      startSeconds: 0,
      ...signedStream(row),
    });
  }
  if (!recovered.length) throw new Error("no signed HLS stream URL was found");
  return recovered;
}

// Group parts whose durations differ by no more than the operator's tolerance.
// Copies of one carrier land within a few seconds of each other while genuine
// parts of an episode rarely do, but that is a likeness test, not a fact the
// provider states -- hence the opt-in.
async function withoutDuplicates(
  streams: ProviderStream[],
  tolerance: number,
): Promise<ProviderStream[]> {
  const groups: ProviderStream[][] = [];
  for (const stream of streams) {
    const group = groups.find((candidate) =>
      candidate[0].durationSeconds !== undefined &&
      stream.durationSeconds !== undefined &&
      Math.abs(candidate[0].durationSeconds - stream.durationSeconds) <=
        tolerance
    );
    if (group) group.push(stream);
    else groups.push([stream]);
  }
  const kept: ProviderStream[] = [];
  for (const group of groups) {
    // The episode duration is built from the first copy in playout order, so
    // the timeline stays computable without reading any rendition.
    const boundSeconds = group[0].durationSeconds;
    if (group.length === 1) {
      kept.push(group[0]);
      continue;
    }
    const ranked = [];
    for (const copy of group) {
      const variant = await bestVariant(copy.url, copy.cookie);
      ranked.push({ copy, variant });
    }
    ranked.sort((left, right) =>
      (right.variant?.pixels ?? 0) - (left.variant?.pixels ?? 0) ||
      (right.variant?.bandwidth ?? 0) - (left.variant?.bandwidth ?? 0) ||
      (right.copy.durationSeconds ?? 0) - (left.copy.durationSeconds ?? 0) ||
      left.copy.playoutOrder - right.copy.playoutOrder
    );
    const winner = ranked[0].copy;
    console.error(
      `beeldengeluid: collapsed ${group.length} copies of a ${boundSeconds}s ` +
        `part; kept playout order ${winner.playoutOrder}`,
    );
    // The kept copy stands in for the group, so it takes the group's place on
    // the timeline and the group's length in both roles. Its own playout
    // position would move the part to wherever that copy happened to sit.
    kept.push({
      ...winner,
      playoutOrder: group[0].playoutOrder,
      durationSeconds: boundSeconds,
      boundSeconds,
    });
  }
  return kept.sort((left, right) => left.playoutOrder - right.playoutOrder);
}

function plan(
  streams: ProviderStream[],
  windowStart: number,
  windowEnd: number | undefined,
): PlannedPart[] {
  if (streams.some((stream) => stream.durationSeconds === undefined)) {
    return streams.map((stream, index) => ({
      ...stream,
      seekSeconds: stream.startSeconds + (index === 0 ? windowStart : 0),
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
    const limits = [
      windowEnd === undefined ? undefined : Math.min(partEnd, windowEnd) - from,
      // A copy kept for a group may run a little longer than the length the
      // timeline reserved for it, so it is trimmed to what was reserved.
      stream.boundSeconds === undefined ? undefined : partEnd - from,
    ].filter((limit): limit is number => limit !== undefined);
    parts.push({
      ...stream,
      // Seek within the asset, which is the part's own leader plus how far
      // into the part the requested position falls.
      seekSeconds: stream.startSeconds + (from - partStart),
      durationLimit: limits.length ? Math.min(...limits) : undefined,
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

function tolerance(): number {
  const configured = Deno.env.get(TOLERANCE_SETTING)?.trim();
  if (!configured) return 0;
  if (!/^\d+$/.test(configured)) {
    throw new DefinitionError(
      "the duplicate part tolerance must be whole seconds",
    );
  }
  return Number(configured);
}

async function main(): Promise<void> {
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
  const collapse = tolerance();
  const streams = collapse > 0
    ? await withoutDuplicates(providerStreams(rows), collapse)
    : providerStreams(rows);
  const parts = plan(streams, windowStart, fragmentEnd);
  const lines = [];
  for (const part of parts) {
    const variant = await bestVariant(part.url, part.cookie);
    lines.push([
      variant?.url ?? part.url,
      part.cookie,
      number(part.seekSeconds),
      part.durationLimit === undefined ? "-" : number(part.durationLimit),
      // Offsetting by zero is a no-op, so a plan that could not establish a
      // timeline still reports a usable column.
      number(part.timestampOffset ?? 0),
    ].join("\t"));
  }
  console.log(lines.join("\n"));
}

try {
  await main();
} catch (error) {
  fail(error);
}
