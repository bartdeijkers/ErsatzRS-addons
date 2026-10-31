// The host owns validation/publication. This pure producer uses only supplied guide data.
const WIDTH = 36;
const MAX_PAGES = 1024;
const COLOURS = [
  "black",
  "red",
  "green",
  "yellow",
  "blue",
  "magenta",
  "cyan",
  "white",
];
const THEMES: Record<string, { accent: string; layout: string }> = {
  classic: { accent: "yellow", layout: "standard" },
  night: { accent: "cyan", layout: "compact" },
  contrast: { accent: "white", layout: "standard" },
};
type GuideId = number | bigint;
type Identity = { playout_id: GuideId; first_item_id: GuideId };
type Programme = {
  identity: Identity;
  start: string;
  stop: string;
  title: string;
  custom_title: string | null;
  sub_title: string | null;
  segments: unknown[];
};
type Channel = {
  id: GuideId;
  number: string;
  name: string;
  programmes: Programme[];
  context: {
    current: Identity | null;
    next: Identity | null;
    continuing: Identity | null;
    later_today: Identity[];
    ambiguous: boolean;
  };
};
type Request = {
  schema_version: number;
  generation: string;
  locale: string;
  timezone: string;
  captured_at: string;
  window: { start: string; finish: string };
  channels: Channel[];
};
type Settings = {
  first: number;
  last: number;
  index: number;
  theme: string;
  accent: string;
  layout: string;
  header: string;
  footer: string;
};
type Address = { page: number; subcode: number };
type Row = ReturnType<typeof row>;
type Draft = {
  address: Address;
  title: string;
  lines: string[];
  binding: string;
};
class Rejection extends Error {
  readonly code: string;
  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}
// A minimal standard Node boundary; Deno continues using its permission-scoped APIs.
declare const process: {
  argv: string[];
  stdin: AsyncIterable<Uint8Array>;
  env: Record<string, string | undefined>;
  exit(code: number): never;
};
const onDeno = typeof Deno !== "undefined";

function reject(code: string, message: string): never {
  throw new Rejection(code, message);
}
function integer(
  env: Record<string, string>,
  key: string,
  fallback: number,
): number {
  const value = env[key] ?? String(fallback);
  if (!/^[0-9]{3}$/.test(value)) {
    reject(
      "invalid-page-range",
      "Page settings must be decimal numbers from 100 to 899.",
    );
  }
  const n = Number(value);
  if (n < 100 || n > 899) {
    reject(
      "invalid-page-range",
      "Page settings must be decimal numbers from 100 to 899.",
    );
  }
  return n;
}
export function settings(env: Record<string, string>): Settings {
  const first = integer(env, "PAGE_START", 200),
    last = integer(env, "PAGE_END", 299);
  const index = integer(env, "INDEX_PAGE", 200), theme = env.THEME ?? "classic";
  if (first > last || index < first || index > last) {
    reject(
      "invalid-page-range",
      "The inclusive range must contain the index page.",
    );
  }
  const selected = THEMES[theme];
  if (!selected) reject("invalid-theme", "Select a declared TV-guide theme.");
  const accent = !env.ACCENT || env.ACCENT === "theme"
    ? selected.accent
    : env.ACCENT;
  if (!COLOURS.includes(accent) || accent === "black") {
    reject(
      "invalid-theme-override",
      "The accent must be a supported visible base colour.",
    );
  }
  const layout = !env.LAYOUT || env.LAYOUT === "theme"
    ? selected.layout
    : env.LAYOUT;
  if (!["standard", "compact"].includes(layout)) {
    reject("invalid-layout", "Select a declared TV-guide layout.");
  }
  const header = env.HEADER ?? "TV GUIDE",
    footer = env.FOOTER ?? "Your TV guide";
  for (const value of [header, footer]) {
    if (
      Array.from(value).length > WIDTH ||
      hasControl(value)
    ) {
      reject(
        "invalid-zone-value",
        "Header and footer zones accept at most 36 characters without control characters.",
      );
    }
  }
  return { first, last, index, theme, accent, layout, header, footer };
}
function hasControl(value: string): boolean {
  return Array.from(value).some((character) => {
    const code = character.charCodeAt(0);
    return code < 32 || (code >= 127 && code <= 159);
  });
}
function text(value: string): string {
  if (
    typeof value !== "string" || hasControl(value)
  ) {
    reject(
      "invalid-guide-text",
      "Guide text contains an unsupported control character.",
    );
  }
  return value;
}
// Wrap complete Unicode code points, never truncate titles or transliterate characters.
export function wrap(value: string): string[] {
  const characters = Array.from(text(value));
  if (!characters.length) return [""];
  const result: string[] = [];
  for (let i = 0; i < characters.length; i += WIDTH) {
    result.push(characters.slice(i, i + WIDTH).join(""));
  }
  return result;
}
export function subcode(index: number): number {
  if (!Number.isInteger(index) || index < 0 || index >= 3200) {
    reject("guide-capacity", "The complete guide exceeds subpage capacity.");
  }
  // S2 has three bits and S4 two: skip invalid decimal 0080..0099, etc.
  return index % 10 | Math.floor(index / 10) % 8 << 4 |
    Math.floor(index / 80) % 10 << 8 | Math.floor(index / 800) << 12;
}
function row(number: number, value: string, colour = "white", column = 2) {
  return {
    row: number,
    runs: [{
      column,
      style: {
        foreground: colour,
        background: "black",
        height: "normal",
        boxed: false,
        flash: false,
        conceal: false,
      },
      content: { kind: "text", text: value },
    }],
  };
}
function instant(value: string): Date {
  const d = new Date(value);
  if (!Number.isFinite(d.getTime())) {
    reject(
      "invalid-guide-time",
      "The supplied guide contains an invalid instant.",
    );
  }
  return d;
}
function language(locale: string): string {
  const languages: Record<string, string> = {
    en: "eng",
    nl: "nld",
    de: "deu",
    fr: "fra",
    it: "ita",
    pl: "pol",
    pt: "por",
    es: "spa",
  };
  const selected = languages[locale.split("-")[0].toLowerCase()];
  if (!selected) {
    reject(
      "unsupported-guide-locale",
      "The guide locale has no declared service language.",
    );
  }
  return selected;
}
function validId(value: GuideId): boolean {
  return typeof value === "bigint"
    ? value >= -9223372036854775808n && value <= 9223372036854775807n
    : Number.isSafeInteger(value);
}
function identityKey(identity: Identity): string {
  if (!validId(identity.playout_id) || !validId(identity.first_item_id)) {
    reject(
      "invalid-guide-reference",
      "Guide references require exact signed 64-bit identities.",
    );
  }
  return `${identity.playout_id}:${identity.first_item_id}`;
}
function parseRequest(source: string): Request {
  // Recover the original decimal spelling before JS Number rounding can merge
  // adjacent SQLite/i64 identities. No bigint is serialized into page output.
  return JSON.parse(
    source,
    (_key: string, value: unknown, context?: { source: string }) => {
      if (
        typeof value === "number" && Number.isInteger(value) &&
        !Number.isSafeInteger(value)
      ) {
        if (!context || !/^-?[0-9]+$/.test(context.source)) {
          reject(
            "invalid-guide-request",
            "Exact guide integer parsing is unavailable.",
          );
        }
        const exact = BigInt(context.source);
        if (!validId(exact)) {
          reject(
            "invalid-guide-request",
            "A guide integer exceeds its signed 64-bit range.",
          );
        }
        return exact;
      }
      return value;
    },
  );
}

export function generate(request: Request, config: Settings) {
  if (
    request.schema_version !== 3 || typeof request.generation !== "string" ||
    !request.generation ||
    new TextEncoder().encode(request.generation).length > 1024 ||
    !Array.isArray(request.channels) || request.channels.length > 256
  ) {
    reject(
      "invalid-guide-request",
      "A bounded teletext.pages.v3 request is required.",
    );
  }
  const lang = language(request.locale);
  let date: Intl.DateTimeFormat, clock: Intl.DateTimeFormat;
  try {
    date = new Intl.DateTimeFormat("en-CA", {
      timeZone: request.timezone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    });
    clock = new Intl.DateTimeFormat("en-GB", {
      timeZone: request.timezone,
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
      timeZoneName: "shortOffset",
    });
  } catch {
    reject(
      "invalid-guide-timezone",
      "The supplied guide timezone is unavailable.",
    );
  }
  const firstInstant = instant(request.window.start),
    lastInstant = instant(request.window.finish);
  if (lastInstant <= firstInstant) {
    reject(
      "invalid-guide-window",
      "The guide window must have increasing bounds.",
    );
  }
  instant(request.captured_at);
  const available = Array.from(
    { length: config.last - config.first + 1 },
    (_, i) => config.first + i,
  ).filter((p) => p !== config.index);
  if (request.channels.length > available.length) {
    reject(
      "guide-capacity",
      "The configured range needs an index and one page per guide channel.",
    );
  }
  const firstRow = config.layout === "compact" ? 4 : 5,
    lineCount = 20 - firstRow;
  const drafts: Draft[] = [],
    indexLines = [
      "CHANNELS",
      ...request.channels.flatMap((channel, i) =>
        wrap(`${available[i]} ${channel.number} ${text(channel.name)}`)
      ),
    ];
  if (!request.channels.length) indexLines.push("No guide channels");
  function append(
    page: number,
    title: string,
    lines: string[],
    binding: string,
  ) {
    // Title overflow becomes body content, preserving long channel names.
    const titleLines = wrap(title);
    lines = [...titleLines.slice(1), ...lines];
    const count = Math.max(1, Math.ceil(lines.length / lineCount));
    if (drafts.length + count > MAX_PAGES) {
      reject(
        "guide-capacity",
        "The complete guide exceeds the host page/subpage limit.",
      );
    }
    for (let part = 0; part < count; part++) {
      drafts.push({
        address: { page, subcode: subcode(part) },
        title: titleLines[0],
        lines: lines.slice(part * lineCount, (part + 1) * lineCount),
        binding,
      });
    }
  }
  append(config.index, "TV GUIDE INDEX", indexLines, "guide.index");
  const channelIds = new Set<GuideId>();
  let occurrences = 0;
  for (const [i, channel] of request.channels.entries()) {
    if (!validId(channel.id) || channelIds.has(channel.id)) {
      reject(
        "invalid-guide-channel",
        "Guide channels need unique signed 64-bit identities.",
      );
    }
    channelIds.add(channel.id);
    occurrences += channel.programmes.length;
    if (occurrences > 10000) {
      reject(
        "guide-capacity",
        "The complete guide exceeds the occurrence limit.",
      );
    }
    const lookup = new Map(
      channel.programmes.map(
        (programme) => [identityKey(programme.identity), programme],
      ),
    );
    const later = channel.context.later_today.map(identityKey);
    if (
      lookup.size !== channel.programmes.length || later.length > lookup.size ||
      new Set(later).size !== later.length
    ) {
      reject(
        "invalid-guide-reference",
        "Programme and Later Today identities must be unique within each channel.",
      );
    }
    const lines: string[] = [];
    const role = (name: string, identity: Identity | null) => {
      if (!identity) {
        lines.push(...wrap(`${name}: No listed programme`));
        return;
      }
      const programme = lookup.get(identityKey(identity));
      if (!programme) {
        reject(
          "invalid-guide-reference",
          "A supplied guide context reference is missing.",
        );
      }
      lines.push(
        ...wrap(`${name}: ${programme.custom_title ?? programme.title}`),
      );
    };
    if (channel.context.ambiguous) lines.push("Guide context is ambiguous");
    role("Now", channel.context.current);
    role("Next", channel.context.next);
    role("Continuing", channel.context.continuing);
    lines.push("LATER TODAY");
    for (const identity of channel.context.later_today) role("Later", identity);
    if (!channel.context.later_today.length) {
      lines.push("No further listed programmes");
    }
    lines.push("", "FULL SUPPLIED GUIDE");
    let day = "";
    // The host supplies identities/context, not editorial ordering. Sort a copy.
    for (
      const programme of channel.programmes.toSorted((left, right) =>
        instant(left.start).getTime() - instant(right.start).getTime()
      )
    ) {
      const start = instant(programme.start), stop = instant(programme.stop);
      if (stop <= start) {
        reject(
          "invalid-guide-time",
          "Programme intervals must have increasing bounds.",
        );
      }
      const localDay = date.format(start);
      if (day !== localDay) {
        day = localDay;
        lines.push(...wrap(localDay));
      }
      lines.push(
        ...wrap(
          `${clock.format(start)} ${programme.custom_title ?? programme.title}`,
        ),
      );
      if (programme.sub_title) lines.push(...wrap(programme.sub_title));
    }
    if (!channel.programmes.length) lines.push("No listed programmes");
    append(
      available[i],
      `${channel.number} ${text(channel.name)}`,
      lines,
      `guide.channel-${channel.id}`,
    );
  }
  // Six regions plus two bindings per page; preserve the host aggregate bound.
  if (drafts.length * 8 > 4096) {
    reject(
      "guide-capacity",
      "The complete guide exceeds authoring metadata capacity.",
    );
  }
  const pages = drafts.map((draft, i) => {
    const previous = drafts[(i + drafts.length - 1) % drafts.length].address;
    const next = drafts[(i + 1) % drafts.length].address;
    const index = { page: config.index, subcode: 0 };
    const links = [
      { role: "index", target: index },
      { role: "red", target: previous },
      { role: "green", target: next },
      { role: "yellow", target: { page: draft.address.page, subcode: 0 } },
      { role: "cyan", target: index },
    ];
    const footer: Row = { row: 24, runs: [] };
    for (const [n, link] of links.slice(1).entries()) {
      footer.runs.push(
        row(
          24,
          String(link.target.page),
          ["red", "green", "yellow", "cyan"][n],
          2 + n * 10,
        ).runs[0],
      );
    }
    return {
      address: draft.address,
      kind: "full_page",
      language: lang,
      national_option: 0,
      rows: [
        row(1, config.header, config.accent),
        row(3, draft.title, config.accent),
        ...draft.lines.map((line, n) => row(firstRow + n, line)),
        row(21, " ".repeat(WIDTH)),
        row(22, config.footer, config.accent),
        footer,
      ].filter((r) => r.runs.some((run) => run.content.text.length > 0)),
      navigation: links,
    };
  });
  const authoringPages = drafts.map((draft) => ({
    page: draft.address,
    regions: [
      { id: "header", kind: "zone", row: 1, height: 1 },
      { id: "title", kind: "generated", row: 3, height: 1 },
      { id: "guide", kind: "generated", row: firstRow, height: lineCount },
      { id: "custom", kind: "free", row: 21, height: 1 },
      { id: "footer", kind: "zone", row: 22, height: 1 },
      { id: "navigation", kind: "generated", row: 24, height: 1 },
    ].map((r) => ({ ...r, area: "main", column: 2, width: WIDTH })),
    dynamic_fields: [
      { id: "title", region: "title", binding: draft.binding },
      { id: "guide", region: "guide", binding: draft.binding },
    ],
  }));
  const overrides: unknown[] = [];
  if (config.accent !== THEMES[config.theme].accent) {
    const bits: Record<string, number[]> = {
      red: [15, 0, 0],
      green: [0, 15, 0],
      yellow: [15, 15, 0],
      blue: [0, 0, 15],
      magenta: [15, 0, 15],
      cyan: [0, 15, 15],
      white: [15, 15, 15],
    };
    const [red, green, blue] = bits[config.accent];
    overrides.push({
      key: "accent",
      value: { kind: "colour", red, green, blue },
    });
  }
  if (config.layout !== THEMES[config.theme].layout) {
    overrides.push({
      key: "layout",
      value: { kind: "layout", id: config.layout },
    });
  }
  return {
    schema_version: 3,
    service: {
      schema_version: 2,
      generation: request.generation,
      language: lang,
      initial_page: config.index,
      pages,
      page_enhancements: [],
      magazines: [],
      objects: [],
      drcs: [],
      mots: [],
      // Explicitly declare that every base page uses no optional MOT bank.
      mot_selections: pages.map((page) => ({
        display: page.address,
        mot: null,
      })),
      empty_object_pages: [],
    },
    authoring: {
      schema_version: 1,
      template: { id: "tvguide", revision: "1" },
      theme: { id: config.theme, overrides },
      pages: authoringPages,
    },
  };
}
if (import.meta.main) {
  try {
    if ((onDeno ? Deno.args : process.argv.slice(2))[0] === "check") {
      console.log(
        JSON.stringify({
          status: "ready",
          code: "ready",
          message: "TV-guide teletext producer is available.",
        }),
      );
    } else if ((onDeno ? Deno.args : process.argv.slice(2))[0] === "pages") {
      const chunks: Uint8Array[] = [];
      let bytes = 0;
      for await (
        const chunk of (onDeno ? Deno.stdin.readable : process.stdin)
      ) {
        bytes += chunk.length;
        if (bytes > 4 * 1024 * 1024) {
          reject(
            "guide-request-limit",
            "The complete guide request exceeds 4 MiB.",
          );
        }
        chunks.push(chunk);
      }
      const input = new Uint8Array(bytes);
      let offset = 0;
      for (const chunk of chunks) {
        input.set(chunk, offset);
        offset += chunk.length;
      }
      const request = parseRequest(
        new TextDecoder("utf-8", { fatal: true }).decode(input),
      );
      const env: Record<string, string> = {};
      for (
        const key of [
          "PAGE_START",
          "PAGE_END",
          "INDEX_PAGE",
          "THEME",
          "ACCENT",
          "LAYOUT",
          "HEADER",
          "FOOTER",
        ]
      ) {
        const variable = `ERSATZRS_ADDON_SETTING_${key}`;
        const value = onDeno ? Deno.env.get(variable) : process.env[variable];
        if (value !== undefined) env[key] = value;
      }
      const result = JSON.stringify(generate(request, settings(env)));
      if (new TextEncoder().encode(result).length > 8 * 1024 * 1024) {
        reject(
          "guide-output-limit",
          "The complete guide response exceeds 8 MiB.",
        );
      }
      // Nothing is emitted until the complete contribution succeeds.
      console.log(result);
    } else {reject(
        "unsupported-operation",
        "Supported operations are check and pages.",
      );}
  } catch (error) {
    const known = error instanceof Rejection;
    console.error(
      JSON.stringify({
        code: known ? error.code : "invalid-guide-request",
        message: known
          ? error.message
          : "The supplied guide request is invalid.",
      }),
    );
    if (onDeno) Deno.exit(65);
    else process.exit(65);
  }
}
