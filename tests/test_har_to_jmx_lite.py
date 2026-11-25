import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from scripts.har_to_jmx_lite import (
    build_jmx_xml,
    main,
    normalize_path,
    parse_har,
    render_api_doc_markdown,
    summarize_endpoints,
    validate_jmx_file,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_HAR = REPO_ROOT / "examples" / "sample_shop_api.har"


class TestHarToJmxLite(unittest.TestCase):
    def test_parse_har_filters_static_and_options(self):
        entries = parse_har(SAMPLE_HAR)
        self.assertEqual(len(entries), 3)
        methods_paths = [(e.method, e.normalized_path) for e in entries]
        self.assertEqual(
            methods_paths,
            [
                ("GET", "/api/v1/products"),
                ("POST", "/api/v1/orders"),
                ("GET", "/api/v1/orders/{id}"),
            ],
        )

    def test_normalize_path_handles_ids_and_uuids(self):
        self.assertEqual(normalize_path("/api/orders/12345/items/9"), "/api/orders/{id}/items/{id}")
        self.assertEqual(
            normalize_path("/api/users/550e8400-e29b-41d4-a716-446655440000/profile"),
            "/api/users/{uuid}/profile",
        )

    def test_api_doc_redacts_sensitive_headers(self):
        entries = parse_har(SAMPLE_HAR)
        md = render_api_doc_markdown(entries, title="Demo API", lang="en")
        self.assertIn("Bearer <REDACTED>", md)
        self.assertNotIn("placeholder_demo_token_do_not_use_in_prod", md)
        self.assertNotIn("placeholder_cookie_value", md)

    def test_generate_and_validate_clean_jmx(self):
        entries = parse_har(SAMPLE_HAR)
        xml_text = build_jmx_xml(entries, threads=10, ramp_up=5, loops=2)
        self.assertNotIn("placeholder_demo_token_do_not_use_in_prod", xml_text)
        self.assertIn("Bearer ${AUTH_TOKEN}", xml_text)
        self.assertIn("${BASE_HOST}", xml_text)

        root = ET.fromstring(xml_text)
        samplers = root.findall(".//HTTPSamplerProxy")
        self.assertEqual(len(samplers), 3)

        with tempfile.TemporaryDirectory() as tmp:
            jmx_path = Path(tmp) / "demo.jmx"
            jmx_path.write_text(xml_text, encoding="utf-8")
            ok, issues = validate_jmx_file(jmx_path)
            self.assertTrue(ok, f"Expected valid JMX, got issues: {issues}")

    def test_validate_catches_leaked_bearer_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            jmx_path = Path(tmp) / "leaked.jmx"
            entries = parse_har(SAMPLE_HAR)
            xml_text = build_jmx_xml(entries).replace(
                "Bearer ${AUTH_TOKEN}",
                "Bearer abcdef1234567890abcdef1234567890",
            )
            jmx_path.write_text(xml_text, encoding="utf-8")
            ok, issues = validate_jmx_file(jmx_path)
            self.assertFalse(ok)
            self.assertTrue(any("Bearer/JWT" in msg for msg in issues))

    def test_cli_scan_doc_and_jmx_end_to_end(self):
        self.assertEqual(main(["scan", str(SAMPLE_HAR), "--format", "json"]), 0)
        with tempfile.TemporaryDirectory() as tmp:
            doc_out = Path(tmp) / "api.md"
            jmx_out = Path(tmp) / "flow.jmx"
            self.assertEqual(main(["doc", str(SAMPLE_HAR), "-o", str(doc_out), "--lang", "zh"]), 0)
            self.assertTrue(doc_out.is_file())
            self.assertIn("已脱敏", doc_out.read_text(encoding="utf-8"))

            self.assertEqual(main(["jmx", str(SAMPLE_HAR), "-o", str(jmx_out), "--validate"]), 0)
            self.assertTrue(jmx_out.is_file())
            self.assertEqual(main(["validate", str(jmx_out)]), 0)

    def test_summarize_endpoints_counts_and_averages(self):
        entries = parse_har(SAMPLE_HAR)
        summary = summarize_endpoints(entries)
        self.assertEqual(len(summary), 3)
        self.assertEqual(summary[0]["count"], 1)


if __name__ == "__main__":
    unittest.main()
