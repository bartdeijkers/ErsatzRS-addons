# TV-guide teletext

A local, network-free `teletext.pages.v3` producer for ErsatzRS 1.1.x. It requires
Deno 2 and explicit installation/enabling in the host. No NOS data is fetched.
Only the numbered TV-guide index, compact listings, subpages and colour-key
navigation of [NOS pages 200–299](https://nos.nl/teletekst/200) inform this
independent layout; names, branding, news and other NOS sections are excluded.

Create named teletext profiles in ErsatzRS and select them per channel. Defaults
publish an index at 200 and channel guides at 201 onwards. `PAGE_START`,
`PAGE_END` and `INDEX_PAGE` choose an inclusive 100–899 output range and an index
inside it. For example, a second profile can use 400–499 with index 400. The
same installed package serves both profiles without changing global settings.
All guide channels need a page in the selected range, in host-supplied order.
Index and channel pages paginate into valid subcodes, including the S2/S4 masks;
no guide rows or titles are silently dropped to fit. The complete supplied
window and Now/Next/Continuing/Later Today roles are preserved. Programme times
use the supplied IANA timezone and include the UTC offset to distinguish DST
folds. Filler gaps are not invented as named programmes; a missing context is
shown as no listed programme.

`THEME` selects `classic` (yellow, standard layout), `night` (cyan, compact) or
`contrast` (white, standard). `ACCENT` and `LAYOUT` permit explicit overrides;
`theme` retains the theme default. Colour uses the base palette. These are
Level 1/1.5 pages; no optional Level 2.5 banks, objects or client is needed.
Unicode is preserved for the host's repertoire/encoding validation.

`HEADER` and `FOOTER` fill named 36-character single-line zones. Unsupported
control characters and overlong values reject the complete result. The native
TTI/sidecar workflow additionally exposes a blank 36-cell `custom` free region
at row 21. Generated title, guide body and navigation regions remain protected.
V3 metadata records template `tvguide` revision `1`, theme/overrides, exact page
identities and dynamic bindings. Import remains a draft; explicit host publication
is separate. Template changes require an explicit package version update.

Red navigates to the previous page/subpage, green to the next, yellow to the
current channel's first subpage and cyan to the index. Every target belongs to
the generated map. Invalid settings, missing context references, insufficient
range/subpage/record/metadata capacity or oversized input/output fail before any
response is emitted. The host independently validates complete output and owns
collision rejection, preview, atomic publication, stale/last-good policy, actual
streaming and playback safety. A successful producer call is not publication.

Manual invocation accepts a host request on stdin and writes one complete JSON
response on stdout: `./addon.sh pages` (Windows: `addon.bat pages`). Settings
enter only through the existing `ERSATZRS_ADDON_SETTING_<KEY>` environment.
`check` reports runtime readiness. This package uses no network, filesystem,
media, process-spawning or managed-FFmpeg permission inside Deno.
