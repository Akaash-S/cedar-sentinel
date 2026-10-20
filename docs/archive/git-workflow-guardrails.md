<!-- Intended repo path: docs/git-workflow-guardrails.md -->
# Git Workflow Guardrails — Cedar Sentinel

**Applies to:** every phase, every agent session. This document doesn't replace the
per-phase instruction doc (`instructions/phase-0N-*.md`) — it sits underneath all of
them as the standing rule for how git gets touched. If a phase instruction doc ever
conflicts with this one on a git operation, this one wins.

**Why this exists:** `00-master-blueprint.md` Section 8 defines the branch/tag
strategy, and `phase-01-setup.md` Section 8 requires "no secrets/ARNs/account IDs in
git history" as an acceptance criterion. Both are easy to violate by accident during an
agent session that moves fast. This doc makes the boundary explicit so it doesn't
depend on the agent inferring it correctly each time.

---

## 1. The one rule that matters most

**The agent commits and pushes. The agent does not merge, and the agent does not tag.**

Merging to `main` and applying the phase tag (`v0.1-setup`, `v0.2-core-reasoning`, etc.)
happens only after Akaash has reviewed the response document for that phase and
confirmed it's clean. That review step is the actual checkpoint — not a formality.

| Action | Who does it |
|---|---|
| Create the phase branch off `main` | Agent |
| Write code, docs, infra | Agent |
| Commit incrementally | Agent |
| Run the pre-push scan (Section 2) | Agent |
| Fill in `responses/phase-0N-response.md` | Agent |
| Push the phase branch | Agent |
| Open the PR against `main` | Agent |
| **Review the PR + response doc** | **Akaash** |
| **Merge the PR (squash)** | **Akaash** |
| **Create and push the tag** | **Akaash** |
| Delete a branch, force-push, or rewrite any history on a shared branch | Nobody, unless Akaash explicitly says so in that exact session |

If a phase instruction doc says "tag on completion: `v0.1-setup`," read that as *"this
is the tag Akaash will apply once he's satisfied" — not an instruction for the agent to
run `git tag` itself.*

---

## 2. Pre-push secret & PII scan (mandatory, every push)

Run this before every `git push`, not just at the end of a phase. Report the results in
the phase's response document under a "Pre-push scan" subsection — don't just do it
silently.

1. **Grep the full diff for the real AWS account ID** (the actual 12-digit number, not
   `<ACCOUNT_ID>`), across every file — docs included, not just code:
   ```bash
   git diff --staged | grep -E '[0-9]{12}'
   ```
2. **Confirm `infra/.env.example` still has only placeholders** — `AWS_REGION=`,
   `BEDROCK_MODEL_ID=`, `CLOUDWATCH_LOG_GROUP_NAME=`, no real values. Real values belong
   only in the local `.env`.
3. **Confirm `.env` is actually gitignored, not just listed:**
   ```bash
   git check-ignore -v .env
   ```
4. **Check `infra/samconfig.toml`** for a baked-in account ID or ARN from
   `sam deploy --guided` — gitignore it if it has one.
5. **Check the response document itself** — "Evidence / notes" columns are the most
   likely place to paste a real ARN, account ID, or log group name as proof a check
   passed. Redact or genericize before committing.
6. **Check any doc that documents a query, log group, or resource name** (e.g. the
   CloudWatch Logs Insights pattern in `docs/architecture.md`) — the *pattern* is fine
   to commit; a real result set or real resource identifier pasted in as an example is
   not.

If the scan finds something already committed on the current branch (even if not yet
pushed): fix it with `git commit --amend` or an interactive rebase on that branch, not a
follow-up commit that leaves the secret sitting in earlier history. If it's already been
pushed anywhere — stop, flag it to Akaash in the response doc, and don't attempt to
force-push or rewrite the pushed history without him explicitly saying to.

---

## 3. Branch & commit conventions

- One branch per phase, exact names from the blueprint: `phase-1-setup`,
  `phase-2-core-logic`, `phase-3-enforcement`, `phase-4-demo-polish` — each cut from
  `main`, never from another phase branch.
- No direct commits to `main`. Everything lands via PR.
- Commit messages name the AWS service(s) the commit touches (per Section 8 of the
  blueprint) — e.g. `feat(lambda): add EventBridge-triggered SQS consumer`, not
  `wip` or `updates`.
- Keep commits scoped — a commit that touches `docs/` and `infra/` for unrelated
  reasons makes the eventual review harder, and review is the whole point of the
  handoff.

---

## 4. Handoff sequence, explicitly

1. Agent works through the current phase's instruction doc and acceptance checklist.
2. Agent runs the Section 2 scan and records the results in that phase's response doc.
3. Agent pushes the phase branch and opens the PR into `main`.
4. **Agent stops here.** No further git action until Akaash responds.
5. Akaash reviews the PR diff and the response doc.
6. Akaash squash-merges and creates the tag himself.
7. Only after the merge + tag exist does the next phase begin.

If Akaash's review turns up something that needs fixing, the agent pushes additional
commits to the *same* phase branch and waits again — the PR stays open until Akaash
merges it, however many review rounds that takes.
