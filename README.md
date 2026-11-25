# har-to-jmx-lite

[![CI](https://github.com/sunqi-2025/har-to-jmx-lite/actions/workflows/ci.yml/badge.svg)](https://github.com/sunqi-2025/har-to-jmx-lite/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-3776AB.svg)](https://www.python.org/)

English | [简体中文](README.zh-CN.md)

A **zero-dependency HAR-to-JMeter 5.6 `.jmx` & API Markdown converter**—usable both as a standalone Python CLI and as a standard **`SKILL.md` Agent Skill** (compatible with Claude Code, Cursor, Codex CLI, Gemini CLI, Antigravity, and Agensi.io).

Browser `.har` exports are noisy and dangerous to share raw: they mix static `.js`/`.css`/image traffic with real API calls and embed live `Authorization` / `Cookie` credentials. `har-to-jmx-lite` strips static & `OPTIONS` noise, redacts sensitive headers automatically, generates readable Markdown API docs, builds clean parameterized JMeter 5.6 `.jmx` plans (avoiding the reverse-proxy `417 Expectation Failed` pitfall), and validates output XML for structural integrity and leaked tokens.

---

## Quick Start

Requires **Python 3.9+** (standard library only, zero `pip install`).

```bash
# 1. Scan unique backend endpoints from a browser HAR recording
python3 scripts/har_to_jmx_lite.py scan examples/sample_shop_api.har

# 2. Generate credential-redacted Markdown API documentation (EN or ZH)
python3 scripts/har_to_jmx_lite.py doc examples/sample_shop_api.har -o api_doc.md --lang en

# 3. Generate a parameterized JMeter 5.6 .jmx test plan and validate it
python3 scripts/har_to_jmx_lite.py jmx examples/sample_shop_api.har -o shop_flow.jmx \
  --threads 10 --ramp-up 5 --loops 2 --validate

# 4. Validate an existing .jmx file for XML errors or leaked Bearer/JWT tokens
python3 scripts/har_to_jmx_lite.py validate shop_flow.jmx

# Run unit tests
python3 -m unittest discover -s tests -v
```

---

## Key Features

- **Smart Noise Filtering**: Drops static extensions (`.js`, `.css`, images, fonts, source maps), `OPTIONS` preflight calls, and non-HTTP entries; normalizes numeric IDs and UUIDs into `/{id}` / `/{uuid}` for clean deduplication.
- **Automatic Credential Redaction & Parameterization**: Redacts `Authorization`, `Cookie`, and API-key headers in Markdown docs, and parameterizes tokens as `${AUTH_TOKEN}` (plus `${PROTOCOL}`, `${BASE_HOST}`, `${BASE_PORT}`) in generated `.jmx` plans.
- **JMeter 5.6 Ready & 417-Safe**: Uses clean JMeter 5.6.3 schema (`HTTPSamplerProxy` + `HeaderManager` + `ResponseAssertion`) and leaves `HTTPSampler.implementation` blank so reverse proxies do not reject POST bodies with `417 Expectation Failed`.
- **Fail-Closed Static Validator (`--validate`)**: Parses output XML and fails non-zero if required JMeter elements are missing or unredacted Bearer/JWT tokens remain.

---

## Build Clean Marketplace ZIP

```bash
python3 scripts/package_skill.py
# Output: dist/har-to-jmx-lite.zip (unpacked and smoke-tested automatically)
```
