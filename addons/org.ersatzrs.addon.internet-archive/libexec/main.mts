// Operation dispatcher for the Internet Archive add-on.
//
// Every failure ends with one structured JSON line on stderr and a non-zero
// exit status, matching the other official packages.

import { existsSync } from "node:fs";
import process from "node:process";
import { ProviderError } from "./archive.mts";
import { runList } from "./list.mts";
import { runPlay } from "./play.mts";

const env = (key: string): string | undefined => {
  const value = process.env[key];
  return value === undefined || value === "" ? undefined : value;
};

function check(): string {
  const ffmpeg = env("FFMPEG_BIN");
  if (!ffmpeg || !existsSync(ffmpeg)) {
    return JSON.stringify({
      status: "unavailable",
      code: "missing-command",
      message: "The managed FFmpeg runtime is unavailable.",
    });
  }
  return JSON.stringify({ status: "ready", code: "ready", message: "Ready to import and play archive.org video." });
}

function write(output: string): Promise<void> {
  return new Promise((resolve, reject) => {
    process.stdout.write(output, (error) => error ? reject(error) : resolve());
  });
}

async function main(operation: string | undefined): Promise<number> {
  switch (operation) {
    case "check":
      await write(`${check()}\n`);
      return 0;
    case "list":
      await write(await runList(env));
      return 0;
    case "play":
      return await runPlay(env);
    default:
      throw new ProviderError("operation-failed", "Unsupported add-on operation.", 64);
  }
}

try {
  process.exitCode = await main(process.argv[2]);
} catch (error) {
  const failure = error instanceof ProviderError
    ? error
    : new ProviderError("operation-failed", "The Internet Archive operation failed.");
  process.stderr.write(`${JSON.stringify({ code: failure.code, message: failure.message })}\n`);
  process.exitCode = failure.status;
}
