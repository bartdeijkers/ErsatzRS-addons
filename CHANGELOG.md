# Changelog

All notable changes are recorded here using Keep a Changelog.

## [Unreleased]

### Added

- yt-dlp package 0.11.0 declares a permission-scoped native tool update operation.
  The configured executable owns its update through `-U`; bounded results
  distinguish updated, already current, manual update required, and failed
  outcomes without exposing native diagnostic text.
