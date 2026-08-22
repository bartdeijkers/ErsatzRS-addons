type JsonObject = Record<string, unknown>;

const MAX_VALUES = 1024;
const ITEM_KINDS = new Set([
  "movie",
  "show",
  "season",
  "episode",
  "remote_stream",
]);
const AVAILABILITY = new Set(["available", "unavailable", "unknown"]);
const CONTENT_KINDS = new Set([
  "auto",
  "television_episode",
  "movie",
  "music_video",
  "other_video",
  "song",
  "image",
]);
const COLLECTION_ROLES = new Set(["auto", "primary", "extra"]);
const ARTWORK_ROLES = new Set(["poster", "fanart", "thumb", "other"]);

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

function unsigned(value: unknown): number | undefined {
  const result = integer(value);
  return result !== undefined && result >= 0 ? result : undefined;
}

function repeated(value: unknown): unknown[] {
  if (value === null || value === undefined) return [];
  return Array.isArray(value) ? value : [value];
}

function strings(value: unknown): string[] {
  const result: string[] = [];
  const seen = new Set<string>();
  for (const candidate of repeated(value)) {
    const item = text(candidate);
    const key = item?.toLocaleLowerCase();
    if (!item || !key || seen.has(key)) continue;
    seen.add(key);
    result.push(item);
    if (result.length === MAX_VALUES) break;
  }
  return result;
}

function dateOnly(value: unknown): string | undefined {
  const match = text(value)?.match(/^(\d{4})-(\d{2})-(\d{2})(?:T.*)?$/);
  if (!match) return undefined;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(Date.UTC(year, month - 1, day));
  if (
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() !== month - 1 ||
    date.getUTCDate() !== day
  ) return undefined;
  return `${match[1]}-${match[2]}-${match[3]}`;
}

function safeHttpsUrl(value: unknown): string | undefined {
  const candidate = text(value);
  if (!candidate) return undefined;
  try {
    const url = new URL(candidate);
    return url.protocol === "https:" && !url.username && !url.password
      ? url.toString()
      : undefined;
  } catch {
    return undefined;
  }
}

function people(value: unknown): JsonObject[] {
  const result: JsonObject[] = [];
  for (const candidate of repeated(value)) {
    const source = object(candidate);
    const name = text(source?.name);
    if (!source || !name) continue;
    const person: JsonObject = { name };
    const role = text(source.role);
    const order = integer(source.order);
    const thumb = safeHttpsUrl(source.thumb);
    if (role) person.role = role;
    if (order !== undefined) person.order = order;
    if (thumb) person.thumb = thumb;
    result.push(person);
    if (result.length === MAX_VALUES) break;
  }
  return result;
}

function artwork(value: unknown): JsonObject[] {
  const result: JsonObject[] = [];
  for (const candidate of repeated(value)) {
    const source = object(candidate);
    const url = safeHttpsUrl(source?.url);
    if (!source || !url) continue;
    const role = text(source.role);
    const image: JsonObject = {
      url,
      role: role && ARTWORK_ROLES.has(role) ? role : "other",
    };
    const width = unsigned(source.width);
    const height = unsigned(source.height);
    const language = text(source.language);
    if (width !== undefined && width > 0) image.width = width;
    if (height !== undefined && height > 0) image.height = height;
    if (language) image.language = language;
    result.push(image);
    if (result.length === MAX_VALUES) break;
  }
  return result;
}

function metadata(value: unknown, line: number): JsonObject | undefined {
  const source = object(value);
  if (!source) return undefined;
  const result: JsonObject = {};
  for (
    const field of [
      "title",
      "original_title",
      "sort_title",
      "outline",
      "plot",
      "tagline",
      "show_title",
      "collection",
    ]
  ) {
    const candidate = text(source[field]);
    if (candidate) result[field] = candidate;
  }
  for (const field of ["season", "episode", "year"]) {
    const candidate = integer(source[field]);
    if (candidate !== undefined) result[field] = candidate;
  }
  const releaseDate = dateOnly(source.release_date);
  if (releaseDate) result.release_date = releaseDate;
  else if (source.release_date !== null && source.release_date !== undefined) {
    console.error(
      `media-list-adapter: line ${line} omitted invalid release_date`,
    );
  }
  for (
    const field of [
      "content_ratings",
      "genres",
      "tags",
      "studios",
      "music_labels",
      "languages",
      "writers",
      "directors",
      "artists",
      "producers",
      "original_broadcasters",
      "broadcasters",
      "guids",
    ]
  ) result[field] = strings(source[field]);
  result.people = people(source.people);
  result.artwork = artwork(source.artwork);
  return result;
}

function requiredText(source: JsonObject, field: string, line: number): string {
  const result = text(source[field]);
  if (!result) throw new Error(`line ${line} requires non-empty ${field}`);
  return result;
}

function normalizeRecord(value: unknown, line: number): JsonObject {
  const source = object(value);
  if (!source) throw new Error(`line ${line} is not a JSON object`);
  const recordType = requiredText(source, "record_type", line);
  if (recordType === "list") {
    const result: JsonObject = {
      record_type: "list",
      provider_id: requiredText(source, "provider_id", line),
      name: requiredText(source, "name", line),
    };
    const description = text(source.description);
    const document = metadata(source.metadata, line);
    if (description) result.description = description;
    if (document) result.metadata = document;
    return result;
  }
  if (recordType !== "item") {
    throw new Error(`line ${line} has unknown record_type`);
  }
  const rank = integer(source.rank);
  if (rank === undefined) throw new Error(`line ${line} requires integer rank`);
  const rawKind = requiredText(source, "kind", line);
  if (!ITEM_KINDS.has(rawKind)) {
    throw new Error(`line ${line} has invalid kind`);
  }
  const result: JsonObject = {
    record_type: "item",
    provider_id: requiredText(source, "provider_id", line),
    rank,
    display_title: requiredText(source, "display_title", line),
    title: requiredText(source, "title", line),
    kind: rawKind,
    guids: strings(source.guids),
  };
  for (const field of ["year", "season", "episode"]) {
    const candidate = integer(source[field]);
    if (candidate !== undefined) result[field] = candidate;
  }
  for (
    const field of ["source_url", "availability_reason", "parent_provider_id"]
  ) {
    const candidate = text(source[field]);
    if (candidate) result[field] = candidate;
  }
  for (
    const field of [
      "duration_seconds",
      "fragment_start_seconds",
      "fragment_end_seconds",
    ]
  ) {
    const candidate = unsigned(source[field]);
    if (candidate !== undefined) result[field] = candidate;
  }
  const availability = text(source.availability) ?? "available";
  result.availability = AVAILABILITY.has(availability)
    ? availability
    : "unknown";
  const contentKind = text(source.content_kind) ?? "auto";
  result.content_kind = CONTENT_KINDS.has(contentKind) ? contentKind : "auto";
  const collectionRole = text(source.collection_role) ?? "auto";
  result.collection_role = COLLECTION_ROLES.has(collectionRole)
    ? collectionRole
    : "auto";
  result.additional_image_urls = repeated(source.additional_image_urls)
    .map(safeHttpsUrl)
    .filter((url): url is string => Boolean(url))
    .slice(0, MAX_VALUES);
  const document = metadata(source.metadata, line);
  if (document) result.metadata = document;
  return result;
}

function decodeAttribute(value: string): string {
  return value.replaceAll("&amp;", "&").replaceAll("&quot;", '"')
    .replaceAll("&#39;", "'").replaceAll("&#x27;", "'");
}

function decodeBase64Url(value: string): string | undefined {
  try {
    const normalized = value.replaceAll("-", "+").replaceAll("_", "/");
    const padded = normalized + "=".repeat((4 - normalized.length % 4) % 4);
    const bytes = Uint8Array.from(
      atob(padded),
      (character) => character.charCodeAt(0),
    );
    return new TextDecoder().decode(bytes);
  } catch {
    return undefined;
  }
}

async function extractCards(path: string): Promise<void> {
  const html = await Deno.readTextFile(path);
  const cards =
    /<a\b[^>]*href="(?<path>\/serie\/\d+\/[^"/]+\/aflevering\/\d+)"[^>]*>(?<body>[\s\S]*?)<\/a>/gi;
  for (const match of html.matchAll(cards)) {
    const episodePath = match.groups?.path;
    const body = match.groups?.body ?? "";
    const source = body.match(
      /\bsrc="(?<url>https:\/\/schatkamer[.]beeldengeluid[.]nl\/image-optimizer[?][^"]+)"/i,
    )
      ?.groups?.url;
    if (!episodePath || !source) continue;
    const optimizer = new URL(decodeAttribute(source));
    const decoded = decodeBase64Url(optimizer.searchParams.get("url") ?? "");
    const image = safeHttpsUrl(decoded);
    if (!image) continue;
    const host = new URL(image).hostname;
    if (
      !new Set(["schatkamer.beeldengeluid.nl", "sk-video.cdn.beeldengeluid.nl"])
        .has(host)
    ) {
      continue;
    }
    console.log(`${episodePath}\t${image}`);
  }
}

async function normalize(path: string): Promise<void> {
  const input = await Deno.readTextFile(path);
  let count = 0;
  for (const [index, line] of input.split(/\r?\n/).entries()) {
    if (!line.trim()) continue;
    console.log(JSON.stringify(normalizeRecord(JSON.parse(line), index + 1)));
    count++;
  }
  if (count === 0) throw new Error("media-list output is empty");
}

const [operation, path] = Deno.args;
if (!path || !["--extract-cards", "--normalize"].includes(operation)) {
  throw new Error(
    "usage: media-list-adapter.ts --extract-cards|--normalize <path>",
  );
}
if (operation === "--extract-cards") await extractCards(path);
else await normalize(path);
