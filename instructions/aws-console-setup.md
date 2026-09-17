<!-- Intended repo path: docs/aws-console-setup.md -->
# AWS Console Setup — Cedar Sentinel

**Purpose:** get every AWS-side prerequisite done before Thursday, Sep 17, 2026, so Day 1
is spent on Phase 1 build work, not account setup. This document exists specifically to
close out the pre-flight checklist in `instructions/phase-01-setup.md`, Section 1 — check
items off there as you complete the matching step here.

**Do this once, in this order** — later steps assume earlier ones are done (the IAM user
in Step 2 is what you'll use for everything after it).

**Revision note (Sep 17, 2026):** Step 6 previously created a CloudTrail Lake event
data store. AWS closed CloudTrail Lake to new customers on May 31, 2026 — this account
hits `InvalidParameterException: CloudTrail Lake is no longer accepting new customers`
if you try. Step 6 now sets up a standard CloudTrail Trail delivering to CloudWatch
Logs instead, which is unaffected by the closure and gives equivalent scoped-query
capability via CloudWatch Logs Insights.

---

## Step 1 — Decide and lock your AWS region

Pick one region and use it for every service in this project: IAM user creation is
global, but Bedrock, CloudWatch Logs, Lambda, EventBridge, and Amplify are all
region-scoped, and a mismatch between them is a common source of confusing errors that
look like permissions bugs but are actually a region bug.

1. `us-east-1` is the safest default — broadest Bedrock model catalog, most consistently
   available across every service this project touches.
2. Write your chosen region down somewhere you won't lose it. `phase-01-setup.md`'s
   pre-flight checklist has a blank for exactly this.

---

## Step 2 — Create the dedicated IAM user

Do **not** use your root account or personal AWS credentials for the build. Everything
runs under one purpose-built IAM user.

1. Sign in to the **AWS Management Console** as the root user, but only for this step.
2. Navigate to **IAM → Users → Create user**.
3. Name: `cedar-sentinel-dev`.
4. Skip "Provide user access to the AWS Management Console" unless you specifically want
   to log in as this user via the console too — CLI access is what actually matters here.
5. On the permissions step, choose **Attach policies directly**, then **Create policy**
   in a new tab and paste in the JSON below. This scopes `iam:PassRole` and
   `iam:CreateServiceLinkedRole` — the two actions AWS's own IAM Access Analyzer flags
   when left wildcarded — while keeping everything else practical for solo, fast
   iteration.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "IdentityAndAudit",
      "Effect": "Allow",
      "Action": [
        "sts:GetCallerIdentity",
        "cloudtrail:*",
        "logs:*"
      ],
      "Resource": "*"
    },
    {
      "Sid": "IamReadOnly",
      "Effect": "Allow",
      "Action": ["iam:Get*", "iam:List*"],
      "Resource": "*"
    },
    {
      "Sid": "IamRoleManagementScoped",
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole",
        "iam:DeleteRole",
        "iam:PutRolePolicy",
        "iam:DeleteRolePolicy",
        "iam:AttachRolePolicy",
        "iam:DetachRolePolicy",
        "iam:UpdateAssumeRolePolicy",
        "iam:TagRole",
        "iam:UntagRole"
      ],
      "Resource": "arn:aws:iam::<ACCOUNT_ID>:role/cedar-sentinel-*"
    },
    {
      "Sid": "PassRoleScopedToOwnRolesAndServices",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": "arn:aws:iam::<ACCOUNT_ID>:role/cedar-sentinel-*",
      "Condition": {
        "StringEquals": {
          "iam:PassedToService": [
            "lambda.amazonaws.com",
            "cloudformation.amazonaws.com",
            "amplify.amazonaws.com",
            "cloudtrail.amazonaws.com"
          ]
        }
      }
    },
    {
      "Sid": "EventPipeline",
      "Effect": "Allow",
      "Action": ["events:*", "sqs:*", "lambda:*"],
      "Resource": "*"
    },
    {
      "Sid": "ReasoningAndVerification",
      "Effect": "Allow",
      "Action": ["bedrock:*", "verifiedpermissions:*"],
      "Resource": "*"
    },
    {
      "Sid": "DeployTooling",
      "Effect": "Allow",
      "Action": ["cloudformation:*", "s3:*", "amplify:*"],
      "Resource": "*"
    }
  ]
}
```

   Note `cloudtrail.amazonaws.com` was added to the `PassedToService` list in the
   `PassRole` statement — creating a Trail with CloudWatch Logs delivery requires
   passing a role to the CloudTrail service, same as it does for Lambda or Amplify.

6. Before saving, replace every `<ACCOUNT_ID>` with your real 12-digit account ID
   (visible top-right in the console, or via `aws sts get-caller-identity` once you have
   any working credentials).
7. Name the policy `cedar-sentinel-dev-policy`, save it, then attach it to the
   `cedar-sentinel-dev` user.
8. Finish user creation.
9. Go to **IAM → Users → cedar-sentinel-dev → Security credentials → Create access key**.
   Choose **Command Line Interface (CLI)** as the use case.
10. **Copy both the access key ID and secret access key immediately** — the secret is
    only shown once.

**Acceptance check:** the user exists, has exactly one policy attached, and you have a
saved access key pair.

---

## Step 3 — Configure AWS CLI locally

1. Install the AWS CLI v2 if it isn't already (`aws --version` to check).
2. Run `aws configure` and enter:
   - Access key ID and secret from Step 2
   - Default region: the one you locked in Step 1
   - Default output format: `json` is fine
3. Verify: `aws sts get-caller-identity` should return the `cedar-sentinel-dev` user's
   ARN and your account ID — not an error, and not your root account's identity.

**Acceptance check:** this is the literal Phase 1 acceptance test for the CLI's
`check-aws` command, so passing it now removes a Day 1 blocker entirely.

---

## Step 4 — Set an AWS Budget alert

1. Console → **Billing and Cost Management → Budgets → Create budget**.
2. Choose **Cost budget**, period **Monthly**.
3. Set the budgeted amount to **$15–20**.
4. Add an alert threshold at 80% of budget, notification email = yours.
5. Save.

**Acceptance check:** the budget appears in your Budgets list with status **OK**, and
you've received (or can trigger a test of) the alert email setup.

---

## Step 5 — Enable Bedrock model access

Most Bedrock foundation models are enabled by default as of late 2025 — no manual
request step. **Anthropic models are the one exception**: they still need a one-time
usage form before first invocation.

1. Console → **Amazon Bedrock**, confirm you're in the region from Step 1.
2. Go to **Model access** (or open the **Playground** and pick an Anthropic model
   directly — either path triggers the form if it's needed).
3. Select a current-generation Claude model. Submit the one-time usage form if
   prompted — this is typically instant approval, not a multi-day wait.
4. Confirm the model shows **Access granted**.
5. Note the exact model ID (e.g. `anthropic.claude-sonnet-4-6`) somewhere you'll copy it
   from on Day 1 — don't hardcode it into any doc or code before then, since availability
   can shift.

**Acceptance check:** the model shows **Access granted** in the console, in the same
region your Lambda and CLI will run in.

---

## Step 6 — Create a CloudTrail Trail delivering to CloudWatch Logs

CloudTrail Lake is closed to new customers as of May 31, 2026 — attempting to create an
event data store here returns `InvalidParameterException`. This step uses a standard
Trail instead, which is unaffected by the closure and gives equivalent scoped-query
capability via CloudWatch Logs Insights.

1. Console → **CloudTrail → Trails → Create trail**.
2. Name it (e.g. `cedar-sentinel-trail`).
3. Choose an S3 bucket for log storage — create a new one; a Trail requires this
   regardless of whether you also send to CloudWatch.
4. In the same wizard, enable **CloudWatch Logs** delivery. Let AWS auto-create the
   **Log group** and the **IAM role** CloudTrail needs to write into it — if you create
   that role by hand instead, name it to match the `cedar-sentinel-*` pattern so it's
   covered by the dev user's IAM policy from Step 2.
5. Under event types, select **Management events** only — leave data events and
   network activity events off; they add cost this project doesn't need.
6. Choose **this region only**, not all regions — you only need visibility on a single
   test role's activity.
7. Confirm the trail shows **Logging: On**, then check **CloudWatch → Log groups** for
   the new log group — allow a few minutes for the first events to actually land.
8. Run a test query in **CloudWatch → Logs → Logs Insights**: select the log group, and
   run something like:
   ```
   fields eventTime, eventName, eventSource, userIdentity.arn
   | filter eventName = "AssumeRole"
   | sort eventTime desc
   | limit 20
   ```

**Acceptance check:** the trail shows **Logging: On**, the CloudWatch Logs group is
receiving events, and the test query above returns without error (Step 5 of
`phase-01-setup.md` covers saving the validated query pattern).

---

## What's deliberately *not* in this document

Amplify Hosting connection and the SAM/Lambda deploy happen **during Phase 1 itself**
(Day 1, Sep 17), not before — they're scaffolding work, not account prerequisites, and
`phase-01-setup.md` Sections 4 and 7 already cover them step by step. Don't get ahead of
the event clock by provisioning those early.

---

## Final checklist — maps to `phase-01-setup.md` Section 1

- [ ] Region decided and written down (Step 1)
- [ ] `cedar-sentinel-dev` IAM user created, dedicated policy attached, access key saved (Step 2)
- [ ] `aws sts get-caller-identity` returns the correct user and account (Step 3)
- [ ] AWS Budget alert active at $15–20 (Step 4)
- [ ] Bedrock model access shows granted for a current-generation Claude model (Step 5)
- [ ] CloudTrail Trail shows Logging: On, CloudWatch Logs group receiving events, test query succeeds (Step 6)
- [ ] AWS Builder Center profile verified — separate from this document, but equally blocking
