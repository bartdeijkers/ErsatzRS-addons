// Internet Archive provider logic shared by the list and play operations.
//
// Runs unchanged under Deno and Node.js (type stripping): only `fetch` and
// `node:` built-ins are used, so the ARMv7 entrypoint can use Node.js where
// Deno publishes no build.

export const ADDON_VERSION = "0.1.0";
export const USER_AGENT =
  `ErsatzRS-InternetArchive/${ADDON_VERSION} (+https://github.com/bartdeijkers/ErsatzRS-addons)`;
export const ARCHIVE_ORIGIN = "https://archive.org";
export const MAX_ITEMS = 10_000;
const MAX_TEXT = 4_000;
const MAX_VALUES = 1_024;
const MAX_URL_BYTES = 2_048;
const SCRAPE_PAGE = 5_000;
const REQUEST_TIMEOUT_MS = 20_000;
const encoder = new TextEncoder();

export type Json = Record<string, unknown>;

export class ProviderError extends Error {
  code: string;
  status: number;
  constructor(code: string, message: string, status = 70) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

/// A parsed operator source or item URL.
export type Source =
  | { kind: "details"; identifier: string; file?: string }
  | { kind: "search"; query: string };

const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/;

export function parseSource(raw: string): Source {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new ProviderError("unsupported-url", "The source URL is invalid.", 64);
  }
  const host = url.hostname.toLowerCase();
  if (
    url.protocol !== "https:" && url.protocol !== "http:" ||
    url.username || url.password ||
    (host !== "archive.org" && host !== "www.archive.org")
  ) {
    throw new ProviderError("unsupported-url", "Only archive.org links are supported.", 64);
  }
  const segments = url.pathname.split("/").filter((part) => part.length > 0)
    .map((part) => decodeURIComponent(part));
  if (segments[0] === "details" && segments.length >= 2) {
    const identifier = segments[1];
    if (!IDENTIFIER.test(identifier)) {
      throw new ProviderError("unsupported-url", "The archive.org identifier is invalid.", 64);
    }
    // `@account` uploader pages and other non-item paths are not identifiers.
    const file = segments.length > 2 ? segments.slice(2).join("/") : undefined;
    if (file !== undefined && (file.includes("..") || /[\x00-\x1f\x7f]/.test(file))) {
      throw new ProviderError("unsupported-url", "The archive.org file name is invalid.", 64);
    }
    return file === undefined ? { kind: "details", identifier } : { kind: "details", identifier, file };
  }
  if (segments[0] === "search" || segments[0] === "search.php") {
    const query = (url.searchParams.get("query") ?? "").trim();
    if (!query || query.length > 2_000 || /[\x00-\x1f\x7f]/.test(query)) {
      throw new ProviderError("unsupported-url", "The archive.org search query is missing or invalid.", 64);
    }
    return { kind: "search", query };
  }
  throw new ProviderError(
    "unsupported-url",
    "Use an archive.org item, collection or search link.",
    64,
  );
}

export function detailsUrl(identifier: string, file?: string): string {
  const base = `${ARCHIVE_ORIGIN}/details/${encodeURIComponent(identifier)}`;
  return file === undefined ? base : `${base}/${file.split("/").map(encodeURIComponent).join("/")}`;
}

export function downloadUrl(identifier: string, file: string): string {
  return `${ARCHIVE_ORIGIN}/download/${encodeURIComponent(identifier)}/${
    file.split("/").map(encodeURIComponent).join("/")
  }`;
}

export type Fetcher = (url: string) => Promise<Json>;

/// Fetch one JSON document with the identifying User-Agent the Archive asks
/// automated clients to send. A 429 or 5xx is a transient provider failure.
export const fetchJson: Fetcher = async (url) => {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(url, {
      headers: { "User-Agent": USER_AGENT, Accept: "application/json" },
      signal: controller.signal,
    });
  } catch {
    throw new ProviderError("provider-unreachable", "The Internet Archive could not be reached.");
  } finally {
    clearTimeout(timer);
  }
  if (response.status === 429) {
    throw new ProviderError("provider-rate-limited", "The Internet Archive asked to slow down; try again later.");
  }
  if (!response.ok) {
    throw new ProviderError("provider-unreachable", `The Internet Archive answered HTTP ${response.status}.`);
  }
  try {
    const value = await response.json();
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error();
    return value as Json;
  } catch {
    throw new ProviderError("provider-invalid-response", "The Internet Archive returned an unreadable answer.");
  }
};

// ---------------------------------------------------------------------------
// Field normalisation

export function text(value: unknown, limit = MAX_TEXT): string | undefined {
  const first = Array.isArray(value) ? value.find((entry) => typeof entry === "string") : value;
  if (typeof first !== "string") return undefined;
  const cleaned = stripHtml(first).trim();
  if (!cleaned) return undefined;
  return cleaned.length > limit ? `${cleaned.slice(0, limit - 1).trimEnd()}…` : cleaned;
}

function stripHtml(value: string): string {
  return value
    .replace(/<\s*\/?\s*(br|p|div)\b[^>]*>/gi, "\n")
    .replace(/<[^>]*>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, "\"")
    .replace(/&#39;/g, "'")
    .replace(/[\x00-\x08\x0b-\x1f\x7f]/g, "")
    .replace(/\n{3,}/g, "\n\n");
}

export function values(...candidates: unknown[]): string[] {
  const result: string[] = [];
  const seen = new Set<string>();
  for (const candidate of candidates.flatMap((value) => Array.isArray(value) ? value : [value])) {
    if (typeof candidate !== "string") continue;
    // Uploaders often put several subjects in one semicolon-separated field.
    for (const part of candidate.split(";")) {
      const item = text(part, 200);
      const key = item?.toLocaleLowerCase();
      if (item && key && !seen.has(key)) {
        seen.add(key);
        result.push(item);
        if (result.length === MAX_VALUES) return result;
      }
    }
  }
  return result;
}

/// Archive dates are free text: `1994`, `1994-03`, `1994-03-12`, or an
/// ISO instant from search results.
export function parseDate(value: unknown): { year?: number; date?: string } {
  const raw = text(value, 64);
  if (!raw) return {};
  const match = /^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?/.exec(raw);
  if (!match) return {};
  const year = Number(match[1]);
  if (year < 1800 || year > new Date().getUTCFullYear() + 5) return {};
  if (match[2] && match[3]) {
    const date = `${match[1]}-${match[2]}-${match[3]}`;
    const parsed = new Date(`${date}T00:00:00Z`);
    if (!Number.isNaN(parsed.getTime()) && parsed.toISOString().startsWith(date)) {
      return { year, date };
    }
  }
  return { year };
}

/// Runtime is free text such as `22:44`, `1:05:12`, `25 min` or `1485.05`.
export function parseRuntime(value: unknown): number | undefined {
  const raw = text(value, 64);
  if (!raw) return undefined;
  if (/^\d+(\.\d+)?$/.test(raw)) return positiveSeconds(Number(raw));
  const minutes = /^(\d+)\s*(min|mins|minutes)\b/i.exec(raw);
  if (minutes) return positiveSeconds(Number(minutes[1]) * 60);
  const clock = /^(\d+):(\d{1,2})(?::(\d{1,2}))?(?:\.\d+)?$/.exec(raw);
  if (!clock) return undefined;
  const parts = clock.slice(1).filter((part) => part !== undefined).map(Number);
  if (parts.slice(1).some((part) => part >= 60)) return undefined;
  // Uploaders also write `MM:SS:FF` (frames); a leading field of 10 or more
  // in a three-part value is read that way rather than as ten-plus hours.
  const seconds = parts.length === 3 && parts[0] < 10
    ? parts[0] * 3600 + parts[1] * 60 + parts[2]
    : parts[0] * 60 + parts[1];
  return positiveSeconds(seconds);
}

function positiveSeconds(value: number): number | undefined {
  // Longer than four days is a mislabelled field rather than a programme.
  return Number.isFinite(value) && value > 0 && value < 4 * 86_400 ? Math.round(value) : undefined;
}

function safeHttpsUrl(value: string): string | undefined {
  if (encoder.encode(value).length > MAX_URL_BYTES) return undefined;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.hostname && !url.username && !url.password
      ? url.toString()
      : undefined;
  } catch {
    return undefined;
  }
}

export function thumbnailUrl(identifier: string): string | undefined {
  return safeHttpsUrl(`${ARCHIVE_ORIGIN}/services/img/${encodeURIComponent(identifier)}`);
}

// ---------------------------------------------------------------------------
// Item files

export type ArchiveFile = {
  name: string;
  source?: string;
  original?: string;
  format?: string;
  length?: string;
  height?: string;
  size?: string;
};

/// One playable programme inside an item: the uploaded original and the file
/// that is actually streamed for it.
export type Programme = {
  original: string;
  playable: string;
  durationSeconds?: number;
  height?: number;
};

const VIDEO_EXTENSION = /\.(mp4|m4v|mov|mkv|webm|ogv|avi|mpe?g|mpg|wmv|flv|ts|m2ts|vob|3gp|dv)$/i;
// Derivative formats in preference order: universally decodable H.264 first.
const PREFERRED_FORMATS = ["h.264", "h.264 hd", "mpeg4", "512kb mpeg4", "h.264 ia", "matroska", "ogg video"];

function isVideo(file: ArchiveFile): boolean {
  if (!VIDEO_EXTENSION.test(file.name)) return false;
  const format = (file.format ?? "").toLowerCase();
  // Thumbnails, animated previews and checksums never count as programmes.
  return !/(thumb|gif|metadata|torrent|spectrogram)/.test(format);
}

function rank(file: ArchiveFile): number {
  const format = (file.format ?? "").toLowerCase();
  const index = PREFERRED_FORMATS.indexOf(format);
  if (index >= 0) return index;
  return /\.mp4$/i.test(file.name) ? PREFERRED_FORMATS.length : PREFERRED_FORMATS.length + 1;
}

function number(value: unknown): number | undefined {
  const parsed = typeof value === "number" ? value : typeof value === "string" ? Number(value) : NaN;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
}

/// Group an item's video files by their uploaded original, sorted by name so
/// list and play always agree on which programme comes first.
export function programmes(files: unknown): Programme[] {
  if (!Array.isArray(files)) return [];
  const videos = files.filter((file): file is ArchiveFile =>
    !!file && typeof file === "object" && typeof (file as ArchiveFile).name === "string"
  ).filter(isVideo);
  const groups = new Map<string, ArchiveFile[]>();
  for (const file of videos) {
    const original = file.source === "derivative" && typeof file.original === "string" ? file.original : file.name;
    const group = groups.get(original) ?? [];
    group.push(file);
    groups.set(original, group);
  }
  const result: Programme[] = [];
  for (const [original, group] of groups) {
    // A derivative of a non-video original (for example a transcoded audio
    // file) still forms its own programme; keep only real video candidates.
    const best = group.slice().sort((left, right) => rank(left) - rank(right) || left.name.localeCompare(right.name))[0];
    const originalFile = group.find((file) => file.name === original);
    const duration = number(originalFile?.length) ?? number(best.length);
    const height = number(best.height);
    result.push({
      original,
      playable: best.name,
      durationSeconds: duration === undefined ? undefined : positiveSeconds(duration),
      height: height === undefined ? undefined : Math.round(height),
    });
  }
  return result.sort((left, right) => left.original.localeCompare(right.original, "en"));
}

export type ItemAvailability = {
  availability: "available" | "unavailable";
  reason?: "content_restricted" | "unavailable";
};

export function itemAvailability(document: Json): ItemAvailability {
  if (!document || Object.keys(document).length === 0 || document.is_dark === true) {
    return { availability: "unavailable", reason: "unavailable" };
  }
  const metadata = (document.metadata ?? {}) as Json;
  if (String(metadata["access-restricted-item"] ?? "").toLowerCase() === "true") {
    return { availability: "unavailable", reason: "content_restricted" };
  }
  return { availability: "available" };
}

export async function itemMetadata(identifier: string, fetcher: Fetcher = fetchJson): Promise<Json> {
  return await fetcher(`${ARCHIVE_ORIGIN}/metadata/${encodeURIComponent(identifier)}`);
}

// ---------------------------------------------------------------------------
// Search

const SEARCH_FIELDS = [
  "identifier",
  "title",
  "description",
  "date",
  "year",
  "runtime",
  "subject",
  "creator",
  "language",
  "licenseurl",
  "mediatype",
  "collection",
];

/// Page through the Scrape API, which returns a stable cursor for result
/// sets of any size. Only video items are requested.
export async function search(query: string, fetcher: Fetcher = fetchJson, limit = MAX_ITEMS): Promise<Json[]> {
  const result: Json[] = [];
  const seen = new Set<string>();
  let cursor: string | undefined;
  do {
    const url = new URL(`${ARCHIVE_ORIGIN}/services/search/v1/scrape`);
    url.searchParams.set("q", `(${query}) AND mediatype:(movies)`);
    url.searchParams.set("fields", SEARCH_FIELDS.join(","));
    url.searchParams.set("count", String(Math.max(100, Math.min(SCRAPE_PAGE, limit - result.length))));
    if (cursor) url.searchParams.set("cursor", cursor);
    const page = await fetcher(url.toString());
    const items = Array.isArray(page.items) ? page.items : [];
    for (const item of items) {
      const identifier = item && typeof item === "object" ? (item as Json).identifier : undefined;
      // Identities must be unique in a list; a repeated result is dropped.
      if (typeof identifier === "string" && !seen.has(identifier)) {
        seen.add(identifier);
        result.push(item as Json);
        if (result.length >= limit) return result;
      }
    }
    const next = typeof page.cursor === "string" && page.cursor ? page.cursor : undefined;
    if (next === cursor || items.length === 0) break;
    cursor = next;
  } while (cursor);
  return result;
}

export function collectionQuery(identifier: string): string {
  return `collection:(${identifier})`;
}
