<!-- Intended repo path: docs/aws-console-setup.md -->
# AWS Console Setup — Cedar Sentinel

**Purpose:** get every AWS-side prerequisite configured so build work proceeds smoothly.

---

## Step 1 — Decide and lock your AWS region

Pick one region and use it for every service in this project: IAM user creation is
global, but Bedrock, CloudWatch Logs, Lambda, EventBridge, and Amplify are all
region-scoped.

1. `ap-south-1` (or `us-east-1`) is recommended.
2. Ensure all SAM and CLI configuration uses this region consistently.

---

## Step 2 — Create the dedicated IAM user

Do **not** use your root account or personal AWS credentials for the build. Everything
runs under one purpose-built IAM user.

1. Sign in to the **AWS Management Console**.
2. Navigate to **IAM → Users → Create user**.
3. Name: `cedar-sentinel-dev`.
4. Skip "Provide user access to the AWS Management Console" unless needed — CLI access is what matters.
5. On the permissions step, choose **Attach policies directly**, then **Create policy**
   and paste in the JSON below:

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
      "Action": ["bedrock:*", "verifiedpermissions:*", "access-analyzer:*"],
      "Resource": "*"
    },
    {
      "Sid": "DeployTooling",
      "Effect": "Allow",
      "Action": ["cloudformation:*", "s3:*", "amplify:*", "dynamodb:*"],
      "Resource": "*"
    }
  ]
}
```

6. Before saving, replace every `<ACCOUNT_ID>` with your real 12-digit account ID.
7. Name the policy `cedar-sentinel-dev-policy`, save it, then attach it to the `cedar-sentinel-dev` user.
8. Finish user creation and create an Access Key (CLI use case).

---

## Step 3 — Configure AWS CLI locally

1. Install the AWS CLI v2 (`aws --version` to check).
2. Run `aws configure` and enter the Access Key, Secret Key, and Region.
3. Verify: `aws sts get-caller-identity` returns the `cedar-sentinel-dev` user identity.

---

## Step 4 — Set an AWS Budget alert

1. Console → **Billing and Cost Management → Budgets → Create budget**.
2. Choose **Cost budget**, period **Monthly**, amount **$15–20**.
3. Add an alert threshold at 80% with your notification email.

---

## Step 5 — Enable Bedrock model access

The primary Bedrock model used is **Amazon Nova Lite** (`apac.amazon.nova-lite-v1:0` / `amazon.nova-lite-v1:0`). Nova Lite is a first-party Amazon model enabled by default with no Marketplace subscription or manual approval form required.

---

## Step 6 — Create a CloudTrail Trail delivering to CloudWatch Logs

This AWS account had never used CloudTrail Lake, so after AWS closed it to new customers on May 31, 2026, creating an event data store failed with `InvalidParameterException: CloudTrail Lake is no longer accepting new customers`. (The account had also only recently moved from the free tier to pay-as-you-go.)

A standard CloudTrail Trail delivering to CloudWatch Logs is used instead, providing equivalent scoped-query capability via CloudWatch Logs Insights:

1. Console → **CloudTrail → Trails → Create trail** (e.g. `cedar-sentinel-trail`).
2. S3 Bucket: create or specify a log storage bucket.
3. Enable **CloudWatch Logs** delivery. Let AWS auto-create the Log Group and IAM Role.
4. Event types: **Management events** (Read/Write).
5. Ensure the trail is set to **Logging: On**.
