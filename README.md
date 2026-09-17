# Cedar Sentinel

> Automated Least-Privilege IAM Policy Synthesis and Drift Detection via Cedar Verification & Amazon Bedrock.

**Track:** Ship It  
**Status:** Phase 1 — Setup  

---

## Overview

**Cedar Sentinel** is an automated IAM governance and least-privilege enforcement pipeline designed for modern AWS cloud infrastructure. Instead of relying on manual policy reviews or static linting that lacks runtime context, Cedar Sentinel intercepts planned IAM policies from Terraform changes, correlates them with historical CloudTrail usage via CloudWatch Logs Insights, and uses Amazon Bedrock with Cedar policy verification (Amazon Verified Permissions) to synthesize right-sized, least-privilege IAM policies.

Cedar Sentinel acts as a **verification and synthesis layer** that produces verified, drift-free IAM policies before changes are deployed.

---

## Repository Structure

```
cedar-sentinel/
├── cli/              # Python CLI for reading Terraform plans and dispatching events
├── lambda/           # Serverless pipeline handlers (ingestion, reasoning, verification)
├── infra/            # AWS SAM templates and infrastructure definitions
├── dashboard/        # Dry-run review and approval dashboard
├── docs/             # Architecture, AI tool disclosure, and attribution logs
├── responses/        # Phase completion reports and acceptance logs
├── .gitignore
├── LICENSE
└── README.md
```

---

## Getting Started (Phase 1)

### 1. Prerequisites
- Python 3.12+
- AWS CLI v2 configured with an active IAM profile
- AWS SAM CLI (1.160+)
- Terraform (1.15+)

### 2. Producing the Input Plan JSON
Cedar Sentinel analyzes Terraform plans produced using standard Terraform commands:

```bash
# Generate the binary plan output
terraform plan -out=tfplan.binary

# Convert the plan to machine-readable JSON format
terraform show -json tfplan.binary > tfplan.json
```

### 3. CLI Usage

```bash
# Navigate to CLI directory
cd cli

# Set up virtual environment
python -m venv .venv
source .venv/bin/activate  # Or on Windows: .venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Verify AWS connectivity
python cedar_sentinel.py check-aws

# Analyze Terraform plan and extract IAM policies
python cedar_sentinel.py analyze --plan-file ../cli/fixtures/sample_tfplan.json
```

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
