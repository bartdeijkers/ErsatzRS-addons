# Changelog

All notable changes are recorded here using Keep a Changelog.

## [Unreleased]

### Fixed

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
