# Internet Archive add-on

This add-on imports public video from the [Internet Archive](https://archive.org)
as ErsatzRS add-on lists and plays it through the managed FFmpeg runtime. Use it
to build your own channels from archived television, films and other public
video. Nothing is downloaded permanently: every programme streams from
archive.org when it airs.

## Supported links

Paste one of these links when you add a list in **Settings > Add-ons**:

| Link | Result |
|---|---|
| `https://archive.org/details/<item>` | One entry per video in the item. An item with a single video becomes one entry named after the item. |
| `https://archive.org/details/<item>/<file>` | Only that video. |
| `https://archive.org/details/<collection>` | Every video item in the collection (up to 10,000). |
| `https://archive.org/search?query=<terms>` | Every video item matching the search (up to 10,000). |

ErsatzRS selects this add-on automatically for `archive.org` links.

## What is imported

Title, description, date, run time, subjects, creators, languages and the
item thumbnail are mapped into the shared metadata document. Known Archive
collections set the content kind (for example `feature_films` becomes a movie
and `classic_tv` a television episode); everything else is left on automatic.
Items that are withdrawn or lending-restricted stay visible as unavailable, so
saved local replacements keep playing.

For playback the add-on picks one file per uploaded video, preferring the
Archive's H.264 derivative, and remuxes it without re-encoding: MP4-family files
as MPEG-TS, other containers as Matroska. Seeking uses the Archive's byte-range
support.

## Prerequisites

- **[Deno](https://deno.com/)** on the `PATH` of the account that runs ErsatzRS
  (Linux x64/ARM64, Windows x64 and macOS).
- On Linux ARMv7, where Deno publishes no build, **Node.js 22.18 or newer**
  runs the same sources instead.

The managed FFmpeg runtime is supplied by ErsatzRS. **Check** reports the
add-on as unavailable until the runtime and FFmpeg are found.

## Fair use of the Archive

Requests identify themselves with an `ErsatzRS-InternetArchive/<version>`
User-Agent, as the Archive's
[guidance for automated access](https://archive.org/developers/bots.html) asks.
A list import makes one metadata request per link plus one search page per
5,000 results; playback makes one metadata request per programme start. A
`429 Too Many Requests` answer is reported as `provider-rate-limited`.

Rights differ per item. Much of the Archive is public domain or Creative
Commons, but not everything is. You are responsible for checking that your use
of an item is permitted. Consider [supporting the Archive](https://archive.org/donate),
whose bandwidth every programme uses.

## Limits

Package 0.1.0 imports a list in one pass. Collections close to 10,000 items may
fall back to shortened descriptions to stay within the host's output limits.
Resumable paged import, subtitle tracks from the Archive's `.srt`/`.vtt` files
and the per-item licence in the review editor are planned follow-ups.

## Development

The provider logic is in `libexec/*.mts` and runs unchanged under Deno and
Node.js. Offline tests use recorded fixture documents and never contact
archive.org:

```sh
python3 -m unittest tests.test_internet_archive
```
