<!-- Intended repo path: docs/ai-tool-disclosure.md -->
# AI Tool Disclosure Log

Required by the First Commit rules: *"AI coding tools are allowed. Name the ones you used
in your writeup."* This is the running source of truth — append the same day a tool is
used. Do not reconstruct this list on submission day.

| Date | Tool | Used for | Notes |
|---|---|---|---|
| Sep 11–13, 2026 | Claude (Anthropic) | Project ideation, problem-statement validation, architecture design (including catching and correcting the Cedar/AVP vs. IAM enforcement misconception), AWS rules research, drafting the master blueprint and Phase 1 instructions | Planning phase only, before the event clock started Sep 17 — no event-window code written at this stage |
| Sep 17, 2026 | Antigravity (agentic IDE) | Phase 1 scaffold implementation: CLI skeleton, SAM infrastructure template, Lambda handler, CloudWatch Logs query verification, Amplify hosting, and test orchestration | Day 1 kickoff / Phase 1 setup |
| Sep 18, 2026 | Antigravity (agentic IDE) | Phase 2 core reasoning & verification pipeline: Lambda 4-stage handler (CloudWatch Logs Insights query, Bedrock structured call, coverage/lockout check, Cedar/AVP validation), DynamoDB results table, CLI result polling and hard-block menu, SAM template IAM extensions | Day 2 / Phase 2 implementation |
| Sep 19, 2026 | Antigravity (agentic IDE) | Phase 2 hardening pass (phase-02-fixes): Nova Lite model switch, CLI self-analysis guard, eventSource-based action prefix fix, model-used logging (`BEDROCK MODEL USED` / `FALLBACK MODEL USED`), `aws-marketplace:*` removal, Bedrock policy resource scoping, `instructions/aws-console-setup.md` Step 5 update, architecture.md deviation entries, ai-tool-disclosure.md update | Day 2–3 / Phase 2 fixes pre-merge |
| Sep 19, 2026 | Antigravity (agentic IDE) | Phase 2 fixes round 2 (phase-02-fixes-round2): added `CEDAR_INVALID` DynamoDB/CLI status handling on verification failure, resolved BEDROCK_MODEL_ID logging at Bedrock stage start, zero-observed-actions Cedar forbid prompt rule and validation testing, SAM deployment verification | Day 3 / Phase 2 fixes round 2 |
| Sep 19, 2026 | Antigravity (agentic IDE) | Phase 3 IAM Translation & Enforcement: Cedar-to-IAM policy translator (`stage_iam_translation`) with CloudTrail-to-IAM action normalization, IAM Access Analyzer independent validation (`ValidatePolicy` & `CheckNoNewAccess`), `--apply` and `--policy-name` workflow with safety guards and interactive dry-run before/after diff, `iam:PutRolePolicy` with snapshotting (`previous_policy`) and eventual-consistency read-back, demo-role reset script (`scripts/reset_demo_role.py`), persistent AVP audit policy logging (`cedar-sentinel-audit-store`), and sanitized dashboard export (`scripts/export_run.py`) | Day 3 / Phase 3 implementation |
| Sep 19, 2026 | Antigravity (agentic IDE) | Phase 3b Dashboard Interface Rebuild: Rebuilt single-file dashboard (`dashboard/index.html`) to a dark monospace terminal / DevOps interface with 10-stage pipeline strip, grouped stage cards (ANALYZE, VERIFY, ENFORCE), interactive side panel, unified git-style policy diff, static recorded-run replay from sanitized runs (`dashboard/runs/`), zero external dependencies/CDNs/polling, validation script (`scripts/validate_runs.py`), and sanitizer unit testing | Day 3 / Phase 3b UI polish |
| Sep 20, 2026 | Antigravity (agentic IDE) | Phase 3c Local Live Dashboard Server: Implemented `cedar_sentinel.py dashboard` CLI subcommand with zero new dependencies using standard library `http.server` bound strictly to `127.0.0.1`, Host/Origin header validation against DNS rebinding, path traversal protection, read-only `Scan`/`GetItem` using developer's local AWS credentials, shared data sanitization/normalization (`cli/run_data.py`), dual-mode auto-detecting frontend (`dashboard/index.html`) supporting both static Amplify hosting and local live mode with bounded polling, hint output on completed analysis, and full unit test suite (`cli/test_dashboard_server.py`) | Day 4 / Phase 3c local dashboard |




---

## Writeup summary (draft — finalize on submission day)

> "We used Claude for pre-event architecture planning and technical research, and
> Antigravity as our agentic coding assistant throughout the build for [specific tasks].
> All core design decisions, AWS service integration, and final code review were done
> by the team member."
