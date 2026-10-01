# Changelog

All notable changes are recorded here using Keep a Changelog.

## [Unreleased]

### Changed

- yt-dlp 0.11.6 supports the stable ErsatzRS 1.1 host version while retaining
  compatibility with the 0.1 development host used by earlier beta releases.
  Update the add-on before upgrading ErsatzRS; capabilities and entrypoints
  are unchanged.

### Removed

- Retire official Beeld & Geluid support and its active usage documentation.
  The current package tree already contains only yt-dlp; no runtime package,
  operator installation or saved media is deleted by this documentation change.

### Fixed

- yt-dlp 0.11.5 marks YouTube playlist slots with no title, channel or duration
  as unavailable during discovery, while retaining unknown status for generic
  untitled entries.

- yt-dlp 0.11.4 preserves structured Windows import errors by packaging batch
  entrypoints with CRLF line endings on every build platform. The bundle test
  checks the ZIP bytes and exercises its extracted error path on Windows.

- yt-dlp 0.11.3 retains playlist genres and languages, maps channel/uploader to
  studios, and preserves explicit source age limits as `age:<number>` across
  list and detail metadata. These are source age limits, not national ratings.

- yt-dlp 0.11.2 omits unknown durations when discovery returns missing, null,
  empty or whitespace values, while preserving genuine numeric zero. The
  media-list protocol is unchanged.

- yt-dlp 0.11.1 keeps addressable playlist entries with missing titles using a fallback
  display title, preserving their order and unknown availability instead of
  aborting the entire import. Import failures no longer falsely report that the
  provider is unreachable when mapping fails.
- Report Firefox cookie-database permission denials as a locked browser profile
  during yt-dlp access checks, while keeping unrelated permission failures generic.
- Supply checksum-pinned yt-dlp and FFmpeg fixtures for clean Windows/Linux CI
  runners, and keep the large source-check request test within Windows batch
  command-line limits while retaining its greater-than-16-KiB stdin assertion.
- Refresh the pinned host validator for manifest v6 so CI validates the current
  package's permission-reviewed tool-update contract.

### Added

- Warn when a failed native yt-dlp update confirms that the installed release
  is behind the latest release on its channel. Readiness uses bounded local
  evidence and clears the warning after a successful update or manual repair;
  unknown latest versions do not warn.
- yt-dlp package 0.11.0 declares a permission-scoped native tool update operation.
  The configured executable owns its update through `-U`; bounded results
  distinguish updated, already current, manual update required, and failed
  outcomes without exposing native diagnostic text.
