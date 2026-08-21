interface Thumbnail {
  url?: string;
  width?: number;
  height?: number;
}

interface ProviderEntry {
  id?: string;
  title?: string;
  description?: string;
  webpage_url?: string;
  original_url?: string;
  availability?: string;
  duration?: number;
  series?: string;
  season_number?: number;
  episode_number?: number;
  release_year?: number;
  upload_date?: string;
  release_date?: string;
  categories?: string[];
  tags?: string[];
  channel?: string;
  uploader?: string;
  artist?: string;
  artists?: string[];
  creator?: string;
  creators?: string[];
  language?: string;
  album?: string;
  thumbnail?: string;
  thumbnail_width?: number;
  thumbnail_height?: number;
  thumbnails?: Thumbnail[];
  playlist_index?: number;
}

interface ProviderPlaylist extends ProviderEntry {
  entries?: ProviderEntry[];
}

const MAX_VALUES = 1024;
const MAX_URL_BYTES = 2048;
const encoder = new TextEncoder();

function text(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
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
    if (item && key && !seen.has(key)) {
      seen.add(key);
      result.push(item);
      if (result.length === MAX_VALUES) break;
    }
  }
  return result;
}

function safeHttpsUrl(value: unknown): string | undefined {
  const candidate = text(value);
  if (!candidate || encoder.encode(candidate).length > MAX_URL_BYTES) {
    return undefined;
  }
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

function releaseDate(entry: ProviderEntry): string | undefined {
  const raw = text(entry.upload_date) ?? text(entry.release_date);
  if (!raw) return undefined;
  if (/^\d{8}$/.test(raw)) {
    return `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`;
  }
  return /^\d{4}-\d{2}-\d{2}$/.test(raw) ? raw : undefined;
}

function year(entry: ProviderEntry): number | undefined {
  if (Number.isInteger(entry.release_year) && (entry.release_year ?? 0) > 0) {
    return entry.release_year;
  }
  const date = releaseDate(entry);
  return date ? Number(date.slice(0, 4)) : undefined;
}

function people(entry: ProviderEntry): Record<string, unknown>[] {
  const result: Record<string, unknown>[] = [];
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

function artwork(
  entry: ProviderEntry,
  role: "fanart" | "thumb",
): Record<string, unknown>[] {
  const candidates = [
    ...(entry.thumbnails ?? []).slice().reverse(),
    {
      url: entry.thumbnail,
      width: entry.thumbnail_width,
      height: entry.thumbnail_height,
    },
  ];
  const selected = candidates.find((candidate) => safeHttpsUrl(candidate.url));
  if (!selected) return [];
  const result: Record<string, unknown> = {
    url: safeHttpsUrl(selected.url),
    role,
  };
  if (Number.isInteger(selected.width) && (selected.width ?? 0) > 0) {
    result.width = selected.width;
  }
  if (Number.isInteger(selected.height) && (selected.height ?? 0) > 0) {
    result.height = selected.height;
  }
  return [result];
}

function availability(value: unknown): "available" | "unavailable" | "unknown" {
  if (["public", "unlisted"].includes(String(value ?? ""))) return "available";
  if (
    ["private", "premium_only", "subscriber_only", "needs_auth"].includes(
      String(value ?? ""),
    )
  ) {
    return "unavailable";
  }
  return "unknown";
}

function contentKind(entry: ProviderEntry): string {
  const identity = [
    entry.series && "ERSATZRS_TV",
    entry.artist && "ERSATZRS_MUSIC",
  ];
  const source = values(identity, entry.categories, entry.tags, entry.title)
    .join(" ").toLocaleLowerCase();
  if (/advertisement|commercial|reclame/.test(source)) return "other_video";
  if (
    /ersatzrs_music|music video|videoclip|concert|music|muziek/.test(source)
  ) return "music_video";
  if (/movie|film|speelfilm/.test(source)) return "movie";
  if (/ersatzrs_tv/.test(source)) return "television_episode";
  return "auto";
}

function metadata(
  entry: ProviderEntry,
  collection?: string,
): Record<string, unknown> {
  const channel = text(entry.channel) ?? text(entry.uploader);
  const date = releaseDate(entry);
  const document: Record<string, unknown> = {
    title: text(entry.title),
    plot: text(entry.description),
    show_title: text(entry.series),
    season: Number.isInteger(entry.season_number)
      ? entry.season_number
      : undefined,
    episode: Number.isInteger(entry.episode_number)
      ? entry.episode_number
      : undefined,
    year: year(entry),
    release_date: date,
    genres: values(entry.categories),
    tags: values(entry.tags),
    studios: [],
    languages: values(entry.language),
    people: people(entry),
    artists: values(entry.artists, entry.artist, entry.creators, entry.creator),
    original_broadcasters: values(channel),
    broadcasters: values(channel),
    collection: text(entry.album) ?? text(collection),
    artwork: artwork(entry, "thumb"),
    guids: entry.id ? [`yt-dlp://${entry.id}`] : [],
  };
  return document;
}

const sourceUrl = text(Deno.env.get("ERSATZRS_MEDIA_LIST_URL")) ??
  text(Deno.env.get("PLAYLIST_URL"));
if (!sourceUrl) throw new Error("playlist URL is unavailable");

const playlist = JSON.parse(
  await new Response(Deno.stdin.readable).text(),
) as ProviderPlaylist;
const listTitle = text(playlist.title) ?? "yt-dlp playlist";
const listPlot = text(playlist.description) ??
  "Remote videos selected by the supplied playlist link.";
const listChannel = text(playlist.channel) ?? text(playlist.uploader);
console.log(JSON.stringify({
  record_type: "list",
  provider_id: sourceUrl,
  name: listTitle,
  description: listPlot,
  metadata: {
    title: listTitle,
    plot: listPlot,
    tags: values(playlist.tags),
    people: people(playlist),
    original_broadcasters: values(listChannel),
    broadcasters: values(listChannel),
    artwork: artwork(playlist, "fanart"),
    guids: [`yt-dlp-list://${sourceUrl}`],
  },
}));

let rank = 0;
for (const entry of playlist.entries ?? []) {
  const id = text(entry.id);
  const title = text(entry.title);
  const stableUrl = text(entry.webpage_url) ?? text(entry.original_url);
  if (!id || !title || !stableUrl) continue;
  const state = availability(entry.availability);
  const row: Record<string, unknown> = {
    record_type: "item",
    provider_id: id,
    rank,
    display_title: title,
    title,
    kind: "remote_stream",
    guids: [`yt-dlp://${id}`],
    source_url: stableUrl,
    availability: state,
    content_kind: contentKind(entry),
    duration_seconds:
      Number.isFinite(entry.duration) && (entry.duration ?? -1) >= 0
        ? Math.round(entry.duration ?? 0)
        : undefined,
    additional_image_urls: artwork(entry, "thumb").map((candidate) =>
      candidate.url
    ),
    metadata: metadata(entry, listTitle),
  };
  if (state === "unavailable") row.availability_reason = "not_playable";
  console.log(JSON.stringify(row));
  rank++;
}
