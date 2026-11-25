#!/usr/bin/env python3
"""Zero-dependency HAR to Markdown API docs & JMeter 5.6 .jmx generator.

Subcommands:
- scan:     Filter static noise and list unique API endpoints from a .har file
- doc:      Generate credential-redacted Markdown API documentation (en/zh)
- jmx:      Generate a parameterized JMeter 5.6.x .jmx test plan (with optional --validate)
- validate: Statically inspect an existing .jmx file for XML validity & leaked credentials
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import parse_qsl, urlparse

STATIC_EXTENSIONS = (
    ".js", ".mjs", ".css", ".map", ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".svg", ".ico", ".woff", ".woff2", ".ttf", ".eot", ".otf", ".mp4", ".mp3",
    ".wav", ".pdf", ".zip", ".gz", ".br",
)

STATIC_MIME_PREFIXES = (
    "image/", "font/", "audio/", "video/", "text/css", "text/javascript",
    "application/javascript", "application/x-javascript",
)

SENSITIVE_HEADER_NAMES = {
    "authorization", "cookie", "set-cookie", "x-api-key", "api-key",
    "x-auth-token", "x-access-token", "proxy-authorization",
}

SKIP_REPLAY_HEADERS = {
    "host", "content-length", "connection", "accept-encoding", "keep-alive",
    "transfer-encoding", "upgrade", "sec-ch-ua", "sec-ch-ua-mobile",
    "sec-ch-ua-platform", "sec-fetch-dest", "sec-fetch-mode", "sec-fetch-site",
    "sec-fetch-user", "user-agent", "cookie", "x-nonce", "x-timestamp",
}

JWT_OR_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}")
RAW_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")
NUMERIC_SEGMENT_RE = re.compile(r"/\d+(?=/|$)")
UUID_SEGMENT_RE = re.compile(
    r"/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?=/|$)"
)


@dataclass
class ApiEntry:
    method: str
    url: str
    scheme: str
    host: str
    port: str
    path: str
    normalized_path: str
    query_params: List[Tuple[str, str]]
    headers: Dict[str, str]
    request_mime: str
    request_body: str
    status: int
    response_mime: str
    response_body: str
    time_ms: float = 0.0
    tags: List[str] = field(default_factory=list)


def normalize_path(path: str) -> str:
    """Replace numeric IDs and UUID segments with placeholders for deduplication."""
    clean = UUID_SEGMENT_RE.sub("/{uuid}", path or "/")
    clean = NUMERIC_SEGMENT_RE.sub("/{id}", clean)
    return clean


def _is_static_entry(url: str, method: str, response_mime: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return True
    if method.upper() == "OPTIONS":
        return True
    low_path = (parsed.path or "").lower()
    if any(low_path.endswith(ext) for ext in STATIC_EXTENSIONS):
        return True
    low_mime = (response_mime or "").lower().split(";")[0].strip()
    if any(low_mime.startswith(prefix) for prefix in STATIC_MIME_PREFIXES):
        return True
    return False


def _header_list_to_dict(headers: Sequence[dict]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for item in headers or []:
        name = str(item.get("name", "")).strip()
        if not name or name.startswith(":"):
            continue
        result[name] = str(item.get("value", ""))
    return result


def redact_header_value(name: str, value: str) -> str:
    low = name.lower()
    if low in SENSITIVE_HEADER_NAMES:
        if low == "authorization" and value.lower().startswith("bearer "):
            return "Bearer <REDACTED>"
        return "<REDACTED>"
    return value


def parse_har(
    har_path: Path,
    *,
    allow_hosts: Optional[Sequence[str]] = None,
    include_methods: Optional[Sequence[str]] = None,
) -> List[ApiEntry]:
    """Load and filter API entries from a standard HAR 1.2 JSON file."""
    raw = json.loads(har_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "log" not in raw or not isinstance(raw["log"], dict):
        raise ValueError("Invalid HAR structure: missing top-level 'log' object.")

    entries_raw = raw["log"].get("entries", [])
    if not isinstance(entries_raw, list):
        raise ValueError("Invalid HAR structure: 'log.entries' must be a list.")

    host_filter = {h.strip().lower() for h in (allow_hosts or []) if h.strip()}
    method_filter = {m.strip().upper() for m in (include_methods or []) if m.strip()}

    parsed_entries: List[ApiEntry] = []
    for item in entries_raw:
        req = item.get("request") or {}
        resp = item.get("response") or {}
        method = str(req.get("method", "GET")).upper()
        url = str(req.get("url", "")).strip()
        if not url:
            continue

        content = resp.get("content") or {}
        resp_mime = str(content.get("mimeType", ""))
        if _is_static_entry(url, method, resp_mime):
            continue

        u = urlparse(url)
        host = (u.hostname or "").lower()
        if host_filter and host not in host_filter:
            continue
        if method_filter and method not in method_filter:
            continue

        port = str(u.port) if u.port else ""
        path = u.path or "/"
        query_params = parse_qsl(u.query, keep_blank_values=True)
        headers = _header_list_to_dict(req.get("headers") or [])
        post_data = req.get("postData") or {}
        req_mime = str(post_data.get("mimeType", ""))
        req_body = str(post_data.get("text", "") or "")
        resp_body = str(content.get("text", "") or "")
        status = int(resp.get("status") or 0)
        time_ms = float(item.get("time") or 0.0)

        parsed_entries.append(
            ApiEntry(
                method=method,
                url=url,
                scheme=u.scheme or "https",
                host=host,
                port=port,
                path=path,
                normalized_path=normalize_path(path),
                query_params=query_params,
                headers=headers,
                request_mime=req_mime,
                request_body=req_body,
                status=status,
                response_mime=resp_mime,
                response_body=resp_body,
                time_ms=time_ms,
            )
        )

    return parsed_entries


def summarize_endpoints(entries: Sequence[ApiEntry]) -> List[dict]:
    """Group captured requests by (host, method, normalized_path)."""
    grouped: Dict[Tuple[str, str, str], dict] = {}
    for e in entries:
        key = (e.host, e.method, e.normalized_path)
        if key not in grouped:
            grouped[key] = {
                "host": e.host,
                "method": e.method,
                "path": e.normalized_path,
                "count": 0,
                "statuses": [],
                "avg_ms": 0.0,
                "_total_ms": 0.0,
            }
        rec = grouped[key]
        rec["count"] += 1
        if e.status not in rec["statuses"]:
            rec["statuses"].append(e.status)
        rec["_total_ms"] += e.time_ms

    out: List[dict] = []
    for rec in grouped.values():
        rec["avg_ms"] = round(rec["_total_ms"] / rec["count"], 1) if rec["count"] else 0.0
        del rec["_total_ms"]
        out.append(rec)
    return out


def render_scan_markdown(summary: Sequence[dict], *, lang: str = "en") -> str:
    if lang == "zh":
        lines = [
            f"## HAR 接口扫描清单（共 {len(summary)} 个唯一接口）",
            "",
            "| 方法 | 主机 | 规范化路径 | 次数 | 状态码 | 平均耗时(ms) |",
            "| :--- | :--- | :--- | ---: | :--- | ---: |",
        ]
    else:
        lines = [
            f"## HAR Endpoint Inventory ({len(summary)} unique endpoints)",
            "",
            "| Method | Host | Normalized Path | Count | Statuses | Avg (ms) |",
            "| :--- | :--- | :--- | ---: | :--- | ---: |",
        ]

    for row in summary:
        statuses = ", ".join(str(s) for s in row["statuses"])
        lines.append(
            f"| `{row['method']}` | `{row['host']}` | `{row['path']}` | {row['count']} | {statuses} | {row['avg_ms']} |"
        )
    return "\n".join(lines)


def _format_json_snippet(raw_text: str, max_chars: int = 800) -> str:
    text = raw_text.strip()
    if not text:
        return ""
    try:
        obj = json.loads(text)
        pretty = json.dumps(obj, ensure_ascii=False, indent=2)
    except (json.JSONDecodeError, ValueError):
        pretty = text
    if len(pretty) > max_chars:
        return pretty[:max_chars] + "\n... (truncated)"
    return pretty


def render_api_doc_markdown(entries: Sequence[ApiEntry], *, title: str, lang: str = "en") -> str:
    """Render credential-redacted Markdown API documentation from filtered HAR entries."""
    seen: set[Tuple[str, str, str]] = set()
    unique_entries: List[ApiEntry] = []
    for e in entries:
        key = (e.host, e.method, e.normalized_path)
        if key not in seen:
            seen.add(key)
            unique_entries.append(e)

    if lang == "zh":
        lines = [
            f"# {title}",
            "",
            f"> 共提取 **{len(unique_entries)}** 个去重 API 接口（敏感鉴权请求头已自动脱敏）。",
            "",
        ]
    else:
        lines = [
            f"# {title}",
            "",
            f"> Extracted **{len(unique_entries)}** deduplicated API endpoints (sensitive auth headers automatically redacted).",
            "",
        ]

    for idx, entry in enumerate(unique_entries, start=1):
        lines.append(f"## {idx}. `{entry.method} {entry.normalized_path}`")
        lines.append("")
        if lang == "zh":
            lines.append(f"- **示例 URL**：`{entry.scheme}://{entry.host}{(':' + entry.port) if entry.port else ''}{entry.path}`")
            lines.append(f"- **响应状态码**：`{entry.status}`")
        else:
            lines.append(f"- **Sample URL**: `{entry.scheme}://{entry.host}{(':' + entry.port) if entry.port else ''}{entry.path}`")
            lines.append(f"- **Captured Status**: `{entry.status}`")

        if entry.query_params:
            lines.append("")
            lines.append("### Query Parameters" if lang == "en" else "### 查询参数")
            lines.append("| Key | Sample Value |")
            lines.append("| :--- | :--- |")
            for k, v in entry.query_params:
                lines.append(f"| `{k}` | `{v}` |")

        kept_headers = [
            (k, redact_header_value(k, v))
            for k, v in entry.headers.items()
            if k.lower() not in SKIP_REPLAY_HEADERS or k.lower() == "authorization"
        ]
        if kept_headers:
            lines.append("")
            lines.append("### Headers" if lang == "en" else "### 请求头（已脱敏）")
            lines.append("| Header | Value |")
            lines.append("| :--- | :--- |")
            for k, v in kept_headers[:12]:
                lines.append(f"| `{k}` | `{v}` |")

        req_snippet = _format_json_snippet(entry.request_body)
        if req_snippet:
            lines.append("")
            lines.append("### Request Body" if lang == "en" else "### 请求体示例")
            lines.append("```json")
            lines.append(req_snippet)
            lines.append("```")

        resp_snippet = _format_json_snippet(entry.response_body)
        if resp_snippet:
            lines.append("")
            lines.append("### Response Sample" if lang == "en" else "### 响应示例")
            lines.append("```json")
            lines.append(resp_snippet)
            lines.append("```")

        lines.append("")

    return "\n".join(lines)


def _add_prop(parent: ET.Element, tag: str, name: str, text: Optional[str] = None) -> ET.Element:
    elem = ET.SubElement(parent, tag, {"name": name})
    if text is not None:
        elem.text = text
    return elem


def _append_udv(parent_hash: ET.Element, variables: Sequence[Tuple[str, str]]) -> None:
    args = ET.SubElement(
        parent_hash,
        "Arguments",
        {"guiclass": "ArgumentsPanel", "testclass": "Arguments", "testname": "User Defined Variables", "enabled": "true"},
    )
    coll = ET.SubElement(args, "collectionProp", {"name": "Arguments.arguments"})
    for key, val in variables:
        el = ET.SubElement(coll, "elementProp", {"name": key, "elementType": "Argument"})
        _add_prop(el, "stringProp", "Argument.name", key)
        _add_prop(el, "stringProp", "Argument.value", val)
        _add_prop(el, "stringProp", "Argument.metadata", "=")
    ET.SubElement(parent_hash, "hashTree")


def _append_header_manager(parent_hash: ET.Element, headers: Dict[str, str]) -> None:
    mgr = ET.SubElement(
        parent_hash,
        "HeaderManager",
        {"guiclass": "HeaderPanel", "testclass": "HeaderManager", "testname": "HTTP Header Manager", "enabled": "true"},
    )
    coll = ET.SubElement(mgr, "collectionProp", {"name": "HeaderManager.headers"})
    for name, val in headers.items():
        low = name.lower()
        if low in SKIP_REPLAY_HEADERS:
            continue
        if low == "authorization":
            out_val = "Bearer ${AUTH_TOKEN}" if val.lower().startswith("bearer ") else "${AUTH_TOKEN}"
        elif low in SENSITIVE_HEADER_NAMES:
            var_name = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")
            out_val = f"${{{var_name}}}"
        else:
            out_val = val
        el = ET.SubElement(coll, "elementProp", {"name": "", "elementType": "Header"})
        _add_prop(el, "stringProp", "Header.name", name)
        _add_prop(el, "stringProp", "Header.value", out_val)
    ET.SubElement(parent_hash, "hashTree")


def _append_status_assertion(parent_hash: ET.Element, expected_status: int) -> None:
    if expected_status < 200 or expected_status >= 400:
        return
    ra = ET.SubElement(
        parent_hash,
        "ResponseAssertion",
        {"guiclass": "AssertionGui", "testclass": "ResponseAssertion", "testname": f"Assert HTTP {expected_status}", "enabled": "true"},
    )
    coll = ET.SubElement(ra, "collectionProp", {"name": "Asserion.test_strings"})
    _add_prop(coll, "stringProp", str(expected_status), str(expected_status))
    _add_prop(ra, "stringProp", "Assertion.custom_message", "")
    _add_prop(ra, "stringProp", "Assertion.test_field", "Assertion.response_code")
    _add_prop(ra, "boolProp", "Assertion.assume_success", "false")
    _add_prop(ra, "intProp", "Assertion.test_type", "8")
    ET.SubElement(parent_hash, "hashTree")


def build_jmx_xml(
    entries: Sequence[ApiEntry],
    *,
    plan_name: str = "HAR Generated API Test Plan",
    threads: int = 1,
    ramp_up: int = 1,
    loops: int = 1,
    deduplicate: bool = True,
) -> str:
    """Build a clean, parameterized JMeter 5.6.x .jmx XML document."""
    if not entries:
        raise ValueError("No API entries available after filtering; refusing to generate an empty JMX.")

    selected: List[ApiEntry] = []
    if deduplicate:
        seen: set[Tuple[str, str, str]] = set()
        for e in entries:
            key = (e.host, e.method, e.normalized_path)
            if key not in seen:
                seen.add(key)
                selected.append(e)
    else:
        selected = list(entries)

    first = selected[0]
    root = ET.Element("jmeterTestPlan", {"version": "1.2", "properties": "5.0", "jmeter": "5.6.3"})
    outer_hash = ET.SubElement(root, "hashTree")

    test_plan = ET.SubElement(
        outer_hash,
        "TestPlan",
        {"guiclass": "TestPlanGui", "testclass": "TestPlan", "testname": plan_name, "enabled": "true"},
    )
    _add_prop(test_plan, "stringProp", "TestPlan.comments", "Generated by har-to-jmx-lite (zero-dependency stdlib)")
    _add_prop(test_plan, "boolProp", "TestPlan.functional_mode", "false")
    _add_prop(test_plan, "boolProp", "TestPlan.tearDown_on_shutdown", "true")
    _add_prop(test_plan, "boolProp", "TestPlan.serialize_threadgroups", "false")
    el_udv = ET.SubElement(
        test_plan,
        "elementProp",
        {"name": "TestPlan.user_defined_variables", "elementType": "Arguments", "guiclass": "ArgumentsPanel", "testclass": "Arguments", "testname": "User Defined Variables", "enabled": "true"},
    )
    ET.SubElement(el_udv, "collectionProp", {"name": "Arguments.arguments"})

    plan_hash = ET.SubElement(outer_hash, "hashTree")
    _append_udv(
        plan_hash,
        [
            ("PROTOCOL", first.scheme),
            ("BASE_HOST", first.host),
            ("BASE_PORT", first.port),
            ("AUTH_TOKEN", "${__P(AUTH_TOKEN,replace_with_staging_token)}"),
        ],
    )

    tg = ET.SubElement(
        plan_hash,
        "ThreadGroup",
        {"guiclass": "ThreadGroupGui", "testclass": "ThreadGroup", "testname": "API Workflow Thread Group", "enabled": "true"},
    )
    _add_prop(tg, "stringProp", "ThreadGroup.on_sample_error", "continue")
    loop_ctrl = ET.SubElement(
        tg,
        "elementProp",
        {"name": "ThreadGroup.main_controller", "elementType": "LoopController", "guiclass": "LoopControlPanel", "testclass": "LoopController", "testname": "Loop Controller", "enabled": "true"},
    )
    _add_prop(loop_ctrl, "boolProp", "LoopController.continue_forever", "false")
    _add_prop(loop_ctrl, "stringProp", "LoopController.loops", str(loops))
    _add_prop(tg, "stringProp", "ThreadGroup.num_threads", str(threads))
    _add_prop(tg, "stringProp", "ThreadGroup.ramp_time", str(ramp_up))
    _add_prop(tg, "boolProp", "ThreadGroup.scheduler", "false")

    tg_hash = ET.SubElement(plan_hash, "hashTree")

    for idx, entry in enumerate(selected, start=1):
        sampler_name = f"{idx:02d} {entry.method} {entry.normalized_path}"
        sampler = ET.SubElement(
            tg_hash,
            "HTTPSamplerProxy",
            {"guiclass": "HttpTestSampleGui", "testclass": "HTTPSamplerProxy", "testname": sampler_name, "enabled": "true"},
        )

        use_raw_body = bool(entry.request_body) and entry.method in ("POST", "PUT", "PATCH", "DELETE")
        _add_prop(sampler, "boolProp", "HTTPSampler.postBodyRaw", "true" if use_raw_body else "false")
        args_el = ET.SubElement(
            sampler,
            "elementProp",
            {"name": "HTTPsampler.Arguments", "elementType": "Arguments"},
        )
        args_coll = ET.SubElement(args_el, "collectionProp", {"name": "Arguments.arguments"})

        if use_raw_body:
            arg = ET.SubElement(args_coll, "elementProp", {"name": "", "elementType": "HTTPArgument"})
            _add_prop(arg, "boolProp", "HTTPArgument.always_encode", "false")
            _add_prop(arg, "stringProp", "Argument.value", entry.request_body)
            _add_prop(arg, "stringProp", "Argument.metadata", "=")
        else:
            for qk, qv in entry.query_params:
                arg = ET.SubElement(args_coll, "elementProp", {"name": qk, "elementType": "HTTPArgument"})
                _add_prop(arg, "boolProp", "HTTPArgument.always_encode", "true")
                _add_prop(arg, "stringProp", "Argument.name", qk)
                _add_prop(arg, "stringProp", "Argument.value", qv)
                _add_prop(arg, "stringProp", "Argument.metadata", "=")

        same_host = entry.host == first.host and entry.port == first.port
        _add_prop(sampler, "stringProp", "HTTPSampler.domain", "${BASE_HOST}" if same_host else entry.host)
        _add_prop(sampler, "stringProp", "HTTPSampler.port", "${BASE_PORT}" if same_host else entry.port)
        _add_prop(sampler, "stringProp", "HTTPSampler.protocol", "${PROTOCOL}" if same_host else entry.scheme)
        _add_prop(sampler, "stringProp", "HTTPSampler.path", entry.path)
        _add_prop(sampler, "stringProp", "HTTPSampler.method", entry.method)
        _add_prop(sampler, "boolProp", "HTTPSampler.follow_redirects", "true")
        _add_prop(sampler, "boolProp", "HTTPSampler.use_keepalive", "true")
        # Leave implementation empty so JMeter uses default Java client (avoids 417 Expect: 100-continue issues)
        _add_prop(sampler, "stringProp", "HTTPSampler.implementation", "")

        sampler_hash = ET.SubElement(tg_hash, "hashTree")
        if entry.headers:
            _append_header_manager(sampler_hash, entry.headers)
        _append_status_assertion(sampler_hash, entry.status)

    if hasattr(ET, "indent"):
        ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def validate_jmx_file(jmx_path: Path) -> Tuple[bool, List[str]]:
    """Statically validate JMeter XML structure and check for leaked credentials."""
    issues: List[str] = []
    text = jmx_path.read_text(encoding="utf-8", errors="replace")

    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        return False, [f"XML parse error: {exc}"]

    if root.tag != "jmeterTestPlan":
        issues.append(f"Unexpected root element '{root.tag}'; expected 'jmeterTestPlan'.")

    if root.find(".//TestPlan") is None:
        issues.append("Missing <TestPlan> element.")
    if root.find(".//ThreadGroup") is None:
        issues.append("Missing <ThreadGroup> element.")
    samplers = root.findall(".//HTTPSamplerProxy")
    if not samplers:
        issues.append("No <HTTPSamplerProxy> samplers found.")

    if JWT_OR_BEARER_RE.search(text) or RAW_JWT_RE.search(text):
        issues.append("Possible unredacted Bearer/JWT token detected inside generated .jmx; parameterize via ${AUTH_TOKEN}.")

    return len(issues) == 0, issues


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Zero-dependency HAR to API Markdown & JMeter 5.6 .jmx converter.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="Scan a HAR file and print unique API endpoints")
    p_scan.add_argument("har", help="Input .har file path")
    p_scan.add_argument("--allow-host", action="append", default=[], help="Restrict to specific host(s)")
    p_scan.add_argument("--format", choices=("markdown", "json"), default="markdown")
    p_scan.add_argument("--lang", choices=("en", "zh"), default="en")

    p_doc = sub.add_parser("doc", help="Generate credential-redacted Markdown API documentation")
    p_doc.add_argument("har", help="Input .har file path")
    p_doc.add_argument("-o", "--output", help="Output Markdown path (prints to stdout if omitted)")
    p_doc.add_argument("--title", default="Captured API Documentation")
    p_doc.add_argument("--allow-host", action="append", default=[])
    p_doc.add_argument("--lang", choices=("en", "zh"), default="en")

    p_jmx = sub.add_parser("jmx", help="Generate a parameterized JMeter 5.6 .jmx test plan")
    p_jmx.add_argument("har", help="Input .har file path")
    p_jmx.add_argument("-o", "--output", required=True, help="Output .jmx file path")
    p_jmx.add_argument("--plan-name", default="HAR Generated API Test Plan")
    p_jmx.add_argument("--allow-host", action="append", default=[])
    p_jmx.add_argument("--threads", type=int, default=1)
    p_jmx.add_argument("--ramp-up", type=int, default=1)
    p_jmx.add_argument("--loops", type=int, default=1)
    p_jmx.add_argument("--keep-duplicates", action="store_true", help="Keep duplicate endpoints in recorded order")
    p_jmx.add_argument("--validate", action="store_true", help="Validate generated .jmx immediately")

    p_val = sub.add_parser("validate", help="Statically validate an existing .jmx file")
    p_val.add_argument("jmx", help="Path to .jmx file")

    args = parser.parse_args(argv)

    if args.command == "validate":
        jmx_path = Path(args.jmx)
        if not jmx_path.is_file():
            print(f"Error: file not found: {jmx_path}", file=sys.stderr)
            return 2
        ok, issues = validate_jmx_file(jmx_path)
        if ok:
            print(f"PASS: {jmx_path.name} is valid JMeter XML with zero detected credential leaks.")
            return 0
        print(f"FAIL: {jmx_path.name} failed validation:", file=sys.stderr)
        for item in issues:
            print(f"  - {item}", file=sys.stderr)
        return 1

    har_path = Path(args.har)
    if not har_path.is_file():
        print(f"Error: HAR file not found: {har_path}", file=sys.stderr)
        return 2

    try:
        entries = parse_har(har_path, allow_hosts=args.allow_host)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"Error parsing HAR: {exc}", file=sys.stderr)
        return 2

    if not entries:
        print("Error: no API requests remained after filtering static assets and host filters.", file=sys.stderr)
        return 1

    if args.command == "scan":
        summary = summarize_endpoints(entries)
        if args.format == "json":
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            print(render_scan_markdown(summary, lang=args.lang))
        return 0

    if args.command == "doc":
        md = render_api_doc_markdown(entries, title=args.title, lang=args.lang)
        if args.output:
            out = Path(args.output)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(md + "\n", encoding="utf-8")
            print(f"OK: wrote API documentation ({len(entries)} captured calls) -> {out}")
        else:
            print(md)
        return 0

    if args.command == "jmx":
        xml_text = build_jmx_xml(
            entries,
            plan_name=args.plan_name,
            threads=args.threads,
            ramp_up=args.ramp_up,
            loops=args.loops,
            deduplicate=not args.keep_duplicates,
        )
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(xml_text, encoding="utf-8")
        if args.validate:
            ok, issues = validate_jmx_file(out)
            if not ok:
                for item in issues:
                    print(f"Validation failed: {item}", file=sys.stderr)
                return 1
        print(f"OK: generated JMeter 5.6 test plan ({len(entries)} filtered calls) -> {out}")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
