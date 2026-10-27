# QA112 — Private API Bearer scheme acceptance (2026-10-27)

**Owner/scope:** independent QA-only branch `chatgpt/cinematic-auth-scheme-qa112-20261027`, frozen QA111 #212 parent `42091d79f5281cf3c7ab4cfaada53ea4f3d56cb0`. Draft, unmerged. Only new QA112 test/handoff files; no edits to the shared studio middleware or other agents' paths.

## Source-level defect and test contract

In `app/studio/server.py`, `private_api()` computes:

```python
supplied = request.headers.get('Authorization','').removeprefix('Bearer ')
if secret:
    if not hmac.compare_digest(secret.encode(), supplied.encode()):
        return JSONResponse(..., status_code=401)
```

Removing the prefix **if present** is not equivalent to requiring it. The configured secret supplied as a raw `Authorization` value passes the comparison even though it is not `Bearer <secret>`. This is **scheme validation** hardening, not an authentication bypass without knowledge of the configured secret, and not evidence of owner-media exposure.

`tests/test_cinematic_bearer_scheme_qa112.py` exercises the actual FastAPI middleware against an intentionally unmapped `/api/` route. The unmapped route returns 404 *only if* the request passed middleware; 401 demonstrates rejection. The test uses a disposable synthetic secret and no project/media data, no model inference, no FFmpeg, no remote transport, and no startup recovery. A valid `Bearer <secret>` is the positive control, while missing/wrong and raw-secret headers must return 401.

**RED test-only commit:** `40e5f81dbab5d96e8fa379951cba818cd22d425d`. CI evidence should be appended only after exact-run verification. Until then, source review is evidence of the logic flaw, not a verified CI reproduction.

## Integration dependency and safe correction

Helper 1 already owns `app/studio/server.py` through #171 (401/403/404 `no-store` cache policy). Do **not** modify that shared file from this branch. The lead/Helper 1 should preserve the explicit `no-store` policy while enforcing the exact `Bearer ` scheme and comparing only the extracted credential using `hmac.compare_digest`. Add tests for missing, wrong, raw, query-only, and valid bearer tokens. Avoid logging credentials, media, private paths, or response bodies.

This QA-only branch cannot prove the combined #171 + #194 + #40 integration SHA. QA99 #200 multi-process startup recovery, QA100 #201 source-audio policy, and QA103 #204 denial cache policy remain separately tracked. Genuine synthetic FFmpeg 4K HTTP acceptance #212 does not imply physical mobile, owner-PC/Windows/WSL2, real inference, or 600-second 4K readiness.

**Release gate:** do not merge or deploy automatically; require a reviewed combined commit and both normal CI and strict private-media FFmpeg acceptance on that exact SHA.
