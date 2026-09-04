type JsonObject = Record<string, unknown>;

interface DiscoverRequest {
  source_url: string;
  record_capability: string;
  cursor?: string;
  limits: { max_items: number; max_output_bytes: number };
}

interface DiscoverV2Request extends DiscoverRequest {
  mode: "full" | "incremental";
  archive: {
    staged_path: string;
    generation: number;
    entry_count: number;
    sha256: string;
    max_bytes: number;
    max_entries: number;
  };
}

interface EnrichRequest {
  source_url: string;
  record_capability: string;
  provider_id: string;
  overview_fingerprint: string;
  item: JsonObject;
}

interface ProviderResult {
  success: boolean;
  stdout: string;
  stderr: string;
}

const encoder = new TextEncoder();
const decoder = new TextDecoder();
const ytDlp = Deno.env.get("YT_DLP_BIN")?.trim() || "yt-dlp";

function requiredEnvironment(name: string): string {
  const value = Deno.env.get(name)?.trim();
  if (!value) {
    throw new Error(`the ${name} environment variable is unavailable`);
  }
  return value;
}

const ytDlpCacheDir = requiredEnvironment("YT_DLP_CACHE_DIR");

function object(value: unknown): JsonObject | undefined {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as JsonObject
    : undefined;
}

function text(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function integer(value: unknown): number | undefined {
  return typeof value === "number" && Number.isSafeInteger(value)
    ? value
    : undefined;
}

function positiveInteger(value: unknown): number | undefined {
  const result = integer(value);
  return result !== undefined && result > 0 ? result : undefined;
}

function values(...candidates: unknown[]): string[] {
  const result: string[] = [];
  const seen = new Set<string>();
  for (
    const candidate of candidates.flatMap((value) =>
      Array.isArray(value) ? value : [value]
    )
  ) {
    const item = text(candidate);
    const key = item?.toLocaleLowerCase();
    if (!item || !key || seen.has(key)) continue;
    seen.add(key);
    result.push(item);
    if (result.length === 1024) break;
  }
  return result;
}

function safeHttpsUrl(value: unknown): string | undefined {
  const candidate = text(value);
  if (!candidate || encoder.encode(candidate).length > 2048) return undefined;
  try {
    const url = new URL(candidate);
    return url.protocol === "https:" && url.hostname && !url.username &&
        !url.password
      ? url.toString()
      : undefined;
  } catch {
    return undefined;
  }
}

function releaseDate(entry: JsonObject): string | undefined {
  const raw = text(entry.upload_date) ?? text(entry.release_date);
  if (!raw) return undefined;
  if (/^\d{8}$/.test(raw)) {
    return `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`;
  }
  return /^\d{4}-\d{2}-\d{2}$/.test(raw) ? raw : undefined;
}

function year(entry: JsonObject): number | undefined {
  const explicit = positiveInteger(entry.release_year) ??
    positiveInteger(entry.year);
  if (explicit) return explicit;
  const date = releaseDate(entry);
  return date ? Number(date.slice(0, 4)) : undefined;
}

function availability(value: unknown): "available" | "unavailable" | "unknown" {
  if (["public", "unlisted"].includes(String(value ?? ""))) return "available";
  if (
    ["private", "premium_only", "subscriber_only", "needs_auth"].includes(
      String(value ?? ""),
    )
  ) return "unavailable";
  return "unknown";
}

type AvailabilityReasonCode =
  | "authentication_required"
  | "content_restricted"
  | "unavailable";

function availabilityReasonCode(
  value: unknown,
): AvailabilityReasonCode | undefined {
  switch (String(value ?? "")) {
    case "needs_auth":
      return "authentication_required";
    case "private":
    case "premium_only":
    case "subscriber_only":
      return "content_restricted";
    default:
      return undefined;
  }
}

function failureAvailabilityReason(
  stderr: string,
): AvailabilityReasonCode | undefined {
  if (
    /age[- ]restricted|age restriction|confirm (?:your )?age|members-only|premium|subscriber|private/i
      .test(stderr)
  ) {
    return "content_restricted";
  }
  if (
    /needs? auth|authentication required|sign in|log in|login|cookies? (?:are )?required|use --cookies/i
      .test(stderr)
  ) {
    return "authentication_required";
  }
  if (/unavailable|removed|not available|deleted/i.test(stderr)) {
    return "unavailable";
  }
  return undefined;
}

function liveness(entry: JsonObject): "unknown" | "finite" | "live" {
  const liveStatus = text(entry.live_status);
  if (
    entry.is_live === true ||
    ["is_live", "is_upcoming"].includes(liveStatus ?? "")
  ) {
    return "live";
  }
  if (
    entry.is_live === false ||
    ["not_live", "post_live", "was_live"].includes(liveStatus ?? "") ||
    Number(entry.duration ?? 0) > 0
  ) return "finite";
  return "unknown";
}

function contentKind(entry: JsonObject): string {
  const source = values(
    entry.series && "ERSATZRS_TV",
    entry.episode && "ERSATZRS_TV",
    entry.artist && "ERSATZRS_MUSIC",
    entry.track && "ERSATZRS_MUSIC",
    entry.categories,
    entry.tags,
    entry.title,
  ).join(" ").toLocaleLowerCase();
  if (/advertisement|commercial|reclame/.test(source)) return "other_video";
  if (
    /ersatzrs_music|music video|videoclip|concert|music|muziek/.test(source)
  ) {
    return "music_video";
  }
  if (/movie|film|speelfilm/.test(source)) return "movie";
  if (/ersatzrs_tv/.test(source)) return "television_episode";
  return "auto";
}

function artwork(entry: JsonObject, role: "fanart" | "thumb"): JsonObject[] {
  const thumbnails = Array.isArray(entry.thumbnails)
    ? [...entry.thumbnails].reverse().map(object).filter(
      Boolean,
    ) as JsonObject[]
    : [];
  const candidates = [
    ...thumbnails,
    {
      url: entry.thumbnail,
      width: entry.thumbnail_width,
      height: entry.thumbnail_height,
    },
  ];
  for (const candidate of candidates) {
    const url = safeHttpsUrl(candidate.url);
    if (!url) continue;
    const result: JsonObject = { url, role };
    const width = positiveInteger(candidate.width);
    const height = positiveInteger(candidate.height);
    if (width) result.width = width;
    if (height) result.height = height;
    return [result];
  }
  return [];
}

function people(entry: JsonObject): JsonObject[] {
  const result: JsonObject[] = [];
  const channel = text(entry.channel);
  const uploader = text(entry.uploader);
  if (channel) result.push({ name: channel, role: "Channel", order: 0 });
  if (
    uploader && uploader.toLocaleLowerCase() !== channel?.toLocaleLowerCase()
  ) {
    result.push({ name: uploader, role: "Uploader", order: result.length });
  }
  return result;
}

function metadata(entry: JsonObject, collection?: string): JsonObject {
  const channel = text(entry.channel) ?? text(entry.uploader);
  const date = releaseDate(entry);
  const season = integer(entry.season_number);
  const episode = positiveInteger(entry.episode_number);
  return {
    title: text(entry.title),
    plot: text(entry.description),
    show_title: text(entry.series),
    season: season !== undefined && season >= 0 ? season : undefined,
    episode,
    year: year(entry),
    release_date: date,
    genres: values(entry.categories),
    tags: values(entry.tags),
    languages: values(entry.language),
    people: people(entry),
    artists: values(entry.artists, entry.artist, entry.creators, entry.creator),
    original_broadcasters: values(channel),
    broadcasters: values(channel),
    collection: text(entry.album) ?? text(collection),
    artwork: artwork(entry, "thumb"),
    guids: text(entry.id) ? [`yt-dlp://${text(entry.id)}`] : [],
  };
}

function providerItem(
  entry: JsonObject,
  rank: number,
  collection?: string,
): JsonObject | undefined {
  const id = text(entry.id);
  const title = text(entry.title);
  const sourceUrl = safeHttpsUrl(entry.webpage_url) ??
    safeHttpsUrl(entry.original_url) ??
    safeHttpsUrl(entry.url);
  if (!id || !title || !sourceUrl) return undefined;
  const state = availability(entry.availability);
  const reasonCode = availabilityReasonCode(entry.availability);
  const duration = Number(entry.duration);
  const row: JsonObject = {
    record_type: "item",
    provider_id: id,
    rank,
    display_title: title,
    title,
    year: year(entry),
    season: integer(entry.season_number),
    episode: positiveInteger(entry.episode_number),
    kind: "remote_stream",
    guids: [`yt-dlp://${id}`],
    source_url: sourceUrl,
    availability: state,
    availability_reason: state === "unavailable" ? "not_playable" : undefined,
    availability_reason_code: reasonCode,
    content_kind: contentKind(entry),
    duration_seconds: Number.isFinite(duration) && duration >= 0
      ? Math.round(duration)
      : undefined,
    liveness: liveness(entry),
    additional_image_urls: artwork(entry, "thumb").map((candidate) =>
      candidate.url
    ),
    metadata: metadata(entry, collection),
  };
  return row;
}

async function runProvider(arguments_: string[]): Promise<ProviderResult> {
  try {
    const result = await new Deno.Command(ytDlp, {
      args: ["--cache-dir", ytDlpCacheDir, ...arguments_],
      stdin: "null",
      stdout: "piped",
      stderr: "piped",
    }).output();
    return {
      success: result.success,
      stdout: decoder.decode(result.stdout),
      stderr: decoder.decode(result.stderr),
    };
  } catch (error) {
    return { success: false, stdout: "", stderr: String(error) };
  }
}

function retryAfter(stderr: string): number | undefined {
  const match = stderr.match(/retry[- ]after[^0-9]{0,16}(\d{1,5})/i);
  if (!match) return undefined;
  return Math.min(Number(match[1]), 86_400);
}

function emit(value: unknown): void {
  console.log(JSON.stringify(value));
}

function failure(stderr: string): void {
  const rateLimited = /(?:http error )?429|too many requests|rate.?limit/i.test(
    stderr,
  );
  emit({
    record_type: "outcome",
    outcome: "transient_failure",
    code: rateLimited ? "rate-limited" : "provider-request-failed",
    message: "The video provider request failed.",
    retry_after_seconds: retryAfter(stderr) ?? (rateLimited ? 60 : undefined),
  });
}

function parseProviderJson(result: ProviderResult): JsonObject {
  const parsed = object(JSON.parse(result.stdout));
  if (!parsed) throw new Error("yt-dlp returned no JSON object");
  return parsed;
}

function listRecord(
  request: DiscoverRequest,
  playlist: JsonObject,
  listTitle: string,
  fallbackDescription = true,
): JsonObject {
  const listPlot = text(playlist.description) ??
    (fallbackDescription
      ? "Remote videos selected by the supplied playlist link."
      : undefined);
  const channel = text(playlist.channel) ?? text(playlist.uploader);
  const playlistId = text(playlist.playlist_id) ??
    (Array.isArray(playlist.entries) ? text(playlist.id) : undefined);
  const videoId = Array.isArray(playlist.entries)
    ? undefined
    : text(playlist.id);
  return {
    record_type: "list",
    provider_id: request.source_url,
    name: listTitle,
    description: listPlot,
    metadata: {
      title: listTitle,
      plot: listPlot,
      tags: values(playlist.tags),
      people: people(playlist),
      original_broadcasters: values(channel),
      broadcasters: values(channel),
      artwork: artwork(playlist, "fanart"),
      guids: values(
        playlistId && `yt-dlp-playlist://${playlistId}`,
        videoId && `yt-dlp://${videoId}`,
      ),
    },
  };
}

async function extractListHeader(
  request: DiscoverRequest,
): Promise<JsonObject> {
  const result = await runProvider([
    "--no-config",
    "--no-update",
    "--quiet",
    "--skip-download",
    "--flat-playlist",
    "--playlist-start",
    "1",
    "--playlist-end",
    "1",
    "--dump-single-json",
    request.source_url,
  ]);
  if (!result.success) {
    throw new Error("yt-dlp playlist-header extraction failed");
  }
  const header = parseProviderJson(result);
  if (!text(header.title)) {
    throw new Error("yt-dlp playlist-header extraction omitted the title");
  }
  return header;
}

async function discoverV1(request: DiscoverRequest): Promise<void> {
  const offset = request.cursor === undefined ? 0 : Number(request.cursor);
  if (!Number.isSafeInteger(offset) || offset < 0) {
    throw new Error("invalid discovery cursor");
  }
  const maxItems = Math.min(Math.max(request.limits.max_items, 1), 250);
  const result = await runProvider([
    "--no-config",
    "--no-update",
    "--quiet",
    "--skip-download",
    "--ignore-errors",
    "--flat-playlist",
    "--playlist-start",
    String(offset + 1),
    "--playlist-end",
    String(offset + maxItems + 1),
    "--dump-single-json",
    request.source_url,
  ]);
  if (!result.success) {
    throw new Error("yt-dlp discovery failed");
  }
  const playlist = parseProviderJson(result);
  const entries =
    (Array.isArray(playlist.entries) ? playlist.entries : [playlist])
      .map(object).filter(Boolean) as JsonObject[];
  const selected = entries.slice(0, maxItems);
  const listTitle = text(playlist.title) ?? "yt-dlp playlist";
  const rows = selected.map((entry, index) =>
    providerItem(entry, offset + index, listTitle)
  ).filter(Boolean) as JsonObject[];
  if (offset === 0 && rows.length === 0) {
    throw new Error("yt-dlp returned no valid media items");
  }
  const complete = entries.length <= maxItems;
  const totalHint = positiveInteger(playlist.playlist_count) ??
    positiveInteger(playlist.n_entries);
  emit({
    record_type: "page",
    complete,
    next_cursor: complete ? undefined : String(offset + selected.length),
    total_hint: totalHint && totalHint <= 10_000 ? totalHint : undefined,
  });
  if (offset === 0) {
    emit(listRecord(request, playlist, listTitle));
  }
  rows.forEach(emit);
}

function requestedProviderPositions(
  playlist: JsonObject,
  offset: number,
  maxItems: number,
): number[] | undefined {
  if (!Array.isArray(playlist.requested_entries)) return undefined;
  const positions = playlist.requested_entries.map(positiveInteger);
  if (positions.some((position) => position === undefined)) {
    throw new Error("yt-dlp returned invalid requested playlist positions");
  }
  const result = positions as number[];
  if (
    result.length > maxItems || new Set(result).size !== result.length ||
    result.some((position, index) =>
      position <= offset || position > offset + maxItems ||
      (index > 0 && position <= result[index - 1])
    )
  ) {
    throw new Error("yt-dlp returned unexpected requested playlist positions");
  }
  return result;
}

function v2ProviderWindow(
  playlist: JsonObject,
  entries: JsonObject[],
  offset: number,
  maxItems: number,
): { examined: number; complete: boolean; totalHint?: number } {
  const total = positiveInteger(playlist.playlist_count);
  const positions = requestedProviderPositions(playlist, offset, maxItems);
  const isPlaylist = Array.isArray(playlist.entries);

  if (!isPlaylist) {
    if (offset !== 0) {
      throw new Error(
        "yt-dlp returned an unexpected direct-video continuation",
      );
    }
    return { examined: 1, complete: true, totalHint: 1 };
  }

  const emittedPositions = entries.map((entry) =>
    positiveInteger(entry.playlist_index)
  );
  if (emittedPositions.some((position) => position === undefined)) {
    throw new Error("yt-dlp omitted a provider playlist position");
  }
  const emitted = emittedPositions as number[];
  if (
    new Set(emitted).size !== emitted.length ||
    emitted.some((position) =>
      position <= offset || position > offset + maxItems ||
      (positions !== undefined && !positions.includes(position))
    )
  ) {
    throw new Error("yt-dlp returned an unexpected provider playlist position");
  }
  if (
    positions !== undefined &&
    (positions.length !== emitted.length ||
      positions.some((position, index) => position !== emitted[index]))
  ) {
    throw new Error("yt-dlp returned inconsistent requested playlist entries");
  }

  let examined: number;
  if (total !== undefined) {
    examined = Math.min(maxItems, Math.max(0, total - offset));
  } else if (
    positions !== undefined && positions.length > 0 &&
    positions.every((position, index) => position === offset + index + 1)
  ) {
    examined = positions.length;
  } else {
    throw new Error("yt-dlp did not report the examined playlist window");
  }
  if (entries.length > examined) {
    throw new Error("yt-dlp returned more items than it examined");
  }
  const complete = total !== undefined
    ? offset + examined >= total
    : examined < maxItems;
  return {
    examined,
    complete,
    totalHint: total !== undefined && total <= 10_000 ? total : undefined,
  };
}

async function discoverV2(request: DiscoverV2Request): Promise<void> {
  const offset = request.cursor === undefined ? 0 : Number(request.cursor);
  if (!Number.isSafeInteger(offset) || offset < 0) {
    throw new Error("invalid discovery cursor");
  }
  if (!request.archive || !text(request.archive.staged_path)) {
    throw new Error("the staged archive path is unavailable");
  }
  if (request.mode !== "full" && request.mode !== "incremental") {
    throw new Error("invalid discovery mode");
  }
  if (
    !Number.isSafeInteger(request.archive.generation) ||
    request.archive.generation < 1
  ) {
    throw new Error("invalid archive generation");
  }
  const maxItems = Math.min(Math.max(request.limits.max_items, 1), 250);
  const header = offset === 0 ? await extractListHeader(request) : undefined;
  const result = await runProvider([
    "--no-config",
    "--no-update",
    "--quiet",
    "--skip-download",
    "--flat-playlist",
    "--playlist-start",
    String(offset + 1),
    "--playlist-end",
    String(offset + maxItems),
    "--download-archive",
    request.archive.staged_path,
    "--force-write-archive",
    "--dump-single-json",
    request.source_url,
  ]);
  if (!result.success) {
    throw new Error("yt-dlp discovery failed");
  }

  if (!result.stdout.trim() || result.stdout.trim() === "null") {
    if (request.mode !== "incremental" || offset !== 0) {
      throw new Error("yt-dlp returned no JSON object");
    }
    emit({
      record_type: "page",
      complete: true,
      strategy: "skip_known",
      examined_count: 1,
      archived_skipped_count: 1,
      emitted_count: 0,
    });
    if (header) {
      const listTitle = text(header.title) ?? "yt-dlp playlist";
      emit(listRecord(request, header, listTitle, false));
    }
    return;
  }

  const playlist = parseProviderJson(result);
  const rawEntries = Array.isArray(playlist.entries)
    ? playlist.entries
    : [playlist];
  const entries = rawEntries.map(object);
  if (entries.some((entry) => entry === undefined)) {
    throw new Error("yt-dlp returned an invalid unarchived item");
  }
  const providerEntries = entries as JsonObject[];
  const window = v2ProviderWindow(playlist, providerEntries, offset, maxItems);
  const listTitle = text(playlist.title) ?? "yt-dlp playlist";
  const rows = providerEntries.map((entry) => {
    const position = Array.isArray(playlist.entries)
      ? positiveInteger(entry.playlist_index)
      : 1;
    if (position === undefined) {
      throw new Error("yt-dlp omitted a provider playlist position");
    }
    const row = providerItem(entry, position - 1, listTitle);
    if (!row) {
      throw new Error("yt-dlp returned an unmappable unarchived item");
    }
    return row;
  });
  if (request.mode === "full" && offset === 0 && rows.length === 0) {
    throw new Error("yt-dlp returned no valid media items");
  }
  const archivedSkipped = window.examined - rows.length;
  if (
    archivedSkipped < 0 || (request.mode === "full" && archivedSkipped !== 0)
  ) {
    throw new Error("yt-dlp returned inconsistent archive suppression counts");
  }
  emit({
    record_type: "page",
    complete: window.complete,
    next_cursor: window.complete ? undefined : String(offset + window.examined),
    total_hint: window.totalHint,
    strategy: "skip_known",
    examined_count: window.examined,
    archived_skipped_count: archivedSkipped,
    emitted_count: rows.length,
  });
  if (header) {
    const headerTitle = text(header.title) ?? listTitle;
    emit(listRecord(request, header, headerTitle, false));
  }
  rows.forEach(emit);
}

function unavailableItem(
  request: EnrichRequest,
  reasonCode: AvailabilityReasonCode,
): JsonObject {
  return {
    ...request.item,
    availability: "unavailable",
    availability_reason: "not_playable",
    availability_reason_code: reasonCode,
  };
}

async function enrich(request: EnrichRequest): Promise<void> {
  const sourceUrl = safeHttpsUrl(request.item.source_url);
  if (!sourceUrl) {
    emit({
      record_type: "outcome",
      outcome: "permanent_failure",
      code: "missing-item-url",
      message: "The overview item has no safe source URL.",
    });
    return;
  }
  const result = await runProvider([
    "--no-config",
    "--no-update",
    "--quiet",
    "--skip-download",
    "--no-playlist",
    "--dump-single-json",
    sourceUrl,
  ]);
  if (!result.success) {
    const reasonCode = failureAvailabilityReason(result.stderr);
    if (reasonCode) {
      emit({
        record_type: "outcome",
        outcome: "unavailable",
        code: reasonCode.replaceAll("_", "-"),
        message: "The provider reports that this item cannot be played.",
      });
      emit(unavailableItem(request, reasonCode));
      return;
    }
    failure(result.stderr);
    return;
  }
  let entry: JsonObject;
  try {
    entry = parseProviderJson(result);
  } catch (error) {
    emit({
      record_type: "outcome",
      outcome: "permanent_failure",
      code: "malformed-provider-response",
      message: String(error).slice(0, 768),
    });
    return;
  }
  const rank = integer(request.item.rank) ?? 0;
  const mapped = providerItem(
    entry,
    rank,
    text(object(request.item.metadata)?.collection),
  );
  if (!mapped) {
    emit({
      record_type: "outcome",
      outcome: "permanent_failure",
      code: "incomplete-provider-response",
      message:
        "yt-dlp did not return the required item identity, title, and URL.",
    });
    return;
  }
  mapped.provider_id = request.provider_id;
  const state = mapped.availability;
  emit({
    record_type: "outcome",
    outcome: state === "unavailable" ? "unavailable" : "complete",
    code: state === "unavailable"
      ? String(mapped.availability_reason_code ?? "unavailable").replaceAll(
        "_",
        "-",
      )
      : undefined,
  });
  emit(mapped);
}

const operation = Deno.args[0];
const input = await new Response(Deno.stdin.readable).text();
if (!input.trim()) throw new Error("media-list import request is missing");
if (operation === "discover") {
  const request = JSON.parse(input) as DiscoverRequest | DiscoverV2Request;
  if ("mode" in request || "archive" in request) {
    await discoverV2(request as DiscoverV2Request);
  } else {
    await discoverV1(request as DiscoverRequest);
  }
} else if (operation === "enrich") {
  await enrich(JSON.parse(input) as EnrichRequest);
} else throw new Error("usage: media-list-import.ts discover|enrich");
