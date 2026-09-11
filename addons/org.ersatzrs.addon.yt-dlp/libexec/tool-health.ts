import { boundedCommand } from "./item-options.ts";

const stateName = "tool-update-health.json";
export function toolVersion(output: string): string | null {
  const value = output.trim();
  return value.length <= 128 && /^\d{4}\.\d{2}\.\d{2}(?:\.\d+)*$/.test(value) ? value : null;
}

function behind(installed: string, latest: string): boolean {
  const a = installed.split(".").map(Number), b = latest.split(".").map(Number);
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    if ((a[i] ?? 0) !== (b[i] ?? 0)) return (a[i] ?? 0) < (b[i] ?? 0);
  }
  return false;
}

// Only native same-channel release labels prove freshness. Unknown labels,
// requested versions, conflicting output and cross-channel builds prove nothing.
export function latestRelease(output: string, installed: string): string | null {
  const labels = output.split(/\r?\n/).filter((line) => /^(Current|Latest|Requested) version:/.test(line));
  if (labels.length !== 2) return null;
  const parse = (line: string, kind: string) => {
    const match = line.match(new RegExp(`^${kind} version: (stable|nightly|master)@([0-9.]+) from (yt-dlp/yt-dlp(?:-nightly-builds|-master-builds)?)$`));
    if (!match || !toolVersion(match[2])) return null;
    const origins: Record<string, string> = { stable: "yt-dlp/yt-dlp", nightly: "yt-dlp/yt-dlp-nightly-builds", master: "yt-dlp/yt-dlp-master-builds" };
    return origins[match[1]] === match[3] ? { channel: match[1], version: match[2] } : null;
  };
  const current = parse(labels[0], "Current"), latest = parse(labels[1], "Latest");
  return current && latest && current.channel === latest.channel && current.version === installed && behind(installed, latest.version)
    ? latest.version : null;
}

async function identity(executable: string): Promise<string> {
  // The host supplies the effective canonical command path; never store it.
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(executable));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function persistHealth(directory: string | undefined, executable: string, installed: string | null, latest: string | null): Promise<void> {
  if (!directory) return;
  const path = `${directory}/${stateName}`, temporary = `${path}.tmp`;
  try {
    await Deno.mkdir(directory, { recursive: true });
    // Invalidate old evidence first, including when the following atomic write
    // fails. Update/check leases are mutually exclusive in the host.
    try { await Deno.remove(path); } catch (error) {
      if (!(error instanceof Deno.errors.NotFound)) await Deno.writeTextFile(path, "null");
    }
    await Deno.writeTextFile(temporary, JSON.stringify({ schema: 1, identity: await identity(executable), installed, latest }));
    await Deno.rename(temporary, path);
  } catch { /* Health persistence must not change the native update result. */ }
  finally { try { await Deno.remove(temporary); } catch { /* No temporary file. */ } }
}

export async function toolHealth(directory: string | undefined, executable: string, includeContext = false) {
  const ready = { status: "ready", code: "ready", message: "yt-dlp Remote Streams is ready." };
  if (!directory) return ready;
  try {
    const metadata = await Deno.lstat(`${directory}/${stateName}`);
    if (!metadata.isFile || metadata.size > 1024) return ready;
    const file = await Deno.open(`${directory}/${stateName}`, { read: true });
    let state;
    try {
      const bytes = new Uint8Array(1025);
      let size = 0, count;
      while (size < bytes.length && (count = await file.read(bytes.subarray(size))) !== null) size += count;
      if (size > 1024) return ready;
      state = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes.subarray(0, size)));
    } finally { file.close(); }
    if (!state || state.schema !== 1 || state.identity !== await identity(executable) ||
      typeof state.installed !== "string" || typeof state.latest !== "string" ||
      toolVersion(state.installed) !== state.installed || toolVersion(state.latest) !== state.latest ||
      !behind(state.installed, state.latest)) return ready;
    const current = await boundedCommand(executable, ["--no-config", "--no-plugin-dirs", "--no-update", "--version"], 5_000, 4096);
    if (!current.success || toolVersion(current.stdout) !== state.installed) {
      await persistHealth(directory, executable, null, null);
      return ready;
    }
    return {
      status: "warning", code: "tool-update-failed-stale",
      message: `The yt-dlp update failed. Installed version ${state.installed} is behind latest version ${state.latest}. Update yt-dlp manually using its installation method.`,
      ...(includeContext ? { tool_update: { program: "yt-dlp", installed_version: state.installed, latest_version: state.latest } } : {}),
    };
  } catch { return ready; }
}

if (import.meta.main) console.log(JSON.stringify(await toolHealth(
  Deno.env.get("ERSATZRS_ADDON_DATA_DIR"), Deno.env.get("YT_DLP_BIN") ?? "",
  Deno.env.get("ERSATZRS_ADDON_CHECK_CONTEXT_VERSION") === "1",
)));
