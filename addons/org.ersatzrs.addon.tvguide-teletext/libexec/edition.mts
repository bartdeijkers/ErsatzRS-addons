// A profile owns its artwork, field placement, catalogue and on-screen copy.
import type { Programme, Request } from "./pages.mts";

const colours = ["red", "green", "yellow", "blue", "magenta", "cyan", "white"];
type Art = [number, number, string, string | number[]];
type Slot = [number, number, number, number, string, string];
type Card = { art: Art[]; fields: Slot[] };
type Layout = {
  version: number;
  count: number;
  detail: number;
  limit: number;
  index: Card;
  synopsis: Card;
};
type Catalogue = {
  series: string;
  seasons: Record<string, (string | null)[]>;
};
type Profile = {
  edition: string;
  catalogue: string;
  pageMap: { page: number; index_entries?: { page: number }[] }[];
  first: number;
  last: number;
  index: number;
};
type Fields = Record<string, string>;
type Address = { page: number; subcode: number };

function requireValue(condition: unknown): asserts condition {
  if (!condition) throw new Error("Invalid episode edition");
}
function integer(n: number, min: number, max: number) {
  return Number.isInteger(n) && n >= min && n <= max;
}
function safeText(value: unknown): value is string {
  return typeof value === "string" &&
    !/[\u0000-\u001f\u007f-\u009f]/u.test(value);
}
function style(foreground: string) {
  requireValue(colours.includes(foreground));
  return {
    foreground,
    background: "black",
    height: "normal",
    boxed: false,
    flash: false,
    conceal: false,
  };
}
function wrap(value: string, width: number): string[] {
  const result: string[] = [];
  let line = "";
  for (const word of value.split(/\s+/u).filter(Boolean)) {
    if (line && Array.from(line + " " + word).length > width) {
      result.push(line);
      line = "";
    }
    const letters = Array.from(word);
    while (letters.length > width) {
      result.push(letters.splice(0, width).join(""));
    }
    if (letters.length) line += (line ? " " : "") + letters.join("");
  }
  if (line) result.push(line);
  return result;
}
function makeCard(card: Card, fields: Fields) {
  requireValue(Array.isArray(card.art) && Array.isArray(card.fields));
  const fieldRows = card.fields.map(([y, x, w, h, colour, pattern]) => {
    requireValue(
      integer(x, 0, 39) && integer(y, 1, 24) && integer(w, 1, 40 - x) &&
        integer(h, 1, 25 - y) && safeText(pattern),
    );
    const value = pattern.replace(/\{([a-z0-9_.]+)\}/g, (_, key: string) => {
      requireValue(Object.hasOwn(fields, key));
      return fields[key];
    }).trim();
    return { x, y, h, colour, lines: wrap(value, w) };
  });
  const parts = Math.max(
    1,
    ...fieldRows.map((f) => Math.ceil(f.lines.length / f.h)),
  );
  requireValue(parts <= 10);
  return Array.from({ length: parts }, (_, part) => {
    const art = card.art.slice();
    for (const f of fieldRows) {
      const start = f.lines.length <= f.h ? 0 : part * f.h;
      f.lines.slice(start, start + f.h).forEach((line, i) =>
        art.push([f.y + i, f.x, f.colour, line])
      );
    }
    const runs = art.map(([y, x, colour, value]) => {
      requireValue(integer(y, 1, 24) && integer(x, 0, 39));
      const mosaic = Array.isArray(value);
      requireValue(
        mosaic ? value.every((c) => integer(c, 0, 63)) : safeText(value),
      );
      const width = Array.from(value as ArrayLike<unknown>).length;
      requireValue(width > 0 && width <= 40 - x);
      const content = mosaic
        ? { kind: "mosaics", cells: value, separated: false }
        : { kind: "text", text: value };
      return { y, width, run: { column: x, style: style(colour), content } };
    }).sort((a, b) => a.y - b.y || a.run.column - b.run.column);
    for (let i = 1; i < runs.length; i++) {
      const a = runs[i - 1], b = runs[i];
      requireValue(a.y !== b.y || a.run.column + a.width <= b.run.column);
    }
    const numbers = [...new Set(runs.map((r) => r.y))];
    return numbers.map((row) => ({
      row,
      runs: runs.filter((r) => r.y === row).map((r) => r.run),
    }));
  });
}

export function episodeEdition(
  request: Request,
  config: Profile,
  language: string,
) {
  const layout: Layout = JSON.parse(config.edition);
  const catalogue: Catalogue = JSON.parse(
    config.catalogue || '{"series":"","seasons":{}}',
  );
  requireValue(
    layout.version === 1 && request.channels.length === 1 &&
      integer(layout.count, 1, 30),
  );
  requireValue(
    safeText(catalogue.series) && catalogue.seasons &&
      typeof catalogue.seasons === "object",
  );
  const { index, first, last } = config, { count, detail, limit } = layout;
  requireValue(
    integer(limit, count, 99) && integer(detail, first, last - limit + 1) &&
      !(index >= detail && index < detail + limit),
  );
  // Reserve the whole rolling detail range, including currently empty slots.
  for (const entry of config.pageMap) {
    for (
      const page of [
        entry.page,
        ...(entry.index_entries ?? []).map((e) => e.page),
      ]
    ) {
      requireValue(page < detail || page >= detail + limit);
    }
  }
  const channel = request.channels[0];
  const captured = Date.parse(request.captured_at);
  requireValue(Number.isFinite(captured));
  const stamp = new Intl.DateTimeFormat("en-GB", {
    timeZone: request.timezone,
    day: "2-digit",
    month: "2-digit",
  });
  const clock = new Intl.DateTimeFormat("en-GB", {
    timeZone: request.timezone,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  const programmes = channel.programmes.filter((p) =>
    Date.parse(p.stop) > captured
  )
    .sort((a, b) => Date.parse(a.start) - Date.parse(b.start)).slice(0, limit);
  const numbers = new Map<string, string>();
  for (const [season, titles] of Object.entries(catalogue.seasons)) {
    requireValue(/^\d{1,3}$/.test(season) && Array.isArray(titles));
    titles.forEach((title, i) => {
      if (title === null) return;
      requireValue(safeText(title) && title.length > 0);
      // A repeated title cannot identify one episode from the v3 guide.
      const code = "S" + season.padStart(2, "0") + "E" +
        String(i + 1).padStart(2, "0");
      numbers.set(title, numbers.has(title) ? "" : code);
    });
  }
  function values(p: Programme | undefined): Fields {
    const title = p?.sub_title || p?.custom_title || p?.title || "";
    const code = p?.title === catalogue.series ? numbers.get(title) ?? "" : "";
    return {
      title,
      code,
      label: code ? code + " : " + title : title,
      synopsis: p?.description || "",
      minutes: p
        ? String(Math.round((Date.parse(p.stop) - Date.parse(p.start)) / 60000))
        : "",
      date: p ? stamp.format(new Date(p.start)) : "",
      time: p ? clock.format(new Date(p.start)) : "",
      stop: p ? clock.format(new Date(p.stop)) : "",
    };
  }
  const listings = [];
  for (let start = 0; start < Math.max(1, programmes.length); start += count) {
    const fields: Fields = { index: String(index) };
    for (let i = 0; i < count; i++) {
      const p = programmes[start + i];
      const data = values(p);
      data.page = p ? String(detail + start + i) : "";
      for (const [key, value] of Object.entries(data)) {
        fields["item" + i + "." + key] = value;
      }
    }
    listings.push(...makeCard(layout.index, fields));
  }
  function numberPart(i: number) {
    requireValue(i < 800);
    return i % 10 | (Math.floor(i / 10) % 8) << 4 | Math.floor(i / 80) << 8;
  }
  const rendered = listings.map((rows, i) => ({
    address: { page: index, subcode: numberPart(i) },
    rows,
  }));
  programmes.forEach((p, i) => {
    const fields = {
      ...values(p),
      index: String(index),
      page: String(detail + i),
    };
    const parts = makeCard(layout.synopsis, fields);
    parts.forEach((rows, n) =>
      rendered.push({
        address: { page: detail + i, subcode: numberPart(n) },
        rows,
      })
    );
  });
  const addr = (page: number): Address => ({ page, subcode: 0 });
  const pages = rendered.map(({ address, rows }, i) => ({
    address,
    rows,
    kind: "full_page",
    language,
    national_option: 0,
    navigation: [
      { role: "index", target: addr(index) },
      {
        role: "red",
        target: rendered[(i + rendered.length - 1) % rendered.length].address,
      },
      { role: "green", target: rendered[(i + 1) % rendered.length].address },
      { role: "yellow", target: addr(programmes.length ? detail : index) },
      { role: "cyan", target: addr(index) },
    ],
  }));
  return {
    schema_version: 3,
    service: {
      schema_version: 2,
      generation: request.generation,
      language,
      initial_page: index,
      pages,
      page_enhancements: [],
      magazines: [],
      objects: [],
      drcs: [],
      mots: [],
      empty_object_pages: [],
      mot_selections: pages.map((p) => ({ display: p.address, mot: null })),
    },
    authoring: {
      schema_version: 1,
      template: { id: "episode-guide", revision: "1" },
      theme: { id: "profile", overrides: [] },
      pages: pages.map((p) => ({
        page: p.address,
        regions: [{
          id: "body",
          kind: "generated",
          area: "main",
          row: 1,
          column: 0,
          width: 40,
          height: 24,
        }],
        dynamic_fields: [{
          id: "programme",
          region: "body",
          binding: "guide.channel-" + channel.id,
        }],
      })),
    },
  };
}
