<!-- Intended repo path: instructions/phase-03c-local-dashboard.md -->
# Instruction Document 3c — Local Live Dashboard (runs on the developer's machine, uses their own AWS credentials)
## Cedar Sentinel — First Commit (Bharat Builds Tour)

**To:** Antigravity coding agent
**From:** Project owner
**Prerequisite:** `instructions/phase-03-dashboard-interface.md` (the Stitch-design rebuild) is **merged to `main`**.
Check first: `dashboard/index.html` and `dashboard/runs/index.json` must exist on `main`. If they do not, **stop
and tell the project owner** — do not build on the old dashboard.
**Branch:** `phase-3c-local-dashboard` — create it off `main`.
**Tag:** none. **Response goes to:** `responses/phase-03c-local-dashboard-response.md` (write it; do **not** commit it).
**Standing rules:** `docs/git-workflow-guardrails.md` still applies (if not at that path, try
`instructions/git-workflow-guardrails.md`) — commit and push to your branch, open a PR against `main`, do **not**
merge, do **not** tag. Wait for review.

---

## 0. Objective

Make the dashboard usable by **any developer, on their own machine, with their own AWS credentials**, with no
hosted backend:

```powershell
python cli/cedar_sentinel.py dashboard              # starts a local server and opens the browser
python cli/cedar_sentinel.py dashboard --run <request_id>
```

The server reads that developer's **own** results table using their **own** AWS credential chain (env vars,
`--profile`, SSO, etc.), so each developer only ever sees what their credentials are allowed to read in their own
account. No login system is needed and nothing is deployed.

**The deployed static dashboard on Amplify must keep working unchanged.** It is the project's public Ship It URL
and replays recorded runs. Local live mode is **additive**: the same `index.html` detects at load time whether a
local server is present and falls back to today's recorded mode if not.

### In scope
- A `dashboard` subcommand in `cli/cedar_sentinel.py` backed by a new module `cli/dashboard_server.py`
  (Python standard library `http.server` + the existing `boto3`; **no new dependencies**).
- A small read-only JSON API (Section 2) and static-file serving of `dashboard/`.
- Front-end mode detection: live mode vs recorded mode (Section 3).
- Shared normalization/sanitization code (Section 4), documentation, tests.

### Explicitly out of scope — do not build
- No changes to `lambda/`, `infra/`, or any AWS resource. No API Gateway, Cognito, Amplify config changes.
- No write path of any kind: no `PutItem`/`UpdateItem`/`PutRolePolicy`, no approve/apply from the dashboard.
  Approval stays CLI-only.
- No hosting, no remote/LAN access, no `--host` option, no telemetry, no new third-party packages.
- No changes to how `analyze` / `--apply` behave (Section 6 allows exactly one added hint line).

---

## 1. Server behavior (`cli/dashboard_server.py`)

1. **Bind to `127.0.0.1` only.** There is no `--host` flag. Default port `8765`; `--port` overrides; if the port is
   busy, fail with a clear message (do not silently pick another).
2. **Credentials:** use boto3's default credential chain. Support `--profile <name>` and `--region <region>`
   (defaults: `AWS_PROFILE` / `AWS_REGION` env, then the `.env` values the CLI already uses). Table name from
   `--table`, else `RESULTS_TABLE_NAME` (same source the CLI already uses for polling). Credentials are **never**
   sent to the browser, never logged, never written to disk.
3. **Read-only:** only `GET` and `HEAD` are handled; every other method returns `405`. The AWS calls made are
   limited to `dynamodb:Scan`, `dynamodb:GetItem` on the results table and `sts:GetCallerIdentity`. Nothing
   else.
4. **Request validation (defends against DNS-rebinding and hostile web pages):**
   - Reject any request whose `Host` header is not exactly `127.0.0.1:<port>` or `localhost:<port>` (`403`).
   - If an `Origin` header is present, it must equal `http://127.0.0.1:<port>` or `http://localhost:<port>`
     (`403` otherwise).
   - Send **no** CORS headers.
5. **Response headers:** API responses `Cache-Control: no-store`, `Content-Type: application/json`,
   `X-Content-Type-Options: nosniff`. Static responses also send `X-Content-Type-Options: nosniff`.
6. **Static files:** serve only files under `dashboard/`. Resolve paths and reject traversal (`..`, absolute
   paths, symlinks leaving the folder, dotfiles); no directory listings. `runs/*.json` continues to be served
   as-is (that is the recorded mode's data).
7. **Startup:** call `sts:GetCallerIdentity`; print `Connected as <user or role name> · region <region> · table
   <table>` (account ID masked unless `--show-real-ids`). If credentials are missing/expired or the table is not
   readable, print a plain, actionable error and exit non-zero (mention `aws sts get-caller-identity` and the
   minimal IAM policy in Section 7). Then print the URL and open the browser (`webbrowser.open`) unless
   `--no-open`. With `--run <request_id>`, open `http://127.0.0.1:<port>/?run=<request_id>`.
8. **Quiet logging:** log method, path and status only. Never log item bodies, ARNs, or credentials.
9. Ctrl-C shuts down cleanly.
10. **`--offline-dir <dir>` (for tests and development):** instead of AWS, serve the same API from run JSON files
    in a directory (use `dashboard/runs`). No AWS calls are made in this mode, and startup prints
    `OFFLINE MODE — reading files from <dir>`.

---

## 2. API (all `GET`, JSON)

| Endpoint | Response |
|---|---|
| `/api/health` | `{"mode":"live","source":"aws"\|"offline","region":"...","table":"...","identity":"<masked name>","sanitized":true}` |
| `/api/runs?limit=50` | `{"runs":[{"request_id","role_arn","role_name","status","completed_at","model_used"}, ...]}` newest first |
| `/api/runs/<request_id>` | the full item, **normalized** to exactly the same shape as the files in `dashboard/runs/*.json` (Section 4). `404` if absent, `400` if the ID is not a UUID |

Implementation notes:
- The results table is keyed only by `request_id`, so listing requires a `Scan`. This is acceptable at demo
  scale (a few items; items expire after 72 hours). Use a projection expression (`status` is a reserved word —
  use `ExpressionAttributeNames`), follow pagination for at most 5 pages, sort newest-first, return at most
  `limit` (cap 200). **Inspect real items** to find the sortable timestamp field (`completed_at`; items still in
  `PROCESSING` may lack it — list those first). Note in `docs/limitations-and-mitigations.md` that production
  would add a GSI (role → time) instead of a Scan.
- Unknown paths under `/api/` return `404` JSON; never fall through to `index.html`.
- Validate `request_id` against a strict UUID regex before it reaches DynamoDB.
- **Sanitization is ON by default** (same rules as `scripts/export_run.py`: account IDs → `<ACCOUNT_ID>`, policy
  store / policy IDs, log-group names, drop `ttl`). `--show-real-ids` turns it off and prints a one-line warning
  at startup ("real ARNs and account IDs will be visible — do not screen-record"). The default is safe for
  screen recording.

---

## 3. Front-end: mode detection (`dashboard/index.html`)

1. On load, request `/api/health` (same origin, ~1.5 s timeout). It is **live mode** only if the response is
   HTTP 200, `Content-Type` is `application/json`, **and** the body has `"mode":"live"`. Anything else — network
   error, timeout, 404, or an HTML page (Amplify may rewrite unknown paths to `index.html`) — means **recorded
   mode**, exactly as built in the previous document (manifest + `runs/*.json`, one fetch per file, no polling).
2. **Live mode:**
   - Run selector is populated from `/api/runs`; each entry shows `role_name`, status, time. Add a small text
     filter over that list (client-side).
   - Selecting a run fetches `/api/runs/<id>` once (cached per session). `?run=<id>` deep-links.
   - A `LIVE · local` badge near the header showing region and masked identity from `/api/health`. The
     notices row reads: `live mode · read from your AWS account through a local server · showing recorded stage
     timings of the selected run`.
   - A **Refresh** button re-fetches the list on click (user-initiated; not a timer).
   - **Bounded polling only for an in-flight run:** if the selected run's status is `PROCESSING`, poll
     `/api/runs/<id>` every 2 s for at most 60 s (matching the CLI), show "run in progress…", and when the status
     leaves `PROCESSING` play the normal replay. No other polling exists anywhere. Use `setTimeout` chains
     that stop on terminal status, tab hidden, or timeout; document this exception where the old "no polling"
     rule is stated.
   - Everything else (HUD, DAG, inspector, tabs, diff, all status states, reduced-motion, `?autoplay=0`) behaves
     identically to recorded mode because live data is normalized to the same shape.
3. **Recorded mode must be regression-free:** opened via plain `python -m http.server` in `dashboard/`, or on
   Amplify, the page behaves exactly as before with no console errors, and shows no live-mode UI.
4. **XSS safety (required — live data includes model-generated text and role names):** render every value from
   the API with `textContent` (or an escaping helper); never `innerHTML`/`insertAdjacentHTML` with data. Add a test
   item whose `rationale`, `role_arn` and an action name contain `<img src=x onerror=alert(1)>` and `"><script>`
   and show it renders as inert text.
5. Keep the wording rules from the previous document (no "Zero Workload Lockouts", "Formal…", "sealed", etc.).

---

## 4. Shared code

- Move the normalization (JSON-encoded string parsing, count coercion, field defaults) and sanitization used by
  `scripts/export_run.py` into one shared module (e.g. `cli/run_data.py`) imported by **both** the export script
  and the server. `scripts/export_run.py` behavior and its existing tests must be unchanged; re-run them and
  paste the output.
- A run served by `/api/runs/<id>` and the same run exported to `dashboard/runs/<name>.json` must be
  byte-for-byte equivalent after normalization/sanitization (add a test asserting this on a fixture).

---

## 5. Documentation

- `README.md`: a **"Local dashboard"** section — the three commands (`dashboard`, `--run`, `--profile`), what
  it needs (AWS credentials that can read the results table), that it never leaves `127.0.0.1`, and the default
  sanitization.
- `docs/architecture.md`: log the local server as a component; note the Amplify site remains the public
  recorded-run view; note the Scan-based listing and the 72-hour TTL.
- `docs/limitations-and-mitigations.md`: add rows — local single-user access model (access = whatever the user's
  IAM credentials allow; no multi-user login or sharing); Scan-based listing; no live per-stage progress because
  Lambda writes stage timings in one write at completion (bounded polling shows `PROCESSING` → done only);
  hosted/authenticated multi-user dashboard is future work.
- `docs/ai-tool-disclosure.md` updated; `docs/attribution.md` unchanged (no new assets or packages).

---

## 6. CLI change (minimal)

- Add the `dashboard` subcommand only. **Do not change** `analyze`, `check-aws`, `--apply` logic or exit codes.
- One allowed addition: after a completed `analyze` run prints its result, print a single extra line
  `View this run: python cli/cedar_sentinel.py dashboard --run <request_id>`. It must not affect stdout parsing
  elsewhere, exit codes, or the refused/`BLOCKED`/`CEDAR_INVALID` paths' existing text. Run the existing CLI test
  suites and paste the output to prove no regression.

---

## 7. Minimal IAM policy for a dashboard reader (document in the README)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": ["dynamodb:GetItem", "dynamodb:Scan"],
      "Resource": "arn:aws:dynamodb:<REGION>:<ACCOUNT_ID>:table/cedar-sentinel-results" },
    { "Effect": "Allow", "Action": "sts:GetCallerIdentity", "Resource": "*" }
  ]
}
```

---

## 8. Verification & evidence (verbatim only)

**Evidence rule:** paste only raw output you actually produced by running the stated command. Do not edit,
reconstruct, retype or reuse earlier outputs. If you cannot do something, say so plainly.

Required:
1. Unit tests (paste full output) proving: server binds only `127.0.0.1`; a request with `Host: evil.example` gets
   403; a bad `Origin` gets 403; `POST`/`PUT`/`DELETE` get 405; path traversal (`/../cli/cedar_sentinel.py`,
   `/%2e%2e/…`) and dotfiles get 404/403; `/api/runs/<non-uuid>` gets 400; unknown `/api/*` gets JSON 404; no
   response body or header contains credentials; sanitization is on by default and `--show-real-ids` disables it;
   API output equals the exported-file shape (Section 4).
2. An `--offline-dir dashboard/runs` session: start the server, `curl.exe -s http://127.0.0.1:8765/api/health`
   and `/api/runs`, and show the JSON (paste raw).
3. A **real** session against the developer's AWS account: start the server without `--offline-dir`, paste the
   startup lines (masked) and `curl.exe -s http://127.0.0.1:8765/api/runs` output (redact IDs), and show one run
   loading in the browser. If you cannot reach AWS from your environment, say so — the project owner will verify.
4. Regression: recorded mode still works under `python -m http.server` (paste the console/Network summary or
   state that you could not check it), and the mode-detection code falls back correctly when `/api/health`
   returns an HTML page (test this explicitly with a stub that returns 200 HTML).
5. XSS test item (Section 3.4) rendered inert — screenshot if a browser tool is available, else say so.
6. `grep -n "setInterval" dashboard/index.html` → no output; a description of the single bounded `setTimeout`
   polling path, and proof it stops on terminal status and after 60 s.
7. `git grep -nE "[0-9]{12}"` and a search for store IDs / log-group names — raw output. Existing tests
   (`lambda/`, `cli/`, `scripts/`) re-run with raw output.

---

## 9. Definition of Done

- [ ] `python cli/cedar_sentinel.py dashboard` starts a `127.0.0.1`-only, read-only server, opens the browser and
      shows the developer's own runs from their own account using their own credentials
- [ ] `--run <id>`, `--profile`, `--region`, `--table`, `--port`, `--no-open`, `--show-real-ids`,
      `--offline-dir` implemented and documented; there is no `--host`
- [ ] Host/Origin validation, GET-only, traversal protection, no CORS headers, `no-store` API responses
- [ ] Sanitization on by default; API output identical in shape to exported run files; shared module used by both
- [ ] Front-end detects live vs recorded mode strictly (200 + JSON + `"mode":"live"`); recorded mode and the
      Amplify site are unchanged and regression-tested
- [ ] All API data rendered as text (XSS test passes); bounded `PROCESSING` polling is the only polling
- [ ] No changes to `lambda/`, `infra/`, or `analyze`/`--apply` behavior (one hint line only); existing tests pass
- [ ] README, `docs/architecture.md`, `docs/limitations-and-mitigations.md`, `docs/ai-tool-disclosure.md` updated
- [ ] Secret/PII scans clean; PR opened from `phase-3c-local-dashboard` against `main`; **not merged, no tag**

---

## Response

Write your report to `responses/phase-03c-local-dashboard-response.md` (do not commit it), following the evidence
rule in Section 8. List anything you could not do or verify, and every deviation from this document.
