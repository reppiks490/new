# QA103 — explicit no-store on unauthorized 600-second master Range

**Draft, test-first privacy acceptance; no production changes.**

## Specific defect / false-positive

Helper 1's independent review of QA102 #203 found that the unauthorized
response assertion used
`denied.headers.get("cache-control", "no-store") == "no-store"`.
A missing header passes that check. On the frozen QA102 head
`31e107bf33e79c22186ce13482814a5fccd40c5e`,
the studio server's 401 JSON response has no explicit Cache-Control.
QA102's authorized 206 byte checks are valid; its 401 no-store claim is not.

QA103 adds a **separate test** rather than editing QA102's agent-owned
file. It uses the existing QA102 genuine synthetic FFmpeg 600-second master
builder, then exercises the actual FastAPI 401 response for missing bearer,
incorrect bearer and query-string token with HTTP Range. The header lookup
does **not** provide a default. Only explicit `Cache-Control: no-store`
passes. The test also requires 401 and no token disclosure.

## Expected implementation owner / acceptance

This is a privacy/cache-policy issue, **not evidence of a private video
body being served without authorization**. The 401 itself is correct.
Helper 1's separate draft #171 already proposes a production fix for
private denial no-store; avoid duplicate production edits. After the lead
integrates #171 and other dependencies, remove QA103's strict xfail,
verify genuine-media acceptance, then verify the actual combined branch SHA.

A strict xfail, if added after a reproduced RED, is an **unresolved
defect**, not a green privacy feature. A strict XPASS requires removing
the marker and reviewing the newly fixed behavior.

## Scope and boundaries

Frozen parent: QA102 #203 at `31e107bf33e79c22186ce13482814a5fccd40c5e`.
Dependencies: #8 master, #21 async queue, #23 cache/media, #40 integration,
Helper 1 #171 and #194, #199 integration gate, #200 unresolved multi-process
recovery, #201 source audio policy, #202 faststart, #203 HTTP Range.
Dedicated CI uses offline, isolated Docker and only synthetic FFmpeg media.
No owner footage, inference, physical mobile/browser cache, Windows-PC,
4K, deployment, cloud generation or real-money operations are verified.

No merge, force push, credential exposure, ICARUS or ChatGPT automation edits.
