---
name: har-to-jmx-lite
description: Convert browser-captured HAR network traces into clean Markdown API documentation and JMeter 5.6-compatible .jmx test plans with automatic noise filtering, sensitive-header redaction, and static XML/leak validation using zero third-party dependencies. Do not use to replay load tests against production hosts.
license: MIT
compatibility: Python 3.9+ standard library only (zero third-party packages required)
metadata:
  author: sunqi-2025
  version: "1.0.0"
---

# HAR to JMX Lite

Zero-dependency Python CLI that turns browser DevTools `.har` files into structured API documentation and clean JMeter 5.6 `.jmx` test plans.

## When to Use This Skill
- Turning a browser `.har` recording into an inventory of unique backend API endpoints (`scan`).
- Generating clean, credential-redacted Markdown API documentation from captured HTTP traffic (`doc`).
- Converting captured API flows into parameterized JMeter 5.6 `.jmx` scripts with built-in XML and secret-leak validation (`jmx`).

## When NOT to Use This Skill
- Do not use this skill to execute traffic or stress tests against production domains.
- Do not commit raw `.har` files containing live session cookies or real Bearer tokens into version control.

## Workflow

### Step 1: Inspect Captured Endpoints First
Always scan the `.har` file first to verify target hosts and confirm static noise is filtered out:

```bash
python3 scripts/har_to_jmx_lite.py scan <capture.har>
```

### Step 2: Generate Redacted API Docs or JMeter Test Plan
```bash
# Generate Markdown API documentation (EN or ZH, sensitive headers redacted)
python3 scripts/har_to_jmx_lite.py doc <capture.har> -o api_doc.md --lang en

# Generate JMeter 5.6 .jmx plan + run built-in XML & secret-leak validation
python3 scripts/har_to_jmx_lite.py jmx <capture.har> -o test_plan.jmx --validate

# Filter to a single staging host and configure load profile
python3 scripts/har_to_jmx_lite.py jmx <capture.har> -o test_plan.jmx \
  --allow-host staging.example.com --threads 20 --ramp-up 10 --loops 5 --validate
```

### Step 3: Review Guardrails Before Load Execution
Read `references/jmeter-guardrails.md` before running generated `.jmx` files in JMeter to avoid single-user caching distortion, missing dynamic token parameterization, or accidental writes against non-isolated environments.
