import { boundedCommand } from "./item-options.ts";
import { latestRelease, persistHealth, toolVersion as version } from "./tool-health.ts";

type Outcome = "updated" | "already_current" | "manual_update_required" | "failed";
type Diagnostic = "unsupported_installation" | "update_failed" | "version_probe_failed" | "tool_unavailable";
type CommandRunner = typeof boundedCommand;
export type ToolUpdateResult = {
  schema: "tool.update.v1";
  tool_key: "YT_DLP_BIN";
  before_version: string | null;
  after_version: string | null;
  outcome: Outcome;
  diagnostic_code: Diagnostic | null;
};

const baseArguments = ["--no-config", "--no-plugin-dirs"];
const versionArguments = [...baseArguments, "--no-update", "--version"];

function requiresManualUpdate(stderr: string): boolean {
  // These are narrow native updater diagnostics, not arbitrary mentions of
  // package managers or permissions in a network/server error.
  return stderr.split(/\r?\n/).some((line) =>
    /^ERROR: You installed yt-dlp with pip or using the wheel from PyPi; Use that to update$/.test(line) ||
    /^ERROR: You installed yt-dlp from a manual build or with a package manager; Use that to update$/.test(line) ||
    /^ERROR: You cannot update when running from source code; Use git to pull the latest changes$/.test(line) ||
    /^ERROR: Auto-update is not supported for unpackaged executables; Re-download the latest release$/.test(line) ||
    /^ERROR: You are using an unofficial build of yt-dlp; Build the executable again$/.test(line) ||
    /^ERROR: Insufficient permissions to write to .+$/.test(line)
  );
}

export async function updateTool(
  request: unknown,
  executable: string,
  run: CommandRunner = boundedCommand,
  directory?: string,
): Promise<ToolUpdateResult> {
  await persistHealth(directory, executable, null, null);
  let output = "";
  const observe: CommandRunner = async (command, args, timeout, limit) => {
    const result = await run(command, args, timeout, limit);
    if (args.includes("-U")) output = result.stdout;
    return result;
  };
  const result = await nativeUpdate(request, executable, observe);
  const latest = (result.outcome === "failed" || result.outcome === "manual_update_required") &&
      result.before_version && result.after_version === result.before_version
    ? latestRelease(output, result.before_version) : null;
  await persistHealth(directory, executable, latest ? result.after_version : null, latest);
  return result;
}

async function nativeUpdate(
  request: unknown,
  executable: string,
  run: CommandRunner,
): Promise<ToolUpdateResult> {
  const result: ToolUpdateResult = {
    schema: "tool.update.v1", tool_key: "YT_DLP_BIN",
    before_version: null, after_version: null,
    outcome: "failed", diagnostic_code: "update_failed",
  };
  if (!request || typeof request !== "object" || Array.isArray(request) ||
    Object.keys(request).some((key) => !["schema", "tool_key"].includes(key)) ||
    (request as Record<string, unknown>).schema !== result.schema ||
    (request as Record<string, unknown>).tool_key !== result.tool_key) return result;
  if (!executable) return { ...result, diagnostic_code: "tool_unavailable" };
  try {
    const before = await run(executable, versionArguments, 10_000, 4096);
    result.before_version = before.success ? version(before.stdout) : null;
  } catch (error) {
    return { ...result, diagnostic_code: error instanceof Deno.errors.NotFound ? "tool_unavailable" : "version_probe_failed" };
  }
  if (!result.before_version) return { ...result, diagnostic_code: "version_probe_failed" };

  let update: Awaited<ReturnType<CommandRunner>> | null = null;
  try {
    // The configured native executable alone owns the network transfer and
    // replacement. No URL, target channel, installer, or package manager is added.
    update = await run(executable, [...baseArguments, "-U"], 60_000, 16_384);
  } catch { /* Keep raw subprocess diagnostics out of the public result. */ }
  try {
    const after = await run(executable, versionArguments, 10_000, 4096);
    result.after_version = after.success ? version(after.stdout) : null;
  } catch { /* A failed post-update probe remains an explicit failed result. */ }

  if (!result.after_version) return { ...result, diagnostic_code: "version_probe_failed" };
  if (!update?.success) {
    if (update && requiresManualUpdate(update.stderr)) {
      return { ...result, outcome: "manual_update_required", diagnostic_code: "unsupported_installation" };
    }
    return result;
  }
  return {
    ...result, diagnostic_code: null,
    outcome: result.before_version === result.after_version ? "already_current" : "updated",
  };
}

if (import.meta.main) {
  let request: unknown = null;
  try {
    const chunks: Uint8Array[] = [];
    let length = 0;
    for await (const chunk of Deno.stdin.readable) {
      length += chunk.length;
      if (length > 1024) throw new Error("request limit");
      chunks.push(chunk);
    }
    const bytes = new Uint8Array(length);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
    request = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch { /* Invalid requests fail without invoking the configured tool. */ }
  const result = await updateTool(request, Deno.env.get("YT_DLP_BIN") ?? "", boundedCommand, Deno.env.get("ERSATZRS_ADDON_DATA_DIR"));
  console.log(JSON.stringify(result));
}
