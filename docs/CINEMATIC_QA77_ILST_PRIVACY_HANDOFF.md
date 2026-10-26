# QA77 — completed-master ilst metadata privacy handoff

**Status:** draft, unmerged, no deployment. Frozen parent: QA76 #163 `e8d5fdbb0b609e0ca48d44c8699959062e3a0177` (24/24 workflows SUCCESS at QA77 start).

## Reproduced gap

The strict offline completed-master inspector checks immediate `moov/udta/meta` child box types, but accepts `ilst` without validating its children. A disposable genuine FFmpeg H.264 MP4 with an opaque `moov/udta/meta/ilst/priv` item fully decoded; FFprobe reported 48 frames, 24 FPS and 2 seconds, and did not reveal the synthetic canary. A matching SHA was persisted in temporary SQLite. The strict CLI incorrectly returned exit 0.

Test-only SHA: `73e4362fe806c17f685d425e1b3114066ef6ea5e`. GitHub Actions [40275398267](https://github.com/reppiks490/new/actions/runs/40275398267) reproduced **1 expected failure / 1 passing clean control** on Python 3.11 and Python 3.12.

## Narrow proposed correction

`455f348a2cf40568c98442e7d5d494b7b5cadaec` extends only the read-only opt-in offline MP4 inspector. It descends into the immediate `ilst` item headers with the existing bounded scanner and conservatively accepts the known FFmpeg encoder item `©too` while rejecting unknown items. It does not read/report private payloads, modify production assembly, mobile, queue, cached asset router, owner files, or invoke model inference.

**Limitations:** this is not exhaustive MP4 sanitization, does not validate all content inside the allowed `©too` item, and can reject legitimate third-party metadata item types. The delivery contract is deliberately conservative for FFmpeg-produced masters. Full 600-second owner-PC rendering, actual model inference and physical mobile playback remain unverified.

## Ownership and dependencies

- Original master assembly: #8; async assembly/queue: #21; cache/media acceptance: #23.
- Lead integration: #40; QA76 parent: #163; Helper 1 active streaming/disk-concurrency: #164.
- QA77 owns only new QA77 test/workflow/handoff and its narrowly scoped offline inspector change.
- **No merge until exact final-HEAD CI is checked.** No force-push, deployment, paid service, owner media, credential exposure or automation/ICARUS changes.
