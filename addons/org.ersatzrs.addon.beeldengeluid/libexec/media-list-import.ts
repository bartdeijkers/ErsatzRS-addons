import { normalizeRecord } from "./media-list-adapter.ts";

type JsonObject = Record<string, unknown>;

interface DiscoverRequest {
  source_url: string;
  record_capability: string;
  cursor?: string;
  limits: { max_items: number; max_output_bytes: number };
}

interface EnrichRequest {
  source_url: string;
  record_capability: string;
  provider_id: string;
  overview_fingerprint: string;
  item: JsonObject;
}

interface Cursor {
  page: number;
  offset: number;
  rank: number;
  seen: string[];
}

interface HttpResult {
  status: number;
  body: string;
  error?: string;
}

interface OverviewItem {
  path: string;
  title: string;
  description?: string;
  releaseDate?: string;
  image?: string;
  playable?: boolean;
}

const decoder = new TextDecoder();
const curl = Deno.env.get("CURL_BIN")?.trim() ||
  (Deno.build.os === "windows" ? "curl.exe" : "curl");
const providerOrigin = "https://schatkamer.beeldengeluid.nl";

function object(value: unknown): JsonObject | undefined {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as JsonObject
    : undefined;
}

function text(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function htmlDecode(value: string): string {
  return value.replaceAll("&amp;", "&").replaceAll("&quot;", '"')
    .replaceAll("&#39;", "'").replaceAll("&#x27;", "'")
    .replaceAll("&lt;", "<").replaceAll("&gt;", ">").replaceAll("&nbsp;", " ");
}

function normalizedHtml(value: string): string {
  return value.replaceAll('\\"', '"').replaceAll("\\/", "/")
    .replaceAll("\\u0026", "&").replaceAll("\\u003c", "<")
    .replaceAll("\\u003e", ">").replaceAll("\\u0027", "'");
}

function plainText(value: string): string {
  return htmlDecode(value.replace(/<[^>]+>/g, " "))
    .replace(/\s+/g, " ").trim();
}

function decodeJsonString(value: string): string | undefined {
  try {
    return text(JSON.parse(`"${value.replaceAll('"', '\\"')}"`));
  } catch {
    return text(
      htmlDecode(value.replaceAll("\\n", " ").replaceAll("\\r", " ")),
    );
  }
}

function jsonStringValues(html: string, field: string): string[] {
  const result: string[] = [];
  const expression = new RegExp(
    `"${field}"\\s*:\\s*"((?:\\\\.|[^"\\\\])*)"`,
    "gi",
  );
  for (const match of html.matchAll(expression)) {
    const value = decodeJsonString(match[1]);
    if (value) result.push(value);
  }
  return result;
}

function lastJsonString(html: string, field: string): string | undefined {
  return jsonStringValues(html, field).at(-1);
}

function jsonStrings(html: string, field: string): string[] {
  const matches = [
    ...html.matchAll(new RegExp(`"${field}"\\s*:\\s*(\\[[^\\]]*\\])`, "gi")),
  ];
  const raw = matches.at(-1)?.[1];
  if (!raw) return [];
  try {
    const values = JSON.parse(raw);
    return Array.isArray(values)
      ? values.map(text).filter(Boolean) as string[]
      : [];
  } catch {
    return [...raw.matchAll(/"((?:\\.|[^"\\])*)"/g)]
      .map((match) => decodeJsonString(match[1])).filter(Boolean) as string[];
  }
}

function safeProviderImage(value: unknown): string | undefined {
  const candidate = text(value);
  if (!candidate) return undefined;
  try {
    const url = new URL(htmlDecode(candidate));
    if (url.protocol !== "https:" || url.username || url.password) {
      return undefined;
    }
    if (
      !["schatkamer.beeldengeluid.nl", "sk-video.cdn.beeldengeluid.nl"]
        .includes(url.hostname)
    ) {
      return undefined;
    }
    return url.toString();
  } catch {
    return undefined;
  }
}

function decodeOptimizerImage(value: string): string | undefined {
  try {
    const optimizer = new URL(htmlDecode(value), providerOrigin);
    const encoded = optimizer.searchParams.get("url");
    if (!encoded) return undefined;
    const normalized = encoded.replaceAll("-", "+").replaceAll("_", "/");
    const padded = normalized + "=".repeat((4 - normalized.length % 4) % 4);
    const bytes = Uint8Array.from(
      atob(padded),
      (character) => character.charCodeAt(0),
    );
    return safeProviderImage(decoder.decode(bytes));
  } catch {
    return undefined;
  }
}

function imageFromHtml(html: string): string | undefined {
  for (
    const match of html.matchAll(
      /(?:src|content|"image")\s*(?:=|:)\s*["']([^"']+)["']/gi,
    )
  ) {
    const candidate = htmlDecode(match[1]);
    const image = candidate.includes("/image-optimizer?")
      ? decodeOptimizerImage(candidate)
      : safeProviderImage(candidate);
    if (image) return image;
  }
  for (const match of html.matchAll(/https:\/\/[^"'<>\\ ]+/gi)) {
    const image = safeProviderImage(match[0]);
    if (image && /[.](?:jpe?g|png|webp)(?:[?#]|$)/i.test(image)) return image;
  }
  return undefined;
}

// A programme page opens with the shared Schatkamer social card and then shows
// stills of neighbouring episodes, so the first picture in document order
// belongs to something else. Two payloads name this programme: the player
// publishes the poster it shows before playback, and the programme record
// carries its still beside its own identity.
function episodeImageFromHtml(
  html: string,
  episodeId: string,
): string | undefined {
  const poster = safeProviderImage(
    html.match(
      /"programStream"\s*:\s*\{[\s\S]{0,400}?"poster"\s*:\s*"([^"]+)"/i,
    )?.[1],
  );
  if (poster) return poster;
  if (!/^\d{1,64}$/.test(episodeId)) return undefined;
  const record = html.match(
    new RegExp(
      `"id"\\s*:\\s*"${episodeId}"[^{}]*?` +
        `"image"\\s*:\\s*\\{[^{}]*?"url"\\s*:\\s*"([^"]+)"`,
      "i",
    ),
  )?.[1];
  return safeProviderImage(record);
}

function dateFromHtml(html: string): string | undefined {
  const explicit = lastJsonString(html, "publishedAtISO") ??
    lastJsonString(html, "datePublished") ??
    lastJsonString(html, "release_date");
  const match = explicit?.match(/^(\d{4}-\d{2}-\d{2})(?:T.*)?$/) ??
    html.match(/\b(\d{4}-\d{2}-\d{2})(?:T\d{2}:\d{2}[^"'< ]*)?/);
  if (match?.[1]) return match[1];
  const localized = plainText(html).match(
    /\b(\d{1,2})\s+(januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december)\s+(\d{4})\b/i,
  );
  if (!localized) return undefined;
  const months = [
    "januari",
    "februari",
    "maart",
    "april",
    "mei",
    "juni",
    "juli",
    "augustus",
    "september",
    "oktober",
    "november",
    "december",
  ];
  const month = months.indexOf(localized[2].toLocaleLowerCase("nl-NL")) + 1;
  return localized[3] + "-" + String(month).padStart(2, "0") + "-" +
    localized[1].padStart(2, "0");
}

function titleFromPath(path: string): string {
  const slug = path.split("/").at(-3) ?? path.split("/").at(-1) ?? "Programme";
  try {
    return decodeURIComponent(slug).replaceAll("-", " ").replace(/\s+/g, " ")
      .trim() ||
      "Programme";
  } catch {
    return slug.replaceAll("-", " ");
  }
}

function titleFromCard(body: string, path: string): string {
  const attributes = [
    "data-gtm-interaction-text",
    "data-title",
    "title",
    "aria-label",
    "alt",
  ];
  for (const attribute of attributes) {
    const match = body.match(new RegExp(`${attribute}=["']([^"']+)["']`, "i"));
    const value = match ? plainText(match[1]) : "";
    if (value) return value;
  }
  const heading = body.match(/<h[1-6][^>]*>([\s\S]*?)<\/h[1-6]>/i);
  if (heading) {
    const value = plainText(heading[1]);
    if (value) return value;
  }
  const stripped = plainText(body);
  return stripped || titleFromPath(path);
}

function descriptionFromCard(body: string): string | undefined {
  const described = lastJsonString(normalizedHtml(body), "description");
  if (described) return described;
  const paragraph = body.match(/<p\b[^>]*>([\s\S]*?)<\/p>/i);
  return paragraph ? text(plainText(paragraph[1])) : undefined;
}

function extractOverviewItems(rawHtml: string): OverviewItem[] {
  const html = normalizedHtml(rawHtml);
  const candidates: Array<{ index: number; item: OverviewItem }> = [];
  const card =
    /<li\b[^>]*>(?<body>(?:(?!<\/li>)[\s\S])*?href=["'](?<path>\/serie\/\d+\/[^"'\/]+\/aflevering\/\d+)["'](?:(?!<\/li>)[\s\S])*?)<\/li>/gi;
  for (const match of html.matchAll(card)) {
    const path = match.groups?.path;
    if (!path) continue;
    const body = match.groups?.body ?? "";
    candidates.push({
      index: match.index,
      item: {
        path,
        title: titleFromCard(body, path),
        description: descriptionFromCard(body),
        releaseDate: dateFromHtml(body),
        image: imageFromHtml(body),
      },
    });
  }
  const anchor =
    /<a\b(?<attributes>[^>]*)href=["'](?<path>\/serie\/\d+\/[^"'\/]+\/aflevering\/\d+)["'](?<tail>[^>]*)>(?<body>[\s\S]*?)<\/a>/gi;
  for (const match of html.matchAll(anchor)) {
    const path = match.groups?.path;
    if (!path) continue;
    const body = `${match.groups?.attributes ?? ""} ${
      match.groups?.tail ?? ""
    } ${match.groups?.body ?? ""}`;
    candidates.push({
      index: match.index,
      item: {
        path,
        title: titleFromCard(body, path),
        description: descriptionFromCard(body),
        releaseDate: dateFromHtml(body),
        image: imageFromHtml(body),
      },
    });
  }
  // A provider record ends with the link it describes, so reading forward from
  // that link reads the next episode's fields. Anchor on the record's own
  // identity and accept it only when the link it introduces names that same
  // episode; the series object wrapping a card carries an identity too.
  const jsonRecord =
    /"id"\s*:\s*"(?<id>\d{1,64})"(?<body>[\s\S]{0,2400}?)"url"\s*:\s*"https:\/\/schatkamer[.]beeldengeluid[.]nl(?<path>\/serie\/\d+\/[^"\/]+\/aflevering\/(?<pathId>\d{1,64}))"/gi;
  let record = jsonRecord.exec(html);
  while (record) {
    const path = record.groups?.path;
    if (path && record.groups?.id === record.groups?.pathId) {
      const body = record.groups?.body ?? "";
      const playableMatch = body.match(/"isPlayable"\s*:\s*(true|false)/i);
      candidates.push({
        index: record.index,
        item: {
          path,
          title: lastJsonString(body, "title") ?? titleFromPath(path),
          description: lastJsonString(body, "description"),
          releaseDate: dateFromHtml(body),
          image: imageFromHtml(body),
          playable: playableMatch
            ? playableMatch[1].toLocaleLowerCase() === "true"
            : undefined,
        },
      });
    } else {
      // A rejected pairing must not hide the record that follows it.
      jsonRecord.lastIndex = record.index + 1;
    }
    record = jsonRecord.exec(html);
  }
  candidates.sort((left, right) => left.index - right.index);
  const merged = new Map<string, OverviewItem>();
  for (const { item } of candidates) {
    const id = item.path.split("/").at(-1);
    if (!id) continue;
    const existing = merged.get(id);
    if (!existing) {
      merged.set(id, item);
      continue;
    }
    existing.title = richerText(existing.title, item.title) ?? existing.title;
    existing.description = richerText(existing.description, item.description);
    existing.releaseDate ??= item.releaseDate;
    existing.image ??= item.image;
    if (item.playable === false || existing.playable === false) {
      existing.playable = false;
    } else if (item.playable === true || existing.playable === true) {
      existing.playable = true;
    }
  }
  return [...merged.values()];
}

function richerText(
  current: string | undefined,
  candidate: string | undefined,
): string | undefined {
  if (!current) return candidate;
  if (!candidate) return current;
  return candidate.length > current.length ? candidate : current;
}

function encodeCursor(cursor: Cursor): string {
  const numericIds = [...new Set(cursor.seen)].map((value) => {
    if (!/^\d{1,64}$/.test(value)) {
      throw new Error("invalid discovery cursor identity");
    }
    return BigInt(value);
  }).sort((left, right) => left < right ? -1 : left > right ? 1 : 0);
  let previous = 0n;
  const seen = numericIds.map((value, index) => {
    const delta = index === 0 ? value : value - previous;
    previous = value;
    return delta.toString(36);
  }).join(".");
  const encoded = btoa(JSON.stringify({
    p: cursor.page,
    o: cursor.offset,
    r: cursor.rank,
    s: seen,
  })).replaceAll("+", "-").replaceAll("/", "_")
    .replace(/=+$/, "");
  if (encoded.length > 4_096) {
    throw new Error("discovery cursor exceeds host limit");
  }
  return encoded;
}

function base36(value: string): bigint {
  if (!/^[0-9a-z]+$/.test(value)) {
    throw new Error("invalid base36 cursor value");
  }
  let result = 0n;
  for (const character of value) {
    const digit = BigInt(parseInt(character, 36));
    result = result * 36n + digit;
  }
  return result;
}

function expandedSeen(value: string): string[] {
  if (!value) return [];
  let previous = 0n;
  const result = value.split(".").map((part) => {
    previous += base36(part);
    return previous.toString();
  });
  if (new Set(result).size !== result.length) {
    throw new Error("duplicate discovery cursor identity");
  }
  return result;
}

function decodeCursor(value?: string): Cursor {
  if (!value) return { page: 1, offset: 0, rank: 0, seen: [] };
  try {
    const normalized = value.replaceAll("-", "+").replaceAll("_", "/");
    const decoded = atob(
      normalized + "=".repeat((4 - normalized.length % 4) % 4),
    );
    const cursor = object(JSON.parse(decoded));
    const page = Number(cursor?.p ?? cursor?.page);
    const offset = Number(cursor?.o ?? cursor?.offset);
    const rank = Number(cursor?.r ?? cursor?.rank);
    const seen = typeof cursor?.s === "string"
      ? expandedSeen(cursor.s)
      : Array.isArray(cursor?.seen)
      ? cursor.seen
      : [];
    if (
      [page, offset, rank].every(Number.isSafeInteger) && page >= 1 &&
      offset >= 0 && rank >= 0 && seen.length <= 10_000 &&
      seen.every((value) => typeof value === "string" && value.length <= 128)
    ) {
      return { page, offset, rank, seen: seen as string[] };
    }
  } catch {
    // Report one stable request error below.
  }
  throw new Error("invalid discovery cursor");
}

function pageUrl(sourceUrl: string, page: number): string {
  const url = new URL(sourceUrl);
  if (
    url.hostname !== "schatkamer.beeldengeluid.nl" ||
    !["http:", "https:"].includes(url.protocol)
  ) {
    throw new Error("unsupported Schatkamer source URL");
  }
  url.protocol = "https:";
  url.hash = "";
  url.searchParams.set("pagina", String(page));
  return url.toString();
}

async function requestPage(url: string): Promise<HttpResult> {
  const marker = "\n__ERSATZRS_HTTP_STATUS__:";
  const writeOut = "\\n__ERSATZRS_HTTP_STATUS__:%{http_code}";
  try {
    const result = await new Deno.Command(curl, {
      args: [
        "--silent",
        "--show-error",
        "--location",
        "--max-redirs",
        "5",
        "--proto",
        "=https",
        "--proto-redir",
        "=https",
        "--connect-timeout",
        "10",
        "--max-time",
        "40",
        "--write-out",
        writeOut,
        url,
      ],
      stdin: "null",
      stdout: "piped",
      stderr: "piped",
    }).output();
    const output = decoder.decode(result.stdout);
    const markerAt = output.lastIndexOf(marker);
    const body = markerAt >= 0 ? output.slice(0, markerAt) : output;
    const status = markerAt >= 0
      ? Number(output.slice(markerAt + marker.length).trim())
      : 0;
    return {
      status,
      body,
      error: result.success ? undefined : decoder.decode(result.stderr).trim(),
    };
  } catch (error) {
    return { status: 0, body: "", error: String(error) };
  }
}

function listIdentity(sourceUrl: string): string {
  const url = new URL(sourceUrl);
  const value = `${url.pathname.replace(/^\//, "")}${url.search}`;
  return value.slice(0, 384);
}

function listHeader(sourceUrl: string, html: string): JsonObject {
  let name: string | undefined;
  let description: string | undefined;
  let image: string | undefined;
  for (
    const match of html.matchAll(
      /<script\b[^>]*type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi,
    )
  ) {
    try {
      let value: unknown;
      try {
        value = JSON.parse(match[1]);
      } catch {
        value = JSON.parse(htmlDecode(match[1]));
      }
      const document = object(value);
      const type = text(document?.["@type"]);
      if (type !== "CreativeWorkSeries") continue;
      name = text(document?.name);
      description = text(document?.description);
      image = safeProviderImage(document?.image);
      break;
    } catch {
      // A malformed optional JSON-LD block does not invalidate card discovery.
    }
  }
  const normalized = normalizedHtml(html);
  const sharedTitle = normalized.match(
    /"title"\s*:\s*"([^"]+)"\s*,\s*"description"\s*:\s*"Gedeelde lijst"/i,
  );
  name ??= sharedTitle ? decodeJsonString(sharedTitle[1]) : undefined;
  const url = new URL(sourceUrl);
  if (!name) {
    name = url.pathname.startsWith("/zoeken")
      ? "Beeld & Geluid search"
      : "Beeld & Geluid Schatkamer";
  }
  description ??= url.pathname.startsWith("/zoeken")
    ? "Programmes selected by the supplied Schatkamer search."
    : undefined;
  const artwork = image ? [{ role: "poster", url: image }] : [];
  return normalizeRecord({
    record_type: "list",
    provider_id: listIdentity(sourceUrl),
    name,
    description,
    metadata: {
      title: name,
      plot: description,
      artwork,
      guids: [`beeldengeluid-list://${listIdentity(sourceUrl)}`],
    },
  }, 1);
}

function overviewRecord(item: OverviewItem, rank: number): JsonObject {
  const episodeId = item.path.split("/").at(-1) ?? "unknown";
  const artwork = item.image ? [{ role: "thumb", url: item.image }] : [];
  return normalizeRecord({
    record_type: "item",
    provider_id: `episode:${episodeId}`,
    rank,
    display_title: item.title,
    title: item.title,
    year: item.releaseDate ? Number(item.releaseDate.slice(0, 4)) : undefined,
    kind: "remote_stream",
    guids: [`beeldengeluid://${episodeId}`],
    source_url: `${providerOrigin}${item.path}`,
    availability: item.playable === false ? "unavailable" : "available",
    availability_reason: item.playable === false ? "not_playable" : undefined,
    content_kind: "auto",
    liveness: "finite",
    additional_image_urls: item.image ? [item.image] : [],
    metadata: {
      title: item.title,
      plot: item.description,
      year: item.releaseDate ? Number(item.releaseDate.slice(0, 4)) : undefined,
      release_date: item.releaseDate,
      artwork,
      guids: [`beeldengeluid://${episodeId}`],
    },
  }, rank + 2);
}

function emit(value: unknown): void {
  console.log(JSON.stringify(value));
}

async function discover(request: DiscoverRequest): Promise<void> {
  const source = new URL(request.source_url);
  if (
    source.hostname !== "schatkamer.beeldengeluid.nl" ||
    !["http:", "https:"].includes(source.protocol)
  ) {
    throw new Error("unsupported Schatkamer source URL");
  }
  source.protocol = "https:";
  source.hash = "";
  const cursor = decodeCursor(request.cursor);
  const maxItems = Math.min(Math.max(request.limits.max_items, 1), 250);
  const isEpisode = /\/aflevering\/\d+\/?$/.test(source.pathname);
  if (isEpisode) {
    const path = source.pathname.replace(/\/$/, "");
    const response = await requestPage(source.toString());
    if (
      response.error || response.status === 0 || response.status === 429 ||
      response.status >= 500
    ) {
      throw new Error(
        response.error || `Schatkamer episode returned HTTP ${response.status}`,
      );
    }
    if (response.status >= 400 && ![404, 410].includes(response.status)) {
      throw new Error(`Schatkamer episode returned HTTP ${response.status}`);
    }
    const episodeId = path.split("/").at(-1) ?? "unknown";
    const normalized = normalizedHtml(response.body);
    const identityAt = [
      ...normalized.matchAll(
        new RegExp(`"id"\\s*:\\s*"${episodeId}"`, "g"),
      ),
    ].at(-1)?.index;
    const playableMatches = [
      ...normalized.matchAll(/"isPlayable"\s*:\s*(true|false)/gi),
    ];
    const playableMatch = identityAt === undefined
      ? playableMatches.at(-1)
      : playableMatches.sort((left, right) =>
        Math.abs((left.index ?? 0) - identityAt) -
        Math.abs((right.index ?? 0) - identityAt)
      )[0];
    const playable = playableMatch?.[1].toLocaleLowerCase() !== "false";
    const overview: OverviewItem = {
      path,
      title: titleFromPath(path),
      playable,
    };
    const baseline = overviewRecord(overview, 0);
    baseline.source_url = source.toString();
    const directRequest: EnrichRequest = {
      source_url: request.source_url,
      record_capability: request.record_capability,
      provider_id: `episode:${episodeId}`,
      overview_fingerprint: "direct-episode",
      item: baseline,
    };
    const unavailable = [404, 410].includes(response.status) || !playable;
    emit({ record_type: "page", complete: true, total_hint: 1 });
    emit(listHeader(request.source_url, response.body));
    emit(fullItem(directRequest, response.body, unavailable));
    return;
  }
  const response = await requestPage(pageUrl(request.source_url, cursor.page));
  if (response.error || response.status >= 400 || response.status === 0) {
    throw new Error(
      response.error || `Schatkamer overview returned HTTP ${response.status}`,
    );
  }
  const allItems = extractOverviewItems(response.body);
  const totalHintMatch = plainText(response.body).match(
    /\b(\d{1,6})\s+resultaten\b/i,
  );
  const totalHint = totalHintMatch ? Number(totalHintMatch[1]) : undefined;
  const seen = new Set(cursor.seen);
  const selected: OverviewItem[] = [];
  let nextOffset = cursor.offset;
  while (nextOffset < allItems.length && selected.length < maxItems) {
    const item = allItems[nextOffset];
    nextOffset++;
    const episodeId = item.path.split("/").at(-1);
    if (!episodeId || seen.has(episodeId)) continue;
    seen.add(episodeId);
    selected.push(item);
  }
  const exhaustedPage = nextOffset >= allItems.length;
  const complete = allItems.length === 0;
  const next = complete ? undefined : exhaustedPage
    ? {
      page: cursor.page + 1,
      offset: 0,
      rank: cursor.rank + selected.length,
      seen: [...seen],
    }
    : {
      page: cursor.page,
      offset: nextOffset,
      rank: cursor.rank + selected.length,
      seen: [...seen],
    };
  emit({
    record_type: "page",
    complete,
    next_cursor: next ? encodeCursor(next) : undefined,
    total_hint: Number.isSafeInteger(totalHint) ? totalHint : undefined,
  });
  if (!request.cursor) emit(listHeader(request.source_url, response.body));
  selected.forEach((item, index) =>
    emit(overviewRecord(item, cursor.rank + index))
  );
}

function classifiedContentKind(
  showTitle: string | undefined,
  genres: string[],
  tags: string[],
): string {
  const source = [...genres, ...tags].join(" ").toLocaleLowerCase();
  if (/reclame|commercial|advertentie/.test(source)) return "other_video";
  if (/muziek|music|concert|videoclip|music video/.test(source)) {
    return "music_video";
  }
  if (/speelfilm|film|movie/.test(source)) return "movie";
  return showTitle ? "television_episode" : "other_video";
}

function peopleFromHtml(html: string): JsonObject[] {
  const result: JsonObject[] = [];
  const sections: Array<[string, string]> = [
    ["presenters", "presenter"],
    ["actors", "actor"],
    ["guests", "guest"],
    ["directors", "director"],
    ["performers", "performer"],
    ["others", "person"],
  ];
  for (const [field, role] of sections) {
    const expression = new RegExp(`"${field}"\\s*:\\s*\\[([\\s\\S]*?)\\]`, "i");
    const section = html.match(expression)?.[1] ?? "";
    for (
      const match of section.matchAll(/"name"\s*:\s*"((?:\\.|[^"\\])*)"/gi)
    ) {
      const name = decodeJsonString(match[1]);
      if (name) result.push({ name, role });
    }
  }
  return result.slice(0, 1024);
}

// A programme that was archived across several analogue carriers publishes one
// stream entry per part, and the episode runs as long as all of them together.
// Only entries in that stream index carry a playout position, so pairing the
// two fields selects the parts and ignores durations published elsewhere on
// the page. A page without the index keeps its single duration.
function episodeDuration(html: string): number | undefined {
  const parts = [
    ...html.matchAll(
      /"durationNumber"\s*:\s*(\d+)\s*,\s*"playoutOrder"\s*:\s*\d+/gi,
    ),
  ].map((part) => Number(part[1]));
  if (parts.length) {
    // The archive also holds repeat digitisations of the same carrier. They
    // are only recognisable by their nearly equal durations, so collapsing
    // them is opt-in and must match what playback does; both keep the first
    // copy of a group in playout order.
    const tolerance = duplicateTolerance();
    const kept: number[] = [];
    for (const part of parts) {
      if (
        tolerance > 0 &&
        kept.some((first) => Math.abs(first - part) <= tolerance)
      ) {
        continue;
      }
      kept.push(part);
    }
    return kept.reduce((total, part) => total + part, 0);
  }
  const single = html.match(/"durationNumber"\s*:\s*(\d+)/i);
  return single ? Number(single[1]) : undefined;
}

function duplicateTolerance(): number {
  const configured = Deno.env
    .get("ERSATZRS_ADDON_SETTING_DUPLICATE_TOLERANCE_SECONDS")?.trim();
  return configured && /^\d+$/.test(configured) ? Number(configured) : 0;
}

function fullItem(
  request: EnrichRequest,
  html: string,
  unavailable = false,
): JsonObject {
  const baseline = request.item;
  const normalized = normalizedHtml(html);
  const showTitle = text(normalized.match(/<h1\b[^>]*>([\s\S]*?)<\/h1>/i)?.[1])
    ? plainText(normalized.match(/<h1\b[^>]*>([\s\S]*?)<\/h1>/i)?.[1] ?? "")
    : lastJsonString(normalized, "series");
  const heading = normalized.match(/<h3\b[^>]*>([\s\S]*?)<\/h3>/i)?.[1];
  const title = (heading ? plainText(heading) : undefined) ??
    lastJsonString(normalized, "title") ?? text(baseline.title) ?? "Programme";
  const plot = lastJsonString(normalized, "description") ??
    text(object(baseline.metadata)?.plot);
  const releaseDate = dateFromHtml(normalized) ??
    text(object(baseline.metadata)?.release_date);
  const duration = episodeDuration(normalized) ??
    Number(baseline.duration_seconds);
  const genres = jsonStrings(normalized, "genres");
  const tags = jsonStrings(normalized, "subjects");
  const episodeId = request.provider_id.replace(/^episode:/, "");
  const image = episodeImageFromHtml(normalized, episodeId) ??
    (Array.isArray(baseline.additional_image_urls)
      ? safeProviderImage(baseline.additional_image_urls[0])
      : undefined);
  const age = lastJsonString(normalized, "ageRating");
  const contentRating = age === "Alle leeftijden"
    ? "nl:AL"
    : age?.match(/onder de (\d+) jaar/i)?.[1]
    ? `nl:${age.match(/onder de (\d+) jaar/i)?.[1]}`
    : age === "Leeftijdsadvies onbekend"
    ? "nl:unknown"
    : age;
  const collection = plainText(
    normalized.match(/href=["']\/zoeken[?]collectie=[^"']*["'][^>]*>([^<]*)/i)
      ?.[1] ?? "",
  ) || lastJsonString(normalized, "collection");
  return normalizeRecord({
    ...baseline,
    provider_id: request.provider_id,
    display_title: title,
    title,
    year: releaseDate ? Number(releaseDate.slice(0, 4)) : baseline.year,
    guids: [`beeldengeluid://${episodeId}`],
    availability: unavailable ? "unavailable" : "available",
    availability_reason: unavailable ? "not_playable" : undefined,
    content_kind: classifiedContentKind(showTitle, genres, tags),
    duration_seconds: Number.isFinite(duration) && duration >= 0
      ? Math.round(duration)
      : undefined,
    liveness: "finite",
    additional_image_urls: image ? [image] : [],
    metadata: {
      title,
      plot,
      show_title: showTitle,
      year: releaseDate ? Number(releaseDate.slice(0, 4)) : undefined,
      release_date: releaseDate,
      content_ratings: contentRating ? [contentRating] : [],
      genres,
      tags,
      people: peopleFromHtml(normalized),
      producers: jsonStrings(normalized, "productionCompanies"),
      original_broadcasters: jsonStringValues(
        normalized,
        "originalBroadcasters",
      ),
      broadcasters: jsonStringValues(normalized, "broadcasters"),
      collection,
      artwork: image ? [{ role: "thumb", url: image }] : [],
      guids: [`beeldengeluid://${episodeId}`],
    },
  }, 1);
}

async function enrich(request: EnrichRequest): Promise<void> {
  const sourceUrl = text(request.item.source_url);
  if (!sourceUrl) {
    emit({
      record_type: "outcome",
      outcome: "permanent_failure",
      code: "missing-item-url",
      message: "The overview item has no source URL.",
    });
    return;
  }
  const response = await requestPage(sourceUrl);
  if (response.status === 404 || response.status === 410) {
    emit({
      record_type: "outcome",
      outcome: "unavailable",
      code: "not-playable",
      message: "The Schatkamer programme is unavailable.",
    });
    emit(fullItem(request, response.body, true));
    return;
  }
  if (response.status === 429) {
    emit({
      record_type: "outcome",
      outcome: "transient_failure",
      code: "rate-limited",
      message: "The Schatkamer provider rate-limited this request.",
      retry_after_seconds: 60,
    });
    return;
  }
  if (response.error || response.status === 0 || response.status >= 500) {
    emit({
      record_type: "outcome",
      outcome: "transient_failure",
      code: response.status === 0
        ? "provider-timeout"
        : "provider-request-failed",
      message: (response.error || `Schatkamer returned HTTP ${response.status}`)
        .slice(0, 768),
    });
    return;
  }
  if (response.status >= 400) {
    emit({
      record_type: "outcome",
      outcome: "permanent_failure",
      code: "provider-rejected-request",
      message: `Schatkamer returned HTTP ${response.status}.`,
    });
    return;
  }
  const normalized = normalizedHtml(response.body);
  if (!/<h[13]\b|"durationNumber"\s*:|"publishedAtISO"\s*:/i.test(normalized)) {
    emit({
      record_type: "outcome",
      outcome: "permanent_failure",
      code: "malformed-provider-page",
      message:
        "The Schatkamer programme page did not contain expected metadata.",
    });
    return;
  }
  const item = fullItem(request, response.body);
  emit({ record_type: "outcome", outcome: "complete" });
  emit(item);
}

const operation = Deno.args[0];
if (["--extract-overview", "--extract-overview-tsv"].includes(operation)) {
  const path = Deno.args[1];
  if (!path) throw new Error("overview HTML path is missing");
  const html = await Deno.readTextFile(path);
  for (const item of extractOverviewItems(html)) {
    const availability = item.playable === false ? "unavailable" : "available";
    if (operation === "--extract-overview-tsv") {
      console.log([
        item.path,
        availability,
        JSON.stringify(item.title),
        JSON.stringify(item.description ?? null),
        JSON.stringify(item.releaseDate ?? null),
        JSON.stringify(item.image ?? null),
      ].join("\t"));
    } else {
      emit({
        path: item.path,
        title: item.title,
        description: item.description,
        release_date: item.releaseDate,
        image: item.image,
        availability,
      });
    }
  }
} else {
  const input = await new Response(Deno.stdin.readable).text();
  if (!input.trim()) throw new Error("media-list import request is missing");
  if (operation === "discover") {
    await discover(JSON.parse(input) as DiscoverRequest);
  } else if (operation === "enrich") {
    await enrich(JSON.parse(input) as EnrichRequest);
  } else {
    throw new Error(
      "usage: media-list-import.ts discover|enrich|--extract-overview <path>",
    );
  }
}
