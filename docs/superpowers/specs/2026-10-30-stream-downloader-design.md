# Local stream downloader

Status: approved by the user on 30 October 2026; implemented as a standalone development package. Internal-browser installation is blocked; Chrome installation and Upsurge compatibility remain unverified.

## Intent

Save lesson videos from a site the user can already access, so the files can be stored locally and later reviewed for strategy research. The user selected a stream downloader rather than playback recording. The first target is Upsurge Pro, but successful authenticated playback does not prove that extension downloads will work.

## Approaches

- **Stream downloader — selected by the user.** Discover direct media URLs and supported HLS playlists in the active signed-in browser tab. Download the original media without recording playback. Site authentication and delivery constraints can still prevent retrieval.
- **Downloader plus recording fallback — declined.** Tab recording would handle some streams that cannot be downloaded, but takes playback time and changes the output. No recording capability will be included.

## Proposed first version

A standalone Chrome Manifest V3 extension, packaged as source plus an installable unpacked-folder ZIP in `tools/stream-downloader/`. This platform and location are implementation proposals, not previous user choices. It does not modify OpenAlgo trading services.

1. The user signs into the course in Chrome, opens a lesson and plays it briefly.
2. The extension's control page scans that tab for direct video sources and media URLs exposed through resource timing. A browser `blob:` URL is never presented as a downloadable file.
3. A visible stream list identifies the format and quality where available. A refresh action rescans after playback begins. The user may also supply a known media URL.
4. The user selects a stream, grants access to its media host if needed, and starts a download. Requested host access is explained by hostname. No access to all browsing sites is required at installation.
5. Direct MP4/WebM files use Chrome downloads. Supported unencrypted, finite HLS playlists are fetched and assembled in a persistent extension page, with progress, cancellation and bounded memory use. MPEG-TS is saved as `.ts`; supported fragmented MP4 is saved as `.mp4`. The extension does not falsely label concatenated TS data as MP4.
6. Separate audio/video renditions are identified explicitly. If they cannot be saved as a complete playable file in this version, the extension reports that limitation rather than silently downloading silent video as a complete lesson.
7. Chrome saves files under a `Course streams/` subfolder of its configured Downloads directory, using sanitized course/lesson names where discoverable. Copying files into the OpenAlgo research folder remains a separate local file operation.

## Boundaries and failures

- Local operation only: no server, external upload, account creation or analytics.
- Use the browser's normal request credentials where applicable; do not export cookies, passwords or authentication headers into files or logs.
- Session-specific media URLs remain in memory; they are not retained in persistent download reports.
- No DRM/key extraction, encrypted HLS decryption, paywall bypass, recording, or automatic course completion.
- Report unsupported DASH, live playlists, encrypted streams, ambiguous/discontinuous media layouts, separate rendition limitations, expired URLs, denied permissions and failed requests clearly. Never substitute a public teaser for a full lesson.
- Stop on missing segments; do not claim success for a partial media file. Enforce byte/segment limits and allow cancellation.
- Initial operation is one selected lesson at a time. Course-wide unattended crawling and downloading are outside this first version.

## Verification and deliverables

Tests cover playlist parsing, relative URLs, variant selection, encryption/unsupported-layout rejection, byte ranges if supported, safe filenames, segment ordering, cancellation, failures and incomplete download handling. Local HTTP fixtures exercise direct files and unencrypted HLS without credentials. Verify extension manifest and package contents. Browser integration testing and an actual Upsurge download must be reported separately; unit tests cannot establish site compatibility.

Deliver source, tests, ZIP and short installation/use instructions. No claim that Upsurge downloads work until a full lesson file, duration and audio/video tracks are verified. Installing the extension grants browser capabilities and will require the user's installation action.

## References

- Chrome downloads: https://developer.chrome.com/docs/extensions/reference/api/downloads
- Extension network requests: https://developer.chrome.com/docs/extensions/develop/concepts/network-requests
- Optional permissions: https://developer.chrome.com/docs/extensions/reference/api/permissions
