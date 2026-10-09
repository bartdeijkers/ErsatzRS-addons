// Empty YouTube SRT cues carry no visible text. Retain every other block,
// including malformed blocks, for the host's strict publication verification.
export function removeEmptySrtCues(bytes: Uint8Array): Uint8Array {
  const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  const blocks = text.replace(/\r\n?/g, "\n").split(/\n(?:[ \t]*\n)+/);
  const timing =
    /^(\d{2,}:[0-5]\d:[0-5]\d,\d{3})[ \t]+-->[ \t]+(\d{2,}:[0-5]\d:[0-5]\d,\d{3})$/;
  const milliseconds = (value: string) => {
    const [hours, minutes, seconds, fraction] = value.split(/[:,]/).map(Number);
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + fraction;
  };
  let removed = false;
  const retained = blocks.filter((block) => {
    const lines = block.split("\n");
    const match = timing.exec(lines[1] ?? "");
    if (
      /^\d+$/.test(lines[0]) && match &&
      Number.isSafeInteger(milliseconds(match[2])) &&
      milliseconds(match[1]) < milliseconds(match[2]) &&
      lines.slice(2).every((line) => line.trim() === "")
    ) {
      removed = true;
      return false;
    }
    return true;
  });
  if (!removed) return bytes;
  const content = retained.filter((block) => block.trim() !== "").join("\n\n");
  return new TextEncoder().encode(content ? content + "\n\n" : "");
}
