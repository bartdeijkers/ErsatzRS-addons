interface Chapter {
  start_time?: number;
  title?: string;
}

interface Metadata {
  id?: string;
  description?: string;
  upload_date?: string;
  release_date?: string;
  release_year?: number;
  categories?: string[];
  tags?: string[];
  thumbnail?: string;
  availability?: string;
  chapters?: Chapter[];
}

function chapterTime(value: number): string {
  const seconds = Math.round(value);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`
    : `${minutes}:${String(remainder).padStart(2, "0")}`;
}

function chapterInput(chapters: Chapter[] | undefined): string | undefined {
  const lines: string[] = [];
  let lastStart = -1;
  for (const chapter of chapters ?? []) {
    if (typeof chapter.start_time !== "number" || !Number.isFinite(chapter.start_time) || !chapter.title?.trim()) continue;
    const start = Math.round(chapter.start_time);
    if (start <= lastStart) continue;
    lines.push(`${chapterTime(start)} ${chapter.title.trim()}`);
    lastStart = start;
  }
  return lines.length > 0 ? lines.join("\n") : undefined;
}

const decoder = new TextDecoder();
let buffered = "";
for await (const chunk of Deno.stdin.readable) {
  buffered += decoder.decode(chunk, { stream: true });
}
buffered += decoder.decode();
for (const line of buffered.split(/\r?\n/)) {
  if (!line.trim()) continue;
  const item = JSON.parse(line) as Metadata;
  if (!item.id) continue;
  const availability = ["public", "unlisted"].includes(item.availability ?? "")
    ? "available"
    : ["private", "premium_only", "subscriber_only", "needs_auth"].includes(item.availability ?? "")
    ? "unavailable"
    : "unknown";
  const rawDate = item.upload_date ?? item.release_date;
  const releaseDate = rawDate?.match(/^\d{8}$/)
    ? `${rawDate.slice(0, 4)}-${rawDate.slice(4, 6)}-${rawDate.slice(6, 8)}`
    : rawDate ?? null;
  const row: Record<string, unknown> = {
    provider_id: item.id,
    plot: item.description ?? null,
    release_date: releaseDate,
    year: item.release_year ?? (rawDate ? Number(rawDate.slice(0, 4)) : null),
    genres: item.categories ?? [],
    tags: item.tags ?? [],
    thumbnail_url: item.thumbnail ?? null,
    availability,
    availability_reason: availability === "unavailable" ? "not_playable" : null,
  };
  const chapters = chapterInput(item.chapters);
  if (chapters) row.chapter_input = chapters;
  console.log(JSON.stringify(row));
}
