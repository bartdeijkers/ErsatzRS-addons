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
  available: boolean;
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
        available: true,
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
        available: true,
      },
    });
  }
  const jsonUrl =
    /"url"\s*:\s*"https:\/\/schatkamer[.]beeldengeluid[.]nl(?<path>\/serie\/\d+\/[^"\/]+\/aflevering\/\d+)"(?<tail>[\s\S]{0,1600}?)(?="url"\s*:|$)/gi;
  for (const match of html.matchAll(jsonUrl)) {
    const path = match.groups?.path;
    if (!path) continue;
    const tail = match.groups?.tail ?? "";
    const playable = !/"isPlayable"\s*:\s*false/i.test(tail);
    candidates.push({
      index: match.index,
      item: {
        path,
        title: lastJsonString(tail, "title") ?? titleFromPath(path),
        description: lastJsonString(tail, "description"),
        releaseDate: dateFromHtml(tail),
        image: imageFromHtml(tail),
        available: playable,
      },
    });
  }
  candidates.sort((left, right) => left.index - right.index);
  const seen = new Set<string>();
  return candidates.flatMap(({ item }) => {
    const id = item.path.split("/").at(-1);
    if (!id || seen.has(id)) return [];
    seen.add(id);
    return [item];
  });
}

function encodeCursor(cursor: Cursor): string {
  return btoa(JSON.stringify(cursor)).replaceAll("+", "-").replaceAll("/", "_")
    .replace(/=+$/, "");
}

function decodeCursor(value?: string): Cursor {
  if (!value) return { page: 1, offset: 0, rank: 0 };
  try {
    const normalized = value.replaceAll("-", "+").replaceAll("_", "/");
    const decoded = atob(
      normalized + "=".repeat((4 - normalized.length % 4) % 4),
    );
    const cursor = object(JSON.parse(decoded));
    const page = Number(cursor?.page);
    const offset = Number(cursor?.offset);
    const rank = Number(cursor?.rank);
    if (
      [page, offset, rank].every(Number.isSafeInteger) && page >= 1 &&
      offset >= 0 && rank >= 0
    ) {
      return { page, offset, rank };
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
    availability: item.available ? "available" : "unavailable",
    availability_reason: item.available ? undefined : "not_playable",
    content_kind: "auto",
    liveness: "finite",
    thumbnail_url: item.image,
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
  const cursor = decodeCursor(request.cursor);
  const maxItems = Math.min(Math.max(request.limits.max_items, 1), 250);
  const isEpisode = /\/aflevering\/\d+\/?$/.test(source.pathname);
  if (isEpisode) {
    const path = source.pathname.replace(/\/$/, "");
    const item: OverviewItem = {
      path,
      title: titleFromPath(path),
      available: true,
    };
    emit({ record_type: "page", complete: true, total_hint: 1 });
    emit(listHeader(request.source_url, ""));
    emit(overviewRecord(item, 0));
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
  const selected = allItems.slice(cursor.offset, cursor.offset + maxItems);
  const exhaustedPage = cursor.offset + selected.length >= allItems.length;
  const complete = allItems.length === 0;
  const next = complete
    ? undefined
    : exhaustedPage
    ? { page: cursor.page + 1, offset: 0, rank: cursor.rank + selected.length }
    : {
      page: cursor.page,
      offset: cursor.offset + selected.length,
      rank: cursor.rank + selected.length,
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
  const durationMatch = normalized.match(/"durationNumber"\s*:\s*(\d+)/i);
  const duration = durationMatch
    ? Number(durationMatch[1])
    : Number(baseline.duration_seconds);
  const genres = jsonStrings(normalized, "genres");
  const tags = jsonStrings(normalized, "subjects");
  const image = imageFromHtml(normalized) ??
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
  const episodeId = request.provider_id.replace(/^episode:/, "");
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
const input = await new Response(Deno.stdin.readable).text();
if (!input.trim()) throw new Error("media-list import request is missing");
if (operation === "discover") {
  await discover(JSON.parse(input) as DiscoverRequest);
} else if (operation === "enrich") {
  await enrich(JSON.parse(input) as EnrichRequest);
} else throw new Error("usage: media-list-import.ts discover|enrich");
