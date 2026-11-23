// Enumerate an archive.org item, collection or search as ErsatzRS records.
//
// One package serves two host contracts from the same entries:
// - media-list.list.v6 when ERSATZRS_MEDIA_LIST_URL is set (list import);
// - remote-stream.list.v4 when ERSATZRS_REMOTE_STREAM_PLAYLIST_URL is set
//   (the scanner of the generated Remote Streams library).

import {
  collectionQuery,
  detailsUrl,
  type Fetcher,
  fetchJson,
  itemAvailability,
  itemMetadata,
  type Json,
  MAX_ITEMS,
  parseDate,
  parseRuntime,
  parseSource,
  programmes,
  ProviderError,
  search,
  text,
  thumbnailUrl,
  values,
} from "./archive.mts";

const MAX_ID_BYTES = 384;
const encoder = new TextEncoder();

export type Entry = {
  providerId: string;
  url: string;
  identifier: string;
  title: string;
  plot?: string;
  year?: number;
  date?: string;
  durationSeconds?: number;
  tags: string[];
  languages: string[];
  creators: string[];
  collections: string[];
  availability: "available" | "unavailable";
  reason?: "content_restricted" | "unavailable";
};

export type Listing = {
  sourceUrl: string;
  name: string;
  description?: string;
  identifier?: string;
  entries: Entry[];
};

function bytes(value: string): number {
  return encoder.encode(value).length;
}

function readableFileTitle(file: string): string {
  const stem = file.replace(/^.*\//, "").replace(/\.[^.]+$/, "");
  return stem.replace(/[_]+/g, " ").replace(/\s+/g, " ").trim() || file;
}

function fromSearchResult(result: Json): Entry | undefined {
  const identifier = String(result.identifier);
  const title = text(result.title, 500) ?? identifier;
  const { year, date } = parseDate(result.date ?? result.year);
  if (bytes(identifier) > MAX_ID_BYTES) return undefined;
  return {
    providerId: identifier,
    url: detailsUrl(identifier),
    identifier,
    title,
    plot: text(result.description),
    year,
    date,
    durationSeconds: parseRuntime(result.runtime),
    tags: values(result.subject).slice(0, 25),
    languages: values(result.language).slice(0, 10),
    creators: values(result.creator).slice(0, 10),
    collections: values(result.collection),
    availability: "available",
  };
}

function fromItem(identifier: string, document: Json, onlyFile?: string): Entry[] {
  const metadata = (document.metadata ?? {}) as Json;
  const state = itemAvailability(document);
  const title = text(metadata.title, 500) ?? identifier;
  const { year, date } = parseDate(metadata.date ?? metadata.year);
  const shared = {
    identifier,
    plot: text(metadata.description),
    year,
    date,
    tags: values(metadata.subject),
    languages: values(metadata.language),
    creators: values(metadata.creator),
    collections: values(metadata.collection),
    availability: state.availability,
    reason: state.reason,
  };
  if (state.availability === "unavailable") {
    return [{ ...shared, providerId: identifier, url: detailsUrl(identifier), title }];
  }
  let found = programmes(document.files);
  if (onlyFile !== undefined) {
    found = found.filter((programme) => programme.original === onlyFile || programme.playable === onlyFile);
    if (found.length === 0) {
      throw new ProviderError("item-not-found", "The linked file is not a video in this archive.org item.", 65);
    }
  }
  if (found.length === 0) {
    throw new ProviderError("no-video", "This archive.org item has no video files.", 65);
  }
  const single = found.length === 1 && onlyFile === undefined;
  return found.flatMap((programme) => {
    const providerId = single ? identifier : `${identifier}/${programme.original}`;
    if (bytes(providerId) > MAX_ID_BYTES) return [];
    return [{
      ...shared,
      providerId,
      url: single ? detailsUrl(identifier) : detailsUrl(identifier, programme.original),
      title: single ? title : `${title} – ${readableFileTitle(programme.original)}`,
      durationSeconds: programme.durationSeconds ?? (single ? parseRuntime(metadata.runtime) : undefined),
    }];
  });
}

/// Resolve the operator's link into a named, ordered listing.
export async function listing(sourceUrl: string, fetcher: Fetcher = fetchJson): Promise<Listing> {
  const source = parseSource(sourceUrl);
  if (source.kind === "search") {
    const results = await search(source.query, fetcher);
    return {
      sourceUrl,
      name: `Internet Archive: ${source.query}`.slice(0, 200),
      description: `archive.org search results for "${source.query}".`,
      entries: results.flatMap((result) => fromSearchResult(result) ?? []),
    };
  }
  const document = await itemMetadata(source.identifier, fetcher);
  const metadata = (document.metadata ?? {}) as Json;
  if (String(metadata.mediatype ?? "") === "collection" && source.file === undefined) {
    const results = await search(collectionQuery(source.identifier), fetcher);
    return {
      sourceUrl,
      name: text(metadata.title, 200) ?? source.identifier,
      description: text(metadata.description),
      identifier: source.identifier,
      entries: results.flatMap((result) => fromSearchResult(result) ?? []),
    };
  }
  if (Object.keys(document).length === 0) {
    throw new ProviderError("item-not-found", "This archive.org item does not exist or was removed.", 65);
  }
  return {
    sourceUrl,
    name: text(metadata.title, 200) ?? source.identifier,
    description: text(metadata.description),
    identifier: source.identifier,
    entries: fromItem(source.identifier, document, source.file),
  };
}

// ---------------------------------------------------------------------------
// Classification

const KIND_BY_COLLECTION: [RegExp, string][] = [
  [/^(music_videos|musicvideos)$/i, "music_video"],
  [/^(feature_films|moviesandfilms|film_noir|sci-fi_horror|silent_films|comedy_films|cartoons_movies)$/i, "movie"],
  [/^(tvprograms|classic_tv|television|tv_shows|classic_tv_1950s|classic_tv_1960s|computerchronicles)$/i, "television_episode"],
  [/^(prelinger|ephemera|classic_tv_commercials|tvcommercials|adviews)$/i, "other_video"],
];

export function contentKind(entry: Entry): string {
  for (const [pattern, kind] of KIND_BY_COLLECTION) {
    if (entry.collections.some((collection) => pattern.test(collection))) return kind;
  }
  return "auto";
}

// ---------------------------------------------------------------------------
// Record shapes

function guid(entry: Entry): string {
  return `internet-archive://${entry.providerId}`;
}

function metadataDocument(entry: Entry, collection: string | undefined, plotLimit: number): Json {
  const thumb = thumbnailUrl(entry.identifier);
  return {
    title: entry.title,
    plot: entry.plot === undefined ? undefined : text(entry.plot, plotLimit),
    year: entry.year,
    release_date: entry.date,
    tags: entry.tags,
    languages: entry.languages,
    people: entry.creators.map((name, order) => ({ name, role: "Creator", order })),
    collection,
    artwork: thumb ? [{ url: thumb, role: "thumb" }] : [],
    guids: [guid(entry)],
  };
}

export function mediaListRecords(list: Listing, plotLimit = 4_000): Json[] {
  const thumb = list.identifier ? thumbnailUrl(list.identifier) : undefined;
  const records: Json[] = [{
    record_type: "list",
    provider_id: list.sourceUrl,
    name: list.name,
    description: list.description ?? null,
    metadata: {
      title: list.name,
      plot: list.description,
      artwork: thumb ? [{ url: thumb, role: "fanart" }] : [],
      guids: [`internet-archive-list://${list.sourceUrl}`],
    },
  }];
  list.entries.slice(0, MAX_ITEMS).forEach((entry, rank) => {
    const thumbUrl = thumbnailUrl(entry.identifier);
    const record: Json = {
      record_type: "item",
      provider_id: entry.providerId,
      rank,
      display_title: entry.title,
      title: entry.title,
      year: entry.year ?? null,
      kind: "remote_stream",
      guids: [guid(entry)],
      source_url: entry.url,
      availability: entry.availability,
      content_kind: contentKind(entry),
      duration_seconds: entry.durationSeconds ?? null,
      additional_image_urls: thumbUrl ? [thumbUrl] : null,
      metadata: metadataDocument(entry, list.name, plotLimit),
      liveness: "finite",
    };
    if (entry.availability === "unavailable") {
      record.availability_reason = "not_playable";
      record.availability_reason_code = entry.reason ?? "unavailable";
    }
    records.push(record);
  });
  return records;
}

export function remoteStreamRecords(list: Listing, compact = false): Json[] {
  return list.entries.slice(0, MAX_ITEMS).map((entry) => {
    const record: Json = {
      id: entry.providerId,
      provider_id: entry.providerId,
      url: entry.url,
      title: entry.title,
      duration_seconds: entry.durationSeconds ?? null,
      thumbnail_url: thumbnailUrl(entry.identifier) ?? null,
      year: entry.year ?? null,
      release_date: entry.date ? `${entry.date}T00:00:00Z` : null,
      collection: list.name,
      availability: entry.availability,
      content_kind: contentKind(entry),
      guids: [guid(entry)],
      liveness: "finite",
    };
    record.plot = entry.plot === undefined ? null : compact ? text(entry.plot, 300) ?? null : entry.plot;
    if (!compact) {
      record.tags = entry.tags.length ? entry.tags : null;
      record.people = entry.creators.length ? entry.creators.map((name) => ({ name, role: "Creator" })) : null;
    }
    if (entry.availability === "unavailable") record.availability_reason = entry.reason ?? "unavailable";
    return record;
  });
}

/// Serialise records as NDJSON, dropping JSON `undefined` members.
export function ndjson(records: Json[]): string {
  return records.map((record) => JSON.stringify(record)).join("\n") + "\n";
}

// Stay safely below the host's stdout caps (16 MiB media list, 8 MiB
// Remote Stream); a very large collection falls back to compact records.
const MEDIA_LIST_BUDGET = 15 * 1024 * 1024;
const REMOTE_STREAM_BUDGET = 7 * 1024 * 1024;

export async function runList(env: (key: string) => string | undefined, fetcher: Fetcher = fetchJson): Promise<string> {
  const mediaListUrl = env("ERSATZRS_MEDIA_LIST_URL");
  const playlistUrl = env("ERSATZRS_REMOTE_STREAM_PLAYLIST_URL");
  const sourceUrl = mediaListUrl ?? playlistUrl;
  if (!sourceUrl) throw new ProviderError("missing-setting", "An archive.org link is required.", 64);
  const list = await listing(sourceUrl, fetcher);
  if (list.entries.length === 0) {
    throw new ProviderError("no-video", "The archive.org link contains no video items.", 65);
  }
  if (mediaListUrl) {
    let output = ndjson(mediaListRecords(list));
    if (bytes(output) > MEDIA_LIST_BUDGET) {
      output = ndjson(mediaListRecords(list, 300));
    }
    if (bytes(output) > MEDIA_LIST_BUDGET) {
      throw new ProviderError("list-too-large", "The archive.org list is too large to import at once.", 65);
    }
    return output;
  }
  let output = ndjson(remoteStreamRecords(list));
  if (bytes(output) > REMOTE_STREAM_BUDGET) output = ndjson(remoteStreamRecords(list, true));
  if (bytes(output) > REMOTE_STREAM_BUDGET) {
    throw new ProviderError("list-too-large", "The archive.org list is too large to scan at once.", 65);
  }
  return output;
}
