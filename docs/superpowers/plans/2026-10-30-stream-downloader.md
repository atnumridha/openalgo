# Stream Downloader Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task. Steps use checkbox syntax for tracking.

**Goal:** Deliver the approved local Chrome stream downloader and assess internal-browser installation.

**Architecture:** Dependency-free Manifest V3 extension with an action that opens a persistent control tab. An isolated-tab scanner discovers visible video and resource-timing candidates. Pure parser and bounded transfer modules handle finite unencrypted HLS; browser downloads handle direct files.

**Tech Stack:** Chrome extension APIs, browser Fetch/Blob, plain HTML/CSS/JavaScript modules, Node's built-in test runner.

**Spec:** `docs/superpowers/specs/2026-10-30-stream-downloader-design.md`

## Global Constraints

- Local operation only; no recording, credentials export, remote scripts, analytics or trading-service changes.
- One selected lesson at a time. Reject encrypted/live/DASH/unsupported layouts and missing segments.
- Optional per-origin HTTPS access; never persist signed URLs.
- Package source and instructions under `tools/stream-downloader/`.
- Internal browser installation may be blocked; never bypass browser policy.

## Review Focus

- Resource discovery must ignore blob URLs and avoid leaking signed URLs to reports.
- Master playlists with separate audio must not yield a falsely complete silent file.
- Failed, cancelled or oversized transfers must never become successful downloads.
- Redirects and HLS relative paths must retain correct URL resolution without broadening origin access silently.
- Browser download acceptance is not disk completion; keep completion states distinct.

## Task 1: Parsing and transfer core

Files: `tools/stream-downloader/extension/core.mjs`, `transfer.mjs`, `tests/core.test.mjs`, `tests/transfer.test.mjs`.

Interfaces: `parsePlaylist(text, baseUrl)` returns variants or ordered segment descriptors; `safeFilename(title, ext)`; `mediaCandidates(resources)`; `assemblePlaylist(playlist, options)` returns a complete bounded Blob only after every segment succeeds.

- [x] Write failing Node tests for relative variants/segments, encrypted/live/separate audio rejection, initialization segments, malformed layouts, safe names and blob filtering.
- [x] Verify failures, then implement the parser and discovery helpers.
- [x] Write failing HTTP-fixture transfer tests for byte ordering, HTTP errors, permission failures, cancellation, empty segments and byte caps.
- [x] Implement sequential bounded fetch with cancellation, progress and complete-file assembly; run the whole package test command.

## Task 2: Extension integration

Files: `extension/manifest.json`, `background.mjs`, `scan.mjs`, `panel.html`, `panel.css`, `panel.mjs`, `tests/browser-contract.test.mjs`.

Interfaces: action opens `panel.html?tab=<id>`; scanner returns source title and candidate URLs only from the selected tab; panel requests permission per media origin and fetches under the browser session. Download lifecycle follows `chrome.downloads.onChanged`.

- [x] Write failing tests for scan filtering and download lifecycle normalization.
- [x] Add MV3 configuration, isolated scanner, control page, explicit origin access, selectable variants, bounded transfers and cancel behavior.
- [x] Check manifest/resources and syntax; run full standalone suite. Render the control page using local fixture state when possible; disclose unavailable extension integration tests.

## Task 3: Review, package and delivery

Files: `README.md`, `package.json`, `scripts/package.py`, `artifacts/stream-downloader.zip`, `VERIFICATION.txt`.

- [x] Independently review complete implementation against spec, including failure modes above; correct important findings with failing regression tests first.
- [x] Run `npm test` for the entire standalone package, syntax checks and deterministic ZIP/resource inspection.
- [x] Save verification results, installation instructions and a ZIP with runtime files only. State clearly that internal installation was blocked and Upsurge compatibility has not been proven.

## Execution ledger

- User approved the design and requested implementation/installation. Proceed inline without another approval round.
- Ruling: use a standalone new directory in the existing feature checkout, with no changes to existing application code or Git history. A worktree/branch operation is unnecessary for this additive deliverable; unrelated untracked research is preserved.
- Internal extension-manager navigation was denied by the browser URL policy (HTTP/HTTPS only). Do not attempt indirect installation or a workaround.

- Task 1: complete — parser and bounded transfer core verified; generated TS/MP4 fixtures verified.
- Task 2: complete — runtime extension/UI packaged; Chrome runtime remains explicitly unverified.
- Task 3: complete — independent review findings corrected RED→GREEN; full package suite 51/51; package and syntax checks pass.
- Ruling: direct files are first fetched with byte limits and basic container checks, then saved using Chrome downloads via a Blob URL. This avoids claiming success for an HTML sign-in response, at the cost of buffering the complete direct file (maximum 512 MiB).
- Ruling: require structural audio/video metadata on HLS parts and reject unsupported layouts; this can reject valid codecs or layouts outside this implementation, but prevents silently saving a known video-only rendition as a complete lesson.
- Internal browser installation: not completed — blocked by URL policy; no workaround attempted.
