# Changelog

All notable changes to AegisQDA. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased] — planned as 0.1.1

### Security

- Fix [AEGIS-2026-001](docs/advisories/AEGIS-2026-001.md): identifiers that
  cross a line break (for example a name wrapped inside a two-line SRT cue), sit
  in square brackets, or are separated by Unicode line separators could pass the
  privacy release unreviewed. Recognizer packs `aegis-custom-strict-v1` and `-v2`
  are revoked; runs scanned with them stop with a message naming the advisory.

### Added

- `aegisqda audit [run-root]`: read-only check of existing runs against the
  current recognizer pack. It prints no source text.
- Terminal review: add a missed detection by its exact text; every occurrence
  inside a content line is added.
- `SECURITY.md` with the reporting and communication policy, and
  `docs/advisories/`.

### Changed

- Recognizer pack `aegis-custom-strict-v3`. A mention that crosses a line break
  is reviewed once and replaced by one placeholder on its first line, shared
  with the same mention elsewhere in the document; the rest is removed from the
  next line, or becomes `[…]` if that line would otherwise be empty.
- Only the exact placeholder shape `[TYPE_NNN]` is exempt from detection.
- A leading UTF-8 byte-order mark is ignored. SRT cue numbers and timings must
  use ASCII digits. Sources longer than 1,000,000 characters are blocked with a
  clear message. Unicode line separators other than LF/CRLF are rejected.
- Terminal review: end of input or Ctrl-C aborts cleanly with `BLOCKED`; an
  unknown entity type is asked again; a type the policy blocks still aborts.
- Cloud-sync detection covers `~/Library/CloudStorage` (including Google Drive
  for desktop), Nextcloud, ownCloud, pCloud, Seafile, Synology Drive and
  Tresorit, and no longer treats folder names such as `Sandbox` or `inbox` as
  Box.
- `keygen-review` no longer changes the permissions of an existing directory.

### Removed

- Unused helper `digqda_adapter._strings`.

## [0.1.0] — 2026-08-08

First archived release ([Zenodo](https://doi.org/10.5281/zenodo.21854346)).
Affected by [AEGIS-2026-001](docs/advisories/AEGIS-2026-001.md).
