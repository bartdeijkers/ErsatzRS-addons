// Offline test harness: runs the add-on's own functions against recorded
// fixture documents. No network access is granted to this process.
import process from "node:process";
import { readFileSync } from "node:fs";
import { parseDate, parseRuntime, parseSource, programmes } from "../../../addons/org.ersatzrs.addon.internet-archive/libexec/archive.mts";
import { listing, mediaListRecords, ndjson, remoteStreamRecords } from "../../../addons/org.ersatzrs.addon.internet-archive/libexec/list.mts";
import { ffmpegArguments, planPlayback, seekArgument } from "../../../addons/org.ersatzrs.addon.internet-archive/libexec/play.mts";

const request = JSON.parse(readFileSync(0, "utf8"));
const responses: [string, unknown][] = request.responses ?? [];
const fetched: string[] = [];
const fetcher = async (url: string) => {
  fetched.push(url);
  // Longest matching prefix wins, so a cursor page can be told apart.
  const match = responses.filter(([prefix]) => url.startsWith(prefix))
    .sort((left, right) => right[0].length - left[0].length)[0];
  if (!match) throw new Error(`unexpected request ${url}`);
  return match[1] as Record<string, unknown>;
};

async function run(): Promise<unknown> {
  switch (request.op) {
    case "source":
      try {
        return parseSource(request.url);
      } catch (error) {
        return { error: (error as { code?: string }).code };
      }
    case "runtime":
      return request.values.map(parseRuntime);
    case "date":
      return request.values.map(parseDate);
    case "programmes":
      return programmes(request.files);
    case "media-list": {
      const list = await listing(request.url, fetcher);
      return { lines: ndjson(mediaListRecords(list)), fetched };
    }
    case "remote-stream": {
      const list = await listing(request.url, fetcher);
      return { lines: ndjson(remoteStreamRecords(list, request.compact ?? false)), fetched };
    }
    case "play": {
      try {
        const plan = await planPlayback(request.url, fetcher);
        return { plan, args: ffmpegArguments(plan, seekArgument(request.seek)) };
      } catch (error) {
        return { error: (error as { code?: string }).code };
      }
    }
    case "seek":
      return request.values.map((value: string) => {
        try {
          return seekArgument(value) ?? null;
        } catch {
          return "invalid";
        }
      });
  }
  throw new Error("unknown op");
}

process.stdout.write(JSON.stringify(await run()));
