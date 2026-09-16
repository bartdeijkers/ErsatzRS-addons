/** Shared normalized yt-dlp metadata; source age is not an official rating. */
export function sourceRatings(age: unknown): string[] {
  return typeof age === "number" && Number.isSafeInteger(age) && age >= 0
    ? [`age:${age}`]
    : [];
}

export function sourceStudio(channel: unknown, uploader: unknown): string[] {
  for (const value of [channel, uploader]) {
    if (typeof value === "string" && value.trim()) return [value.trim()];
  }
  return [];
}
