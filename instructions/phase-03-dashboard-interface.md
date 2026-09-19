<!-- Intended repo path: instructions/phase-03-dashboard-interface.md -->
# Instruction Document 3b — Dashboard Interface Rebuild (static recorded-run replay)
## Cedar Sentinel — First Commit (Bharat Builds Tour)

**To:** Antigravity coding agent
**From:** Project owner, following a design review of the dashboard as built and merged in Phase 3
**Event day this maps to:** Saturday, Sep 19, 2026 (UI-only polish; no feature work)
**Branch:** `phase-3b-dashboard` — create it off `main`. `main` already contains all of Phase 3 and is tagged
`v0.3-enforcement`; Amplify already deploys `dashboard/` from `main`.
**Tag:** none. Do **not** create a tag. The project owner will tag after review.
**Response goes to:** `responses/phase-03b-dashboard-response.md` (write it, but do **not** commit it)
**Standing rules:** `docs/git-workflow-guardrails.md` still applies (if not at that path, try
`instructions/git-workflow-guardrails.md`) — commit and push to your branch, open a PR against `main`, do
**not** merge, do **not** tag. Wait for review.

**This document replaces** `phase-03-enforcement.md` Section 8 and the earlier draft of this document.
Everything else in Phase 3 (translation, Access Analyzer, `--apply`, `PutRolePolicy`, the audit store) is
unchanged and must not be touched.

**Revision note:** the earlier draft assumed a live read-only API endpoint and a four-card pipeline. Both were
changed after review against what was actually built: (a) the results table deletes items after 72 hours, so
a live endpoint would return nothing when judges look days later, and a public unauthenticated endpoint would
expose role ARNs and policies; the dashboard now replays **recorded JSON files** served from the same
origin — no backend, no CORS; (b) the pipeline is now ten stages, covering IAM translation, Access
Analyzer, approval, enforcement and the audit record; (c) new statuses (`ANALYZER_INVALID`, `DECLINED`,
`APPLIED_UNVERIFIED`, `APPLY_FAILED`) are rendered; (d) several fields the earlier draft assumed do not exist
in the stored result item — see Section 2.4.

---

## 0. Objective & Scope

Replace the current dashboard with a dark, monospace, terminal/DevOps-style page that replays a **completed
run** as a ten-stage pipeline of cards, with a click-through detail panel and a git-diff-style policy diff.
The page is a static, dependency-free site.

**In scope**
- `dashboard/index.html` — one self-contained file (inline CSS + JS; no build step, no npm, no CDN, no
  external fonts/scripts/images).
- `dashboard/runs/index.json` (manifest) and `dashboard/runs/<name>.json` (sanitized recorded runs).
- An export script and a validation script (Section 2.3, Section 9).
- Rendering **every** status the pipeline can produce (Section 5).

**Explicitly out of scope — do not build**
- No API Gateway, no Lambda, no new DynamoDB access from the browser, no CORS work, no Cognito.
- No WebSocket, no polling, no live telemetry. Data is fetched from static files only.
- No write/approve action anywhere in the page. Approval stays CLI-only.
- **No changes to `lambda/`, `cli/`, `infra/` or any AWS resource.** If you believe one is needed, stop and
  flag it instead. (The only AWS access this task needs is *reading* existing result items, from your
  export script, using the dev credentials.)

If you find yourself adding a server, a build tool, a framework or a dependency, stop — that's not this task.

---

## 1. Visual design — terminal, not SaaS

The current build reads as a generic dark dashboard: rounded panels, blue headings, a pill badge, a sans-serif
title. The target is a terminal / git-diff look.

- **One monospace stack everywhere, including headings:**
  `ui-monospace, SFMono-Regular, "JetBrains Mono", Menlo, Consolas, "Liberation Mono", monospace`.
  Do not rely on a CSS variable that a static page won't define.
- **Palette (CSS custom properties defined in `:root`):** near-black background (`#0b0f14` or similar), body
  text `#c9d1d9`, muted `#6e7681`, success green `#3fb950`, failure red `#f85149`, warning amber `#d29922`,
  one restrained accent (cyan/blue, used sparingly for links and focus rings).
- **Flat.** No gradients, no glow, no box-shadows, no `border-radius` above 2px, 1px solid borders only,
  no icon libraries or images. Use text glyphs (`[✓]`, `[✗]`, `[!]`, `[—]`, `▸`, `│`, `▼`) as icons.
- **Header is a prompt line:** `$ cedar-sentinel analyze --apply` on the left, a plain-text status token such
  as `STATUS: APPLIED` on the right (bordered rectangle, not a pill).
- **Diff coloring** (anything showing requested-vs-tightened): removed lines red-toned with a `-` gutter,
  added lines green-toned with a `+` gutter, unchanged lines plain — matching the CLI's own diff output so the
  two surfaces read as one product. Subtle flat background tints are fine.
- Layout must not leave large empty panels (the current before/after view leaves the right panel mostly
  empty) and must not wrap identifiers mid-word (e.g. role names) — use `overflow-wrap: anywhere` only on
  long tokens that genuinely exceed the width, and prefer horizontal scroll inside `<pre>` blocks.
- **Wording (binding).** Do not use the phrases "Zero Workload Lockouts", "Formal Cedar Check", "Formal
  verification" or "Formally verified". Use "Cedar schema validation (STRICT)" and "Cedar policy
  (schema-validated via Amazon Verified Permissions)". Footer text:
  `Cedar Sentinel · First Commit · Ship It · recorded runs, read-only`.

---

## 2. Data: recorded runs, not a live endpoint

### 2.1 Files
```
dashboard/
  index.html
  runs/
    index.json          # manifest
    applied.json        # example names — see 2.2
    ...
```
Remove the old `dashboard/run.json` after migrating its content into `runs/` and update anything that
references it (README, `scripts/export_run.py`).

Manifest entry shape:
```json
{
  "id": "applied",
  "label": "APPLIED — guard removed 11 unobserved actions",
  "file": "runs/applied.json",
  "status": "APPLIED",
  "synthetic": false,
  "source_request_id": "db48ddbc-...",
  "captured_at": "2026-09-19T14:34:49+00:00"
}
```

### 2.2 Which runs to include
Export **real** result items wherever a real one exists, and do it **today** — the results table has a 72-hour
TTL and items from Sep 18–19 will start disappearing on Sep 21. Once exported, the JSON files are the source
of truth.

1. Using boto3 in the export script, scan `cedar-sentinel-results` for `request_id`, `status`,
   `completed_at` and list what statuses actually exist. Paste the (redacted) list in your response.
2. Include one run per status that has a real item: at minimum try `APPLIED` (request
   `db48ddbc-b4dd-4978-947c-c81f2131b1ab`, the guarded run), `DECLINED`, `ANALYZER_INVALID`, `BLOCKED`,
   `CEDAR_INVALID`.
3. For any of the remaining statuses with **no** real item (`APPLIED_UNVERIFIED`, `APPLY_FAILED`, `COMPLETE`
   awaiting approval, and any missing above), create a **crafted** item by copying a real one and changing
   only what that status requires. Crafted items must contain `"synthetic": true` and a
   `"synthetic_note"`, and the page must show an amber banner `SYNTHETIC EXAMPLE — crafted to demonstrate
   this state` whenever one is loaded. Never present a crafted item as a real run.
4. The default run shown on page load is the real `APPLIED` one.

### 2.3 Export script (`scripts/export_run.py`, extend the existing one)
- Usage (adjust flags if you must, but document them): `--request-id <id> --out dashboard/runs/<name>.json
  --label "<text>"`, plus `--synthetic --from <file> --set status=... --note "..."` for crafted items.
- Also regenerate `runs/index.json`.
- **Sanitization (mandatory, applied to the whole item, including nested and JSON-encoded string fields):**
  12-digit account IDs → `<ACCOUNT_ID>`; role/user ARNs keep the role name but use `<ACCOUNT_ID>`;
  AVP policy-store and policy IDs → `<AVP_STORE_ID>` / `<POLICY_ID>`; CloudTrail log-group names →
  `<LOG_GROUP>`; remove `ttl`. Request IDs may stay.
- Add unit tests for the sanitizer using an obviously fake item (e.g. account `123456789012`), and paste the
  output.

### 2.4 What the stored item actually looks like (read real items — do not assume)
Known fields from real items: `request_id`, `role_arn`, `status`, `model_used`, `completed_at`,
`requested_policy` (JSON-**encoded string**), `previous_policy` (JSON-encoded string), `iam_policy`
(JSON-encoded string), `cedar_policy` (Cedar text), `observed_actions` (map of action → count, **counts are
strings**), `action_mappings_applied`, `unmatched_actions`, `guard_removed_actions`, `rationale`,
`coverage_check {passed, blocked_actions}` (`blocked_actions` may be a string like `"[]"` or a list),
`cedar_validation {passed, messages, policy_store_id}`, `analyzer_validation {passed, reason, findings,
messages, check_no_new_access {result, message, reasons}}`, `stage_timings [{stage, start, end}]`,
`other_policies`, and (only on some runs) `audit_failed`.

Rules for the page:
- Parse JSON-encoded string fields and coerce counts to numbers **in the export script**, so the files in
  `runs/` hold clean data; the page should still tolerate either form.
- **Not stored, so do not invent:** the CloudWatch Logs Insights query text (use the template in
  `lambda/handler.py`, copied exactly, labeled "query template — role ARN substituted at runtime"); the plan
  file name (omit it); any timing for the CLI-side stages (show "not recorded"); the pre-guard raw model
  output (the stored `cedar_policy` is the post-guard result — say so); a per-action coverage table (compute it
  in the browser from `observed_actions` and `cedar_policy` and label it "recomputed in browser from stored
  data"; for `BLOCKED` runs use `coverage_check.blocked_actions` as the source of truth); the audit policy ID
  (state "recorded in the AVP audit store; ID not stored in the run item" unless present).
- Every missing field must render as a muted "not recorded", never as blank, `undefined` or a crash.

---

## 3. Fetch, then replay client-side

1. On page load: fetch `runs/index.json` once, then fetch the selected run's file once (default: the real
   `APPLIED` run; support `?run=<id>` for deep-linking). Selecting another run in the dropdown fetches that
   file once; each file is cached in memory and never fetched twice.
2. **No polling.** No `setInterval` anywhere in the page, no repeated `fetch` against the same file.
   (`setTimeout`/`requestAnimationFrame` for animation sequencing is fine.)
3. A **Replay** button restarts the animation from cached data with **no** new network request.
4. Show this label near the top, in muted text: `run complete · fetched once · replaying recorded stage
   timings (each card shown for at least 350 ms so it stays visible)`.
5. **Timing:** each Lambda stage's badge shows its **real** recorded duration (from `stage_timings`, `end -
   start`, shown as `N ms` or `N.NN s` at ≥1000 ms). The **animation** time for a card is
   `clamp(real_ms, 350, 1800)`; stages with no recorded timing use 450 ms and show "not recorded". A stage
   that really took 3.1 s must visibly take longer than one that took 1 ms. Never display the animated time
   as if it were the real time.
6. `prefers-reduced-motion: reduce` → skip animation and render the final state immediately.
7. If any fetch fails, show a visible error (`Could not load runs/<file> — HTTP <code>`), not a blank page.
   If the page is opened via `file://`, show a hint to serve it with `python -m http.server`.
8. After the last reached card completes, show the summary panel (Section 7).

---

## 4. The ten pipeline stages

Render a compact one-line **pipeline strip** at the top (ten small nodes `[1]─[2]─…─[10]`, each showing its
state glyph, wrapping on narrow screens) plus the ten **cards**, grouped under three headers: `ANALYZE`
(1–3), `VERIFY` (4–7), `ENFORCE` (8–10), joined by a thin vertical connector (`│` / `▼`).

Each card: glyph icon (left), title, status badge (right), one-line plain-English explanation, a muted
"under the hood" line naming the real AWS API call(s), and a monospace **detail line** populated from the
fetched run (never hardcoded). Badge progression: `pending` (muted) → `running` (amber, with the real
duration once known) → `done · <duration>` (green). Cards never reached in a given status show `— not
reached` (muted).

| # | Title | Explanation | Under the hood | Detail line (from data) | Timing source |
|---|---|---|---|---|---|
| 1 | Extract & publish | CLI read the Terraform plan and published it to EventBridge → SQS | `events:PutEvents` → `sqs` → Lambda | count of requested actions across statements | not recorded |
| 2 | Usage lookup | Lambda queried CloudWatch Logs Insights for the role's real activity | `logs:StartQuery` / `logs:GetQueryResults` | `N distinct observed actions` | `cloudwatch_query` |
| 3 | Draft | The model drafted a tightened Cedar policy plus rationale; a deterministic guard strips unobserved actions | `bedrock:InvokeModel` — model ID **read from `model_used`**, never hardcoded | `<model_used> · drafted policy has N actions · guard removed M` | `bedrock_call` |
| 4 | Coverage check | Every observed action must still be allowed by the draft | in-Lambda comparison (no AWS call) | `all N observed actions covered` or the dropped actions with counts | `coverage_check` |
| 5 | Cedar validation | Draft validated against a schema in a disposable AVP store, then discarded | `verifiedpermissions:PutSchema` / `CreatePolicy` / `DeletePolicy` | `STRICT schema validation: pass/fail` (+ first message) | `cedar_validation` |
| 6 | IAM translation | Verified Cedar translated to an IAM policy; CloudTrail event names mapped to IAM actions | in-Lambda (no AWS call) | `N actions · M mappings applied · K unmatched` | `iam_translation` |
| 7 | Access Analyzer | Independent check: policy syntax, and no access beyond the requested plan | `access-analyzer:ValidatePolicy` / `CheckNoNewAccess` | `N findings · no new access: PASS/FAIL` | `analyzer_validation` |
| 8 | Approval | Developer reviews the diff and approves in the CLI | none — CLI prompt (dashboard is read-only) | `approved` / `declined` / `awaiting decision` (derived from `status`) | not recorded |
| 9 | Apply & verify | Tightened policy written to the role, then read back | `iam:GetRolePolicy` → `iam:PutRolePolicy` → `iam:GetRolePolicy` | `overwrote inline policy · read-back confirmed` (derived from `status`) | not recorded |
| 10 | Audit record | Approved Cedar policy + rationale stored in a persistent AVP audit store | `verifiedpermissions:CreatePolicy` (audit store) | `recorded` / `not written` / `audit_failed` | not recorded |

Cards 8–10 are derived from `status` only; make clear on the card that they run in the CLI, not in Lambda.

---

## 5. Status matrix — render every state

Render whatever `status` the loaded item has. Failure states are **not** errors in the page — they are the
product working.

| `status` | Cards 1–7 | Card 8 | Card 9 | Card 10 | Outcome text in summary |
|---|---|---|---|---|---|
| `COMPLETE` | done | `awaiting decision` (pending) | not reached | not reached | "Verified. Not applied in this run." |
| `APPLIED` | done | done — approved | done — read-back confirmed | done — recorded | "Tightened policy applied and verified." |
| `APPLIED_UNVERIFIED` | done | done | **warning** — put succeeded, read-back not confirmed | not reached (audit skipped) | "Applied but not verified — inspect the role manually." |
| `APPLY_FAILED` | done | done | **failed** — show the recorded error if present | not reached | "Apply failed." |
| `DECLINED` | done | **declined** (amber) | not reached | not reached | "Developer declined. Nothing applied." |
| `BLOCKED` | 1–3 done; **4 blocked** (red/amber) listing each dropped action with its observed count, in the same wording as the CLI warning in `docs/differentiators.md`; 5–7 not reached | not reached | not reached | not reached | "Deployment blocked. The CLI offered a three-way choice: fall back / override (disabled in this build) / re-evaluate. The dashboard does not offer choices." |
| `CEDAR_INVALID` | 1–4 done; **5 failed** with the validation messages verbatim; 6–7 not reached | not reached | not reached | not reached | "Cedar validation rejected the draft. Nothing applied." |
| `ANALYZER_INVALID` | 1–6 done; **7 failed** showing `reason` (`VALIDATION_ERROR` or `NEW_ACCESS`) and each finding / reason verbatim | not reached | not reached | not reached | "Access Analyzer rejected the translated policy. Nothing applied." |
| `ERROR` / unknown | up to the last recorded stage | not reached | not reached | not reached | Show the status and any error message present |
| `PROCESSING` | — | — | — | — | Show "run still processing — nothing to replay"; do not animate |

Badge colors: done green; failed/blocked red; warning/declined/awaiting amber; not reached muted.

---

## 6. Detail side panel

- Layout: cards in the main column, a fixed-width panel (~400 px) on the right. On narrow viewports it
  becomes a bottom sheet with a close button; **Esc** closes it.
- Before any card is clicked: neutral placeholder text ("select a completed stage to see its full data").
- **Only completed cards are clickable** — done, failed or blocked cards (they have data). `pending`,
  `running` and `not reached` cards are not interactive. Cards are real `<button>`s, keyboard operable
  (Enter/Space), with a visible focus ring.
- Clicking a card renders that stage's full data from the **already fetched run object**. No network request
  per click (verify in the browser's Network tab). Monospace, scrollable, JSON/log style.

| Card | Panel content |
|---|---|
| 1 | Full requested-policy (every statement: Sid, effect, all actions, resource) and the role ARN (sanitized) |
| 2 | Every observed action with its exact count, sorted by count then name, plus the query template (labeled as a template) and the 7-day lookback |
| 3 | `model_used`; full `rationale`; full `cedar_policy` (labeled "post-guard"); full `guard_removed_actions` list with the note "removed because not observed in CloudTrail" |
| 4 | Every observed action with count and covered ✓/✗ (label: "recomputed in browser from stored data"); for `BLOCKED` runs, the recorded `blocked_actions` |
| 5 | `passed`, every message verbatim, mode STRICT, and one line: "the schema is generated from the draft's own actions, so this validates schema/syntax, not privilege escalation — Access Analyzer covers that". For `CEDAR_INVALID`, also the offending `cedar_policy` |
| 6 | The translated `iam_policy` JSON, `action_mappings_applied` (original → mapped), `unmatched_actions` |
| 7 | `ValidatePolicy` findings (each: type, code if present, details), `CheckNoNewAccess` result, message and reasons; the `reason` for `ANALYZER_INVALID` |
| 8 | What the CLI prompt is, the derived outcome, and "approval is CLI-only" |
| 9 | Unified diff of `previous_policy` → `iam_policy` (git-style, Section 7), read-back note, `other_policies` if any |
| 10 | What is stored in the audit store (Cedar policy + rationale in the description, request-ID prefix), whether it was written, and `audit_failed` if present |

---

## 7. Summary panel and policy diff

After the last reached card completes, show:
- **Total pipeline time** = sum of the recorded Lambda stage durations (real, not animated), labeled as such.
- The **outcome** text from the Section 5 matrix.
- The **unified policy diff**: flatten both policies to lines of the form `<Effect>  <Resource>  <Action>`;
  lines only in the requested policy render red with a `-` gutter, lines only in the tightened policy render
  green with a `+` gutter, identical lines plain. Add the guard's removed actions as a separate red block
  labeled "removed by deterministic guard (not observed)". Do not attempt wildcard-aware matching — plain
  line-level set difference is intended.
- For `BLOCKED`, `CEDAR_INVALID`, `ANALYZER_INVALID`, `DECLINED` there is no applied policy: show the
  requested vs drafted comparison if data exists, and say plainly that nothing was applied.

---

## 8. Accessibility & robustness (short)
- Sufficient contrast for text on the dark background; do not rely on color alone (glyphs + text labels).
- Works at 360 px width and at desktop width; no horizontal page scroll (scroll inside `<pre>` blocks).
- Run selector, Replay button and panel are keyboard reachable.
- Page must not throw on any of the ten statuses or on missing fields (test each; see Section 9).

---

## 9. Verification & evidence (verbatim only)

**Evidence rule for this document:** paste **only** raw output you actually produced by running the command,
and say which command produced it. Do not edit, reconstruct, retype or reuse earlier outputs. If you
cannot do something (for example take screenshots), say so plainly — do not describe results you did not
observe. Earlier phases had to be re-audited for exactly this reason.

Required:
1. `scripts/validate_runs.py` (new): loads every file listed in `runs/index.json` and asserts (a) required
   keys are present or explicitly allowed missing, (b) `status` matches the manifest, (c) crafted files have
   `synthetic: true`, (d) **no** 12-digit numbers, **no** `arn:aws:iam::` followed by digits, no policy-store
   or policy IDs. Paste its full output.
2. Sanitizer unit-test output (Section 2.3).
3. `git grep -nE "[0-9]{12}"` on your branch, plus a search for the audit store ID, policy-store IDs and the
   CloudTrail log-group name — paste the raw results.
4. `grep -n "setInterval" dashboard/index.html` (expect no output) and a search of the file for `http://` /
   `https://` (only namespace URIs, if any, are acceptable; no external resources).
5. The Section 2.2 status listing from the results table (redacted) and a table mapping each manifest entry
   to: real or synthetic, and the source request ID for real ones.
6. Serve locally (`python -m http.server` in `dashboard/`) and, **if your environment has a browser tool**,
   capture a screenshot of each of the ten statuses plus the mobile-width view and the open side panel.
   State which screenshots you took. If you have no browser tool, say so; the project owner will verify
   visually.
7. Confirm in writing, per behavior, that you tested it and how: one fetch per file (Network tab), Replay
   makes no request, clicking cards makes no request, reduced-motion path, fetch-failure message,
   `file://` hint, deep link `?run=<id>`.

---

## 10. Definition of Done

- [ ] Dark, monospace, flat terminal styling applied consistently; no gradients, glow, shadows or radius > 2px
- [ ] Ten stage cards + pipeline strip + three group headers render with real data; badges show real recorded
      durations; animation uses the clamped visible time; "not recorded" shown where timing doesn't exist
- [ ] Stage 3 shows `model_used` from the data, not a hardcoded model name
- [ ] All statuses in Section 5 render correctly; real items used where they exist; crafted items flagged
      `synthetic` and bannered on screen
- [ ] Side panel shows full, different data per completed card with no per-click network request; non-completed
      cards are not clickable
- [ ] Unified diff + guard-removed block + total pipeline time shown in the summary
- [ ] No `setInterval`, no external resources, no write/approve action, no backend or infra change
- [ ] Wording rules in Section 1 followed (no "Zero Workload Lockouts", no "Formal…")
- [ ] `runs/` sanitized; `validate_runs.py` and the `git grep` scans clean; old `run.json` removed
- [ ] `docs/architecture.md` updated: dashboard is a static recorded-run replay (no API endpoint); note the
      72-hour TTL reason
- [ ] `docs/ai-tool-disclosure.md` updated with today's entry
- [ ] PR opened from `phase-3b-dashboard` against `main`; **not merged, no tag**

---

## 11. Handoff

The project owner will review the PR, check the page locally and on the Amplify URL after merge (including
that `runs/*.json` are served as JSON, not rewritten to `index.html` by a hosting rule), tag, and continue to
Phase 4 (video, writeup, submission). Features remain frozen; this is presentation only.

---

## Response

Write your report to `responses/phase-03b-dashboard-response.md` (do not commit it), following the evidence
rule in Section 9. List anything you could not do, and every place you deviated from this document.
