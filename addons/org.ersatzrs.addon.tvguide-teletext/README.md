# TV-guide teletext

A local, network-free `teletext.pages.v3` producer for ErsatzRS 1.1.x with the
accepted Phase 9A v3 host contract. Explicit installation/enabling is required.
Linux x64, Linux ARM64 and Windows use Deno 2. Linux ARMv7 uses Node.js 22.18 or
newer because Deno has no official ARMv7 binary. Debian-family ARMv7 systems
also need the standard `libatomic1` system library for the official Node binary.
No runtime is installed automatically. No NOS data is fetched.
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
response on stdout: `./addon.sh pages` (Windows: `addon.bat pages`; ARMv7:
`./addon-node.sh pages`). Both runtimes execute the same `libexec/pages.mts`
producer; there is no separate page generator. Settings
enter only through the existing `ERSATZRS_ADDON_SETTING_<KEY>` environment.
`check` reports runtime readiness. The producer accesses only stdin/stdout and
the declared settings; it performs no network, media, filesystem or subprocess
operation. Deno additionally receives its existing restricted environment grant.
Node is an explicitly declared external command within the host's existing
permission-reviewed addon boundary; it is not represented as a Deno sandbox.

The manifest chooses the appropriate entrypoint per RID. The same source was
qualified with Deno 2.9.5/2.9.8 and Node 22.21.1/22.23.4. ARM software checks use
emulation; native ARM remains deferred, not verified. Version 0.1.1 changes the
runtime boundary, not template revision 1 or the page/metadata contract.
