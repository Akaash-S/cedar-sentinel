<!-- Intended repo path: instructions/phase-03-dashboard-interface.md -->
# Instruction Document 3b — Dashboard Interface Rebuild (Stitch design → static recorded-run replay)
## Cedar Sentinel — First Commit (Bharat Builds Tour)

**To:** Antigravity coding agent
**From:** Project owner, following a design review of the dashboard as built and merged in Phase 3
**Event day this maps to:** Saturday, Sep 19, 2026 (UI-only rebuild; no feature work)
**Branch:** `phase-3b-dashboard` — create it off `main`. `main` already contains all of Phase 3 and is tagged
`v0.3-enforcement`; Amplify already deploys `dashboard/` from `main`.
**Tag:** none. Do **not** create a tag. The project owner will tag after review.
**Response goes to:** `responses/phase-03b-dashboard-response.md` (write it, but do **not** commit it)
**Standing rules:** `docs/git-workflow-guardrails.md` still applies (if not at that path, try
`instructions/git-workflow-guardrails.md`) — commit and push to your branch, open a PR against `main`, do
**not** merge, do **not** tag. Wait for review.

**You are given, alongside this document:**
1. `code.html` — an HTML/Tailwind export from Google Stitch. This is the **visual and structural source of
   truth**: layout, component structure, spacing, typography, colors, radii, hover/selected states.
2. A screenshot of that design.

**This document replaces** `phase-03-enforcement.md` Section 8 and every earlier draft of this document.
Everything else in Phase 3 (translation, Access Analyzer, `--apply`, `PutRolePolicy`, the audit store) is
unchanged and must not be touched.

**The single most important rule:** `code.html` is a *design mockup*. **Every number, name, ID, timestamp and
claim in it is placeholder content, and much of it is false for this project** (wrong model, wrong lookback
window, invented audit checksum, a real-looking account number, resource-scoped ARNs the tool never
produces). Copy the **design**; never copy the **content**. Section 2 lists every mock element and what
replaces it. Everything shown must come from the recorded run data or be derived from it.

---

## 0. Objective & Scope

Rebuild `dashboard/` as a static, dependency-light page that replays a **completed run** using the Stitch
design's components: fixed header with run selector and status, a four-card metrics HUD, a three-zone,
ten-stage execution graph with an interactive stage inspector, a dual-pane workbench (policy diff / Cedar
policy / stripped actions on the left, stage telemetry on the right), and a footer. The purpose is to let a
viewer see clearly what happened, and what is happening during the replay, under the hood.

**In scope**
- `dashboard/index.html` — one self-contained page (inline CSS + JS).
- `dashboard/runs/index.json` (manifest) and `dashboard/runs/<name>.json` (sanitized recorded runs).
- An export script and a validation script (Sections 3 and 9).
- Rendering **every** status the pipeline can produce (Section 6).
- Attribution rows for any third-party asset (Section 1.3).

**Explicitly out of scope — do not build**
- No API Gateway, no Lambda, no browser access to DynamoDB, no CORS work, no Cognito, no login/user avatar.
- No WebSocket, no polling, no live telemetry. Data comes from static files only.
- No write/approve action anywhere in the page. Approval stays CLI-only.
- **No changes to `lambda/`, `cli/`, `infra/` or any AWS resource.** If you believe one is needed, stop and flag
  it. (The only AWS access this task needs is *reading* existing result items from your export script.)

**Why recorded files, not a live endpoint:** the results table deletes items after 72 hours, so a live endpoint
would return nothing when judges look days later; a public unauthenticated endpoint would expose role ARNs and
policies; and it would add API Gateway/CORS work on the last night before the freeze.

---

## 1. Design source of truth & dependency rules

### 1.1 What to reproduce from `code.html`
Follow its structure and styling closely:
- **Header (fixed):** brand tile (shield icon) + "Cedar Sentinel" + small uppercase subtitle "Cloud Security
  Intelligence"; a command chip (`$ cedar-sentinel analyze --apply`, hidden below the `xl` breakpoint); a run
  selector (tag + label + chevron); a status pill; a **Replay Run** button; and a second row of four nav tabs.
- **HUD:** four metric cards (grid 1 / 2 / 4 columns) with a tinted icon tile, uppercase title, small tag,
  large number + label, muted sub-line, divider, and a footer row with a chip and a caption. Each card has a
  faint blurred corner glow.
- **Execution DAG section:** canvas header ("Execution Directed Acyclic Graph", "Interactive Stage
  Inspector" tag, subtitle, and two status chips: `Completed (n/10)` and `Inspecting: Stage n`), then three
  **zones** side by side — `ZONE 01: ANALYZE` (stages 1–3), `ZONE 02: VERIFY` (4–7), `ZONE 03: ENFORCE`
  (8–10) — each stage a `dag-node` card: status icon + "Stage N: Title" + right-aligned duration, a
  monospace line (API call · detail), and a footer chip row (uppercase label + value). The selected node has
  a ring, a lighter surface and a small pulse indicator.
- **Workbench (7/5 split at `xl`):** left pane with a tab bar (`Side-by-Side IAM Diff` · `Cedar Policy` ·
  `Stripped Actions (n)`), the side-by-side policy panes, and the red "actions removed by deterministic guard"
  alert; right pane "Stage Telemetry & Audit" with a stage-detail chip and stacked info cards.
- **Footer:** shield icon + `Cedar Sentinel · First Commit · Ship It · recorded runs, read-only`.
- **Design tokens** (port these exactly as CSS custom properties in `:root`; `code.html`'s
  `tailwind.config` is the full list):

| Token | Value | Token | Value |
|---|---|---|---|
| `--surface` / `--background` | `#10141a` | `--surface-container-lowest` | `#0a0e14` |
| `--surface-container-low` | `#181c22` | `--surface-container` | `#1c2026` |
| `--surface-container-high` | `#262a31` | `--surface-container-highest` | `#31353c` |
| `--on-surface` | `#dfe2eb` | `--on-surface-variant` | `#bdc8d1` |
| `--outline` | `#87929a` | `--outline-variant` | `#3e484f` |
| `--primary` | `#8ed5ff` | `--primary-container` | `#38bdf8` |
| `--secondary` (success) | `#4edea3` | `--secondary-container` | `#00a572` |
| `--tertiary` (guard/removed) | `#ffbcbf` | `--tertiary-container` | `#ff929a` |
| `--error` | `#ffb4ab` | `--error-container` | `#93000a` |

  The design has **no amber**. Add exactly one warning token, `--warning: #e3b341`, for
  warning/declined/awaiting states. Use `--secondary` for success, `--error` for failed/blocked,
  `--tertiary` for guard-removed items.
- **Typography:** Plus Jakarta Sans (headlines), Inter (body), JetBrains Mono (code, labels, tags), at the
  sizes/line-heights/letter-spacing in `tailwind.config` (`headline-xl` 36/44 — 28/36 on mobile, `headline-lg`
  24/32, `headline-md` 18/26, `body-lg` 15/22, `body-md` 13/18, `body-sm` 11/16, `label-code` 12/16,
  `label-code-sm` 11/14, `label-tag` 10/12 uppercase, `tracking 0.04em`, weight 600).
- **Spacing tokens:** xs 0.25rem, sm 0.5rem, md 0.75rem, lg 1rem, xl 1.5rem.
- **Radii:** use the values from the design's `rounded-corners-override` style (`rounded-xl` 1.125rem,
  `rounded-lg` 0.875rem, `rounded` 0.625rem, `.dag-node` 0.875rem, buttons 0.75rem), not Tailwind's defaults.
  (This supersedes the earlier "flat, ≤2px radius" idea — the Stitch design is now the reference.)

### 1.2 What NOT to copy from `code.html` (fix these while porting)
- **`<script src="https://cdn.tailwindcss.com">`** — do not ship the Tailwind runtime CDN. Port the design to
  plain CSS using the tokens above. (Alternative: run the Tailwind CLI **once** locally against the design's
  config to generate a static CSS file, commit only that generated CSS, and commit no `package.json`,
  `node_modules` or build step.) The shipped page must not load Tailwind at runtime.
- **Material Symbols icon font** — replace with a small **inline SVG sprite** (`<symbol>` set) containing only
  the icons actually used (e.g. shield_lock, terminal, expand_more, replay, check_circle, verified, gavel,
  timer, tune, account_tree, difference, monitoring, code_blocks, security, remove_circle, info, download,
  error, warning, hourglass, block). If the icon font fails, ligature text like "check_circle" would leak
  onto the page; an inline sprite cannot.
- **The user avatar (`person` icon)** — remove. There is no login and no user.
- **The "sync / Refresh Telemetry" button** — remove. There is no live data.
- **`::-webkit-scrollbar { display: none }`** — do not hide scrollbars globally. Scrollable code panes must
  show a thin, styled scrollbar so they are discoverable.
- **Magic `pt-24` under a fixed header** — the header height changes when it wraps on narrow screens. Use a
  sticky header, or measure the header height and offset the content, so nothing hides under it at any width.
- **Dead nav links (`href="#"` with `data-path`)** — wire them (Section 7.4).
- **`animate-pulse` on the status dot** — a permanent pulse reads as "live". Pulse only while a replay is
  running; when idle the dot is static.

### 1.3 Dependencies and attribution
- The only permitted external requests are **Google Fonts stylesheets** for Inter, JetBrains Mono and Plus
  Jakarta Sans, loaded with `display=swap`. Every font needs a system fallback stack; the page must be fully
  usable if the fonts fail to load.
- No CDN scripts, no external images, no analytics.
- Vanilla JS only. No frameworks, no npm packages shipped.
- Add rows to `docs/attribution.md` for: Material Symbols icons used in the SVG sprite (Apache-2.0); Inter,
  JetBrains Mono and Plus Jakarta Sans (SIL Open Font License 1.1); Tailwind CSS (MIT), only if you used its
  CLI to generate CSS. Include source URLs and the date.
- **Do not commit `code.html` or the design screenshot into `dashboard/`** (it is served publicly and contains
  mock IDs). Keep them local; if you must keep them in the repo, put them under `docs/design/`, never under
  `dashboard/`.

---

## 2. Mock content → real content (binding)

Everything in the left column is placeholder text or numbers in `code.html`. Replace as shown. Any value not
present in the recorded data renders as a muted `not recorded` — never blank, `undefined`, or a guess.

| Where | Mock content in `code.html` | Rule |
|---|---|---|
| Header run tag | `RUN #0941` | `RUN <first 8 chars of request_id>` |
| Header run label | "APPLIED — guard stripped 11 unobserved actions" | manifest `label` |
| Command chip | `$ cedar-sentinel analyze --apply` | manifest `command` string (default that text; runs that were print-only must not show `--apply`) |
| Status pill | "Status: Applied", always green, pulsing | real `status`, colored per Section 6, pulse **only** during replay |
| HUD 1 title / big number | "Attack Surface Posture", "7 Observed Actions" | keep title; number = count of distinct observed actions |
| HUD 1 sub-line / chip | "Pruned down from 18 broad role permissions", "**-61% attack surface**", "Baseline: 18" | **No percentage and no "attack surface" claim** (counting wildcard entries against specific actions is misleading). Sub-line: `Requested plan: R action entries (W wildcard) → applied policy: A actions`. Chip: `wildcards removed: n`. Caption: `Baseline: R entries`. Tag: `7D LOOKBACK` (the real lookback is **7 days**, not 14) |
| HUD 2 | "Guard Quarantine", "11 Unobserved Actions", chip "11 **destructive** stripped", "0 Re-eval Pass" | number = `guard_removed_actions.length`; **never label them "destructive"** (the real ones are `ec2:Describe*`, `logs:*` etc. — do not classify actions). Chip `n removed`; caption `not in CloudTrail`. If 0: neutral color, "guard made no changes". Tag `GUARD` |
| HUD 3 | "3.85s Total Exec", "10 STAGES", "10/10 Stages OK", "LLM: 2.24s" | total = **sum of recorded Lambda stage durations**; tag `n/10 STAGES` (stages reached); footer `n/10 stages OK` or the failing stage; `LLM: <bedrock_call duration>` |
| HUD 4 | "APPLIED", "Cedar Schema Validation PASS", "IAM Access Analyzer 0 FINDINGS", "Enforcement Ready", "100% Coverage" | real status; Cedar `PASS`/`FAIL`/`—`; analyzer `n FINDINGS` / `NEW ACCESS` / `—`; verdict text from the Section 6 matrix (**not** "Enforcement Ready"); coverage % = covered ÷ observed actions, computed in the browser |
| DAG stage 1 | "180ms", "200 OK" | duration `not recorded` (only Lambda stages have timings); chip `PLAN → EVENTBRIDGE` / `n ACTIONS REQUESTED` |
| DAG stage 2 | "540ms", "14d WINDOW" | recorded `cloudwatch_query`; chip `7D WINDOW` / `n ACTIONS` |
| DAG stage 3 | "anthropic.claude-3-sonnet-20240229-v1:0", "GUARD REVOKED / 11 UNUSED" | model = `model_used` (**never hardcode a model**; real runs used an Amazon Nova model); chip `GUARD STRIPPED` / `n REMOVED` |
| DAG stage 4 | "15ms", "100% COVERED" | recorded `coverage_check`; chip = computed `x/y COVERED` |
| DAG stage 5 | "415ms", `VALID` | recorded `cedar_validation`; chip `CEDAR SCHEMA (STRICT)` / `VALID` or `INVALID` |
| DAG stage 6 | "20ms", "2 STATEMENTS" | recorded `iam_translation`; chip `n STATEMENTS · m MAPPINGS` |
| DAG stage 7 | "620ms", "0 WARNINGS" | recorded `analyzer_validation`; chip `n FINDINGS · NO NEW ACCESS` (or `NEW ACCESS`) |
| DAG stage 8 | "INTERACTIVE", "**OPERATOR OVERRIDE / GRANTED**" | chip `CLI APPROVAL` / `APPROVED`, `DECLINED` or `AWAITING`. Never "override" — approving is the normal path |
| DAG stage 9 | "190ms", "REPLACED" | duration `not recorded`; chip `TARGET ROLE` / `OVERWRITTEN · VERIFIED` (per status) |
| DAG stage 10 | "INSPECTED", "**AUDIT SEALED**", "STORE ID: avp-audit-0941" | chip `AUDIT RECORD` / `RECORDED`, `NOT WRITTEN` or `AUDIT FAILED`; store shown as `<AVP_STORE_ID>` (sanitized) — **no "sealed"** |
| Diff pane titles | "ORIGINAL REQUESTED POLICY — 18 ACTIONS", "TIGHTENED IAM (STAGE 9 CONFIRMED) — 7 OBSERVED" | counts computed from the real policies; the "STAGE 9 CONFIRMED" wording only when status is `APPLIED` (else `TRANSLATED IAM (NOT APPLIED)`) |
| Diff policy bodies | Invented statements with **resource-scoped ARNs** (bucket ARNs, a table ARN) | render the **real** `requested_policy` and `iam_policy`. The tool tightens **actions only**; `Resource` stays as requested (usually `"*"`). **Never depict or fake resource scoping** |
| Guard alert | "11 Actions Removed…", "destructive management operations", "target developer PR draft", "14-day" | `M actions removed by deterministic guard (not observed in CloudTrail)`; body: "Actions in the model's draft that were never observed in the CloudTrail lookback window (7 days) were removed." Chips = real `guard_removed_actions` |
| Cedar tab | `AWS::S3::Action::"GetObject"`-style entities, scoped principal/resource, "Formal Verification Status … AST Schema … 0 TYPE MISMATCHES", tag "Strict Verified" | show the real stored `cedar_policy` text (it uses `CedarSentinel::Action::"service:Action"`), keyword-highlighted; footer `Cedar schema validation (STRICT): PASS/FAIL · n messages`; tag `STRICT · SCHEMA-VALID`. State it is the post-guard policy |
| Stripped tab | "0 queries in 14d", "REVOKED" | `0 observed calls in 7d`, badge `REMOVED` |
| Right pane subtitle | "AVP verified permissions **cryptographic** audit trail" | "Recorded telemetry for the selected stage" |
| Target role card | `role/service-role/prod-analytics-engine`, "Identity Store: **AWS Account 471120938**", "Role Online" | real sanitized role ARN (`arn:aws:iam::<ACCOUNT_ID>:role/<name>`); show `account: <ACCOUNT_ID> (sanitized)`; **delete** the account number and the "Role Online" status |
| Model rationale card | fixed sentence, "PROMPT EVALUATION: 1,482 TOKENS" | real `model_used` and full real `rationale`; `SYNTHESIS LATENCY` = `bedrock_call`; **delete token counts** (not stored) |
| Audit store card | "RECORDED & SEALED", `ps-cedar-893047`, "Audit Checksum sha256:d8a9e2f…", "Schema Timestamp 2025-02-18…", "COMMIT_SUCCESS" | fields: `Policy store: <AVP_STORE_ID>`; `Audit record: written / not written / audit failed`; `Run completed: <completed_at>`; `Run file SHA-256: <computed in browser with crypto.subtle from the fetched file text>` labeled "checksum of this recorded-run file (computed in your browser) — not an AWS audit seal". Delete "Schema Timestamp", "COMMIT_SUCCESS", "sealed" |
| CloudWatch card | "Window: 14d · Scanned 2.4M events · Matched 7 valid action signatures" | `Window: 7d · <sum of counts> calls across <n> distinct actions`. **Delete "Scanned … events"** (not stored). Keep the query-template note text |
| Buttons | "Export Audit Seal JSON", refresh icon | `Download run JSON` (saves the sanitized run file; no network write); remove refresh |
| Footer right | "Cedar Engine Strict", "v1.4.2-preview" | delete the invented version; `Cedar schema validation: STRICT` is acceptable |

**Forbidden wording anywhere on the page:** "Zero Workload Lockouts", "Formal Verification/Formal Cedar/Formally
verified", "cryptographic", "sealed / Audit Seal", "attack surface" percentages, "destructive" (as a label for
removed actions), "Role Online", "Enforcement Ready", "Operator Override", "AST schema".

---

## 3. Data: recorded runs, not a live endpoint

### 3.1 Files
```
dashboard/
  index.html
  runs/
    index.json          # manifest
    applied.json        # example names — see 3.2
    ...
```
Remove the old `dashboard/run.json` after migrating its content into `runs/`, and update anything that
references it (README, `scripts/export_run.py`).

Manifest entry shape:
```json
{
  "id": "applied",
  "label": "APPLIED — guard removed 11 unobserved actions",
  "command": "$ cedar-sentinel analyze --apply",
  "file": "runs/applied.json",
  "status": "APPLIED",
  "synthetic": false,
  "source_request_id": "db48ddbc-...",
  "captured_at": "2026-09-19T14:34:49+00:00"
}
```

### 3.2 Which runs to include
Export **real** result items wherever a real one exists, and do it **today** — the results table has a 72-hour
TTL and items from Sep 18–19 start disappearing on Sep 21. Once exported, the JSON files are the source of
truth.
1. Using boto3 in the export script, scan `cedar-sentinel-results` for `request_id`, `status`, `completed_at`
   and list which statuses actually exist. Paste the (redacted) list in your response.
2. Include one run per status that has a real item; at minimum try `APPLIED` (request
   `db48ddbc-b4dd-4978-947c-c81f2131b1ab`, the guarded run), `DECLINED`, `ANALYZER_INVALID`, `BLOCKED`,
   `CEDAR_INVALID`.
3. For each remaining status with **no** real item (`APPLIED_UNVERIFIED`, `APPLY_FAILED`, `COMPLETE`
   awaiting approval, and any missing above), create a **crafted** item by copying a real one and changing
   only what that status requires. Crafted items carry `"synthetic": true` and a `"synthetic_note"`, and the
   page shows an amber banner `SYNTHETIC EXAMPLE — crafted to demonstrate this state` whenever one is loaded.
   Never present a crafted item as a real run.
4. The default run on page load is the real `APPLIED` one.

### 3.3 Export script (`scripts/export_run.py`, extend the existing one)
- Usage (adjust flags if you must, but document them): `--request-id <id> --out dashboard/runs/<name>.json
  --label "<text>" --command "<text>"`, plus `--synthetic --from <file> --set status=... --note "..."` for
  crafted items. It also regenerates `runs/index.json`.
- **Sanitization (mandatory; applied to the whole item including nested and JSON-encoded string fields):**
  12-digit account IDs → `<ACCOUNT_ID>`; role/user ARNs keep the role name but use `<ACCOUNT_ID>`; AVP
  policy-store and policy IDs → `<AVP_STORE_ID>` / `<POLICY_ID>`; CloudTrail log-group names → `<LOG_GROUP>`;
  remove `ttl`. Request IDs may stay.
- Unit tests for the sanitizer using an obviously fake item (e.g. account `123456789012`); paste the output.

### 3.4 What the stored item actually looks like (read real items — do not assume)
Known fields from real items: `request_id`, `role_arn`, `status`, `model_used`, `completed_at`,
`requested_policy` (JSON-**encoded string**), `previous_policy` (JSON-encoded string), `iam_policy`
(JSON-encoded string), `cedar_policy` (Cedar text), `observed_actions` (map action → count, **counts are
strings**), `action_mappings_applied`, `unmatched_actions`, `guard_removed_actions`, `rationale`,
`coverage_check {passed, blocked_actions}` (`blocked_actions` may be the string `"[]"` or a list),
`cedar_validation {passed, messages, policy_store_id}`, `analyzer_validation {passed, reason, findings,
messages, check_no_new_access {result, message, reasons}}`, `stage_timings [{stage, start, end}]`
(stages: `cloudwatch_query`, `bedrock_call`, `coverage_check`, `cedar_validation`, `iam_translation`,
`analyzer_validation`), `other_policies`, and (only on some runs) `audit_failed`.

- Parse JSON-encoded string fields and coerce counts to numbers **in the export script** so the files in
  `runs/` are clean; the page should still tolerate either form.
- **Not stored — do not invent:** the CloudWatch query text (use the template in `lambda/handler.py`, copied
  exactly, labeled "query template — role ARN substituted at runtime"); the plan file name (omit); timing for
  the CLI-side stages 1, 8, 9, 10 (`not recorded`); the pre-guard raw model output (the stored `cedar_policy`
  is post-guard — say so); a per-action coverage table (compute it in the browser from `observed_actions` and
  `cedar_policy`, labeled "recomputed in browser from stored data"; for `BLOCKED` runs use
  `coverage_check.blocked_actions` as the source of truth); the audit policy ID (say "recorded in the AVP audit
  store; ID not stored in the run item" unless present); token counts; number of events scanned.

---

## 4. Page structure & component binding

1. **Header** (Section 1.1). Run selector lists manifest entries (a real `<select>` or an accessible custom
   listbox); synthetic entries are marked. Selecting one loads that file once. Second row nav: Section 7.4.
2. **Notices row (new; the design lacks it):** directly under the header, a muted line:
   `run complete · fetched once · replaying recorded stage timings (each stage shown for at least 350 ms so it
   stays visible)`. For synthetic runs, the amber banner from Section 3.2.
3. **HUD**: four cards bound per Section 2.
4. **Execution DAG**: canvas header chips: `Completed (reached/10)` (or the status name when a stage failed)
   and `Inspecting: Stage n`. Zones and nodes per Section 1.1 and the stage table below.
5. **Workbench**: left pane (tabs + diff/cedar/stripped + guard alert) and right pane (stage telemetry).
6. **CloudTrail Log Intelligence section (new; the design's 4th nav tab has no content):** full-width panel
   with (a) a table of every observed action: name, call count, a proportional bar, covered ✓/✗, mapped IAM
   action (if a mapping was applied), included-in-final ✓/✗; (b) the query template in a `<pre>`; (c) the 7-day
   window and `<sum> calls across <n> distinct actions`; (d) a note: "S3 object-level actions appear only if S3
   data events are enabled for the bucket — see docs/limitations-and-mitigations.md".
7. **Footer** (Section 1.1).

### Stage nodes — content
| # | Title | API / detail line (mono) | Duration source |
|---|---|---|---|
| 1 | Extract & publish | `events:PutEvents → sqs → Lambda` | not recorded |
| 2 | Usage lookup | `logs:StartQuery / logs:GetQueryResults` | `cloudwatch_query` |
| 3 | Draft | `bedrock:InvokeModel · <model_used>` | `bedrock_call` |
| 4 | Coverage check | `in-Lambda · all n observed covered` (or dropped actions) | `coverage_check` |
| 5 | Cedar validation | `verifiedpermissions:PutSchema · STRICT` | `cedar_validation` |
| 6 | IAM translation | `in-Lambda · n actions · m mappings` | `iam_translation` |
| 7 | Access Analyzer | `access-analyzer:ValidatePolicy / CheckNoNewAccess` | `analyzer_validation` |
| 8 | Approval | `CLI prompt · <approved / declined / awaiting>` | not recorded |
| 9 | Apply & verify | `iam:PutRolePolicy · read-back <confirmed / unconfirmed>` | not recorded |
| 10 | Audit record | `verifiedpermissions:CreatePolicy · persistent AVP store` | not recorded |

Nodes 8–10 are derived from `status` only; say on the node or in the inspector that they run in the CLI, not
in Lambda. Node icon states: pending (hourglass, muted) · running (pulse, `--primary`) · done (check,
`--secondary`) · failed/blocked (error, `--error`) · warning/declined/awaiting (warning, `--warning`) · not
reached (muted dash, non-interactive).

---

## 5. Fetch, replay, and "what is happening right now"

1. On load: fetch `runs/index.json` once, then the selected run file once (default: the real `APPLIED` run;
   support `?run=<id>`). Selecting another run fetches that file once; files are cached in memory and never
   fetched twice.
2. **No polling.** No `setInterval` anywhere in the page and no repeated `fetch` of the same file.
   (`setTimeout` / `requestAnimationFrame` for animation sequencing is fine.)
3. The replay **auto-plays once on load** (skip with `?autoplay=0`, which shows the final state immediately —
   handy for recording). **Replay Run** restarts the animation from cached data with **no** network request.
4. **While a stage is running**, the UI shows what is happening under the hood right now: that node is in the
   running state; the `Inspecting: Stage n` chip and the right pane follow the running stage; the right pane
   shows that stage's API call line and, as it completes, its real result. The status pill pulses only during
   the replay.
5. **Timing:** each Lambda stage's node shows its **real** recorded duration (`end - start`, formatted `N ms`
   or `N.NN s` at ≥1000 ms). The **animation** time is `clamp(real_ms, 350, 1800)`; stages with no recorded
   timing animate 450 ms and show `not recorded`. Never present the animated time as the real time.
6. After the last reached stage completes, the inspector selects it (design default: "Inspecting: Stage 10"
   for a fully applied run) and the HUD values are already final (HUD is populated on load; only the DAG
   animates).
7. `prefers-reduced-motion: reduce` → no animation; render the final state immediately.
8. If any fetch fails, show a visible error (`Could not load runs/<file> — HTTP <code>`), never a blank
   page. If opened via `file://`, show a hint to serve with `python -m http.server`.

---

## 6. Status matrix — render every state

Failure states are not errors in the page — they are the product working. Render whatever `status` the
loaded item has.

| `status` | Nodes 1–7 | Node 8 | Node 9 | Node 10 | Header pill / HUD-4 verdict text |
|---|---|---|---|---|---|
| `COMPLETE` | done | awaiting (pending) | not reached | not reached | `COMPLETE` · "Verified — not applied in this run" |
| `APPLIED` | done | done — approved | done — read-back confirmed | done — recorded | `APPLIED` (green) · "Enforced and verified" |
| `APPLIED_UNVERIFIED` | done | done | **warning** — put succeeded, read-back not confirmed | not reached (audit skipped) | `APPLIED_UNVERIFIED` (amber) · "Applied, not verified — inspect the role" |
| `APPLY_FAILED` | done | done | **failed** (show recorded error if present) | not reached | `APPLY_FAILED` (red) · "Apply failed" |
| `DECLINED` | done | **declined** (amber) | not reached | not reached | `DECLINED` (amber) · "Declined — nothing applied" |
| `BLOCKED` | 1–3 done; **4 blocked** listing each dropped action with its observed count (same wording as the CLI warning in `docs/differentiators.md`); 5–7 not reached | not reached | not reached | not reached | `BLOCKED` (red) · "Blocked — workload lockout prevented". Summary text: "The CLI offered a three-way choice: fall back / override (disabled in this build) / re-evaluate. The dashboard offers no choices." |
| `CEDAR_INVALID` | 1–4 done; **5 failed** with validation messages verbatim; 6–7 not reached | not reached | not reached | not reached | `CEDAR_INVALID` (red) · "Cedar validation rejected the draft" |
| `ANALYZER_INVALID` | 1–6 done; **7 failed** showing `reason` (`VALIDATION_ERROR` / `NEW_ACCESS`) and each finding/reason verbatim | not reached | not reached | not reached | `ANALYZER_INVALID` (red) · "Access Analyzer rejected the policy" |
| `ERROR` / unknown | up to the last recorded stage | not reached | not reached | not reached | show the status and any error message |
| `PROCESSING` | — | — | — | — | "run still processing — nothing to replay"; no animation |

For runs where no policy was applied, the right diff pane is titled `TRANSLATED IAM (NOT APPLIED)` if a
translation exists, `DRAFT (NOT APPLIED)` otherwise, with a plain sentence that nothing was applied.
HUD 3's failing-stage text names the stage that stopped the run.

---

## 7. Interactions

### 7.1 Stage inspector (right pane, "Stage Telemetry & Audit")
The pane's top card (Target Role, sanitized) is always shown. Below it, the content follows the selected
node ("Stage n Detail" chip). Only completed nodes (done, failed, blocked, warning) are clickable;
pending / running / not-reached nodes are not interactive. Nodes are real `<button>`s (Enter/Space, visible
focus ring). Clicking renders data **from the already-fetched run object — no network request per click**.

| Node | Inspector content |
|---|---|
| 1 | Full requested policy (each statement: Sid, effect, all actions, resource), role ARN (sanitized) |
| 2 | CloudWatch Lookup Context: every observed action with exact count (sorted by count then name), query template (labeled), 7-day window, `<sum> calls across <n> actions` |
| 3 | Model Rationale card: `model_used`, full `rationale`, full `cedar_policy` (labeled post-guard), full `guard_removed_actions` ("removed because not observed in CloudTrail"), `SYNTHESIS LATENCY` |
| 4 | Every observed action with count and covered ✓/✗ ("recomputed in browser from stored data"); for `BLOCKED`, the recorded `blocked_actions` |
| 5 | `passed`, every validation message verbatim, mode STRICT, and one line: "the schema is generated from the draft's own actions, so this validates schema/syntax, not privilege escalation — Access Analyzer covers that". For `CEDAR_INVALID`, also the offending `cedar_policy` |
| 6 | The translated `iam_policy` JSON, `action_mappings_applied` (original → mapped), `unmatched_actions` |
| 7 | `ValidatePolicy` findings (type, code if present, details), `CheckNoNewAccess` result/message/reasons; the `reason` for `ANALYZER_INVALID` |
| 8 | What the CLI prompt is, the derived outcome, and "approval is CLI-only" |
| 9 | Unified diff `previous_policy` → `iam_policy` (Section 7.3), read-back note, `other_policies` if any |
| 10 | Persistent AVP Audit Store card per Section 2 (store placeholder, audit record status, run-completed time, computed file SHA-256 with its label), plus what is stored there (Cedar policy + rationale in the description, request-ID prefix) |

Selecting a node also switches the left tab where relevant: stage 3 → Stripped Actions; 5 → Cedar Policy;
6 and 9 → Side-by-Side IAM Diff. Clicking a tab manually never changes the selected node.

### 7.2 Left pane tabs
`Side-by-Side IAM Diff` · `Cedar Policy` · `Stripped Actions (n)` — `n` is the real count, and the tab
behaves as a proper tablist (arrow keys, `aria-selected`).

### 7.3 Policy diff rule
Pretty-print both policies as in the design (one line element per line, indentation preserved). Flatten each
policy to lines `<Effect>  <Resource>  <Action>`; lines only in the requested policy are tinted red with a
`-` gutter, lines only in the tightened policy are tinted green with a `+` gutter, identical lines are plain.
Plain line-level set difference; do **not** attempt wildcard-aware matching. Guard-removed actions appear in
the red alert block below (Section 2).

### 7.4 Nav tabs (header, second row)
Single-page anchors, not routes: `Pipeline Graph (DAG)` → DAG section; `Policy Comparison Diff` → left
workbench pane; `Audit & Verification Telemetry` → right workbench pane; `CloudTrail Log Intelligence` → the
new Section 4 item 6 panel. Clicking scrolls (offset for the header) and marks that tab active; the active tab
follows scroll position. Use the design's active-tab styling.

---

## 8. Responsive & accessibility
- Breakpoints as in the design: HUD 1 / 2 / 4 columns; workbench stacks below `xl`; DAG zones stack on narrow
  screens. Works at 360 px and at 1440 px+; no horizontal page scroll (scroll inside code panes).
- The header must not overflow on narrow screens: collapse the command chip (already hidden below `xl`),
  wrap the run selector / status / replay onto a second line, and let the nav row scroll horizontally.
- Never rely on color alone: icons + text labels carry the state. Sufficient contrast on the dark surfaces.
- Everything interactive is keyboard reachable with a visible focus ring; Esc closes any overlay or bottom
  sheet used on mobile.
- The page must not throw on any of the ten statuses or on missing fields (test each; Section 9).

---

## 9. Verification & evidence (verbatim only)

**Evidence rule for this document:** paste **only** raw output you actually produced by running the command,
and say which command produced it. Do not edit, reconstruct, retype or reuse earlier outputs. If you cannot do
something (for example take screenshots), say so plainly — do not describe results you did not observe.
Earlier phases had to be re-audited for exactly this reason.

Required:
1. `scripts/validate_runs.py` (new): loads every file in `runs/index.json` and asserts (a) required keys are
   present or explicitly allowed missing, (b) `status` matches the manifest, (c) crafted files have
   `synthetic: true`, (d) **no** 12-digit numbers, no `arn:aws:iam::` followed by digits, no policy-store or
   policy IDs. Paste its full output.
2. Sanitizer unit-test output (Section 3.3).
3. `git grep -nE "[0-9]{12}"` on your branch, plus searches for the audit store ID, policy-store IDs and the
   CloudTrail log-group name — paste the raw results.
4. `grep -n "setInterval" dashboard/index.html` (expect no output). A search of `dashboard/index.html` for
   `http://` / `https://` showing that the **only** external URLs are the Google Fonts stylesheet(s) (and SVG
   namespace URIs, if any) — no `cdn.tailwindcss.com`, no other hosts.
5. A search for every forbidden phrase in Section 2 (case-insensitive) across `dashboard/` — expect no hits —
   and a search for the mock values (`0941`, `471120938`, `claude-3-sonnet`, `avp-audit`, `ps-cedar`,
   `d8a9e2f`, `v1.4.2`, `2.4M`, `1,482`) — expect no hits.
6. The Section 3.2 status listing (redacted) and a table mapping each manifest entry to: real or synthetic,
   and the source request ID for real ones.
7. Serve locally (`python -m http.server` in `dashboard/`). **If your environment has a browser tool**,
   capture screenshots: the default (`APPLIED`) run at ~1440 px and at ~390 px; each other status; the
   Stripped tab; the Cedar tab; a selected stage inspector. Compare the desktop capture with the supplied
   Stitch screenshot and **list every visual deviation** you made or could not match. State which screenshots
   you took; if you have no browser tool, say so — the project owner will verify visually.
8. Confirm in writing, per behavior, that you tested it and how: one fetch per file (Network tab), Replay
   makes no request, clicking nodes/tabs makes no request, reduced-motion path, fetch-failure message,
   `file://` hint, `?run=<id>`, `?autoplay=0`, header at narrow width.

---

## 10. Definition of Done

- [ ] Visual structure and tokens match the Stitch design; deviations listed in the response
- [ ] No Tailwind CDN, no icon font, no other external requests than Google Fonts; inline SVG sprite used
- [ ] HUD, DAG (3 zones / 10 nodes), workbench (3 tabs), right-pane inspector, Log Intelligence section and
      footer all render from **real recorded data**; every mock value in Section 2 replaced
- [ ] Stage 3 model name read from `model_used`; lookback shown as 7 days; no invented metrics
- [ ] Real durations shown; animation uses the clamped visible time; `not recorded` where no timing exists;
      status pill pulses only during replay
- [ ] All statuses in Section 6 render correctly; real items used where they exist; crafted items flagged
      `synthetic` and bannered
- [ ] Node click → inspector shows full, different data per completed node, with no per-click network request
- [ ] Diff, Cedar and Stripped tabs show the real policies; no resource scoping is depicted that the data
      does not contain
- [ ] Nav tabs wired; header does not overflow at narrow widths; scrollbars not globally hidden
- [ ] No `setInterval`, no write/approve action, no backend or infra change, no user avatar, no refresh button
- [ ] Forbidden-wording and mock-value searches clean
- [ ] `runs/` sanitized; `validate_runs.py` and the `git grep` scans clean; old `run.json` removed
- [ ] `docs/architecture.md` updated: dashboard is a static recorded-run replay (no API endpoint; 72-hour TTL
      is why); `docs/attribution.md` updated (Section 1.3); `docs/ai-tool-disclosure.md` updated
- [ ] PR opened from `phase-3b-dashboard` against `main`; **not merged, no tag**

---

## 11. Handoff

The project owner will review the PR, check the page locally and on the Amplify URL after merge (including
that `runs/*.json` are served as JSON and not rewritten to `index.html` by a hosting rule), tag, and continue
to Phase 4 (video, writeup, submission). Features remain frozen; this is presentation only.

---

## Response

Write your report to `responses/phase-03b-dashboard-response.md` (do not commit it), following the evidence
rule in Section 9. List anything you could not do, and every place you deviated from this document or the
Stitch design.
