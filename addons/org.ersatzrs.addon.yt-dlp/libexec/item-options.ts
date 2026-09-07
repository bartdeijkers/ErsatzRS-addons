// Only typed option values cross this boundary; never accept profile paths.
export function itemOptions(value: unknown): { browser: string; remove: boolean } {
  const envelope = value as { schema?: unknown; values?: Record<string, unknown> };
  if (!envelope || envelope.schema !== "media-list.options.v1" ||
    !envelope.values || typeof envelope.values !== "object" || Array.isArray(envelope.values)) {
    throw new Error("invalid item options");
  }
  const values = envelope.values;
  if (Object.keys(values).some((key) => !["cookies_from_browser", "sponsorblock_remove"].includes(key))) {
    throw new Error("unknown item option");
  }
  const browser = values.cookies_from_browser === undefined ? "none" : values.cookies_from_browser;
  if (typeof browser !== "string" || !["none", "firefox", "chrome", "chromium"].includes(browser) ||
    (values.sponsorblock_remove !== undefined && typeof values.sponsorblock_remove !== "boolean")) {
    throw new Error("invalid item option value");
  }
  // Effective operation envelopes omit options that do not target that operation.
  return { browser, remove: values.sponsorblock_remove === true };
}

export function browserArguments(value: unknown): string[] {
  const { browser } = itemOptions(value);
  return browser === "none" ? [] : ["--cookies-from-browser", browser];
}

export async function boundedCommand(
  executable: string,
  args: string[],
  timeoutMilliseconds = 60_000,
  maximumOutputBytes = 4 * 1024 * 1024,
  environment: Record<string, string> = {},
): Promise<{ success: boolean; stdout: string; stderr: string }> {
  const child = new Deno.Command(executable, {
    args, env: environment, stdin: "null", stdout: "piped", stderr: "piped",
  }).spawn();
  const kill = () => { try { child.kill("SIGKILL"); } catch { /* Already exited. */ } };
  const timer = setTimeout(kill, timeoutMilliseconds);
  async function collect(stream: ReadableStream<Uint8Array>): Promise<string> {
    const chunks: Uint8Array[] = [];
    let length = 0;
    for await (const chunk of stream) {
      length += chunk.length;
      if (length > maximumOutputBytes) { kill(); throw new Error("provider output limit"); }
      chunks.push(chunk);
    }
    const result = new Uint8Array(length);
    let offset = 0;
    for (const chunk of chunks) { result.set(chunk, offset); offset += chunk.length; }
    return new TextDecoder().decode(result);
  }
  try {
    const [stdout, stderr, status] = await Promise.all([
      collect(child.stdout), collect(child.stderr), child.status,
    ]);
    return { success: status.success, stdout, stderr };
  } finally {
    clearTimeout(timer);
    kill();
    await child.status;
  }
}
