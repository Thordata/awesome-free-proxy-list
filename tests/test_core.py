"""Unit tests for pure functions in scripts/update.py and scripts/subscription.py.

Run: pytest tests/ -v
"""

import base64
import sys
from pathlib import Path

import pytest

# Make scripts/ importable.
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import update  # noqa: E402
import subscription  # noqa: E402
from update import Proxy, classify_anonymity, tier_of  # noqa: E402
from geoip_lookup import classify_ip_type  # noqa: E402
from subscription import flag_emoji  # noqa: E402


# ---------- tier_of ----------
class TestTierOf:
    def test_none_is_unknown(self):
        assert tier_of(None) == "unknown"

    def test_fast(self):
        assert tier_of(100) == "fast"
        assert tier_of(499) == "fast"

    def test_medium(self):
        assert tier_of(500) == "medium"
        assert tier_of(1999) == "medium"

    def test_slow(self):
        assert tier_of(2000) == "slow"
        assert tier_of(10000) == "slow"


# ---------- classify_anonymity ----------
class TestClassifyAnonymity:
    def test_none_response_is_unknown(self):
        assert classify_anonymity(None, "1.2.3.4") == "unknown"

    def test_empty_is_unknown(self):
        assert classify_anonymity({}, "1.2.3.4") == "unknown"

    def test_no_headers_key_is_unknown(self):
        assert classify_anonymity({"foo": "bar"}, "1.2.3.4") == "unknown"

    def test_transparent_real_ip_in_xff(self):
        resp = {"headers": {"X-Forwarded-For": "1.2.3.4"}}
        assert classify_anonymity(resp, "1.2.3.4") == "transparent"

    def test_anonymous_via_present_no_real_ip(self):
        resp = {"headers": {"Via": "1.1 proxy"}}
        assert classify_anonymity(resp, "9.9.9.9") == "anonymous"

    def test_anonymous_xff_without_real_ip(self):
        resp = {"headers": {"X-Forwarded-For": "5.5.5.5"}}
        assert classify_anonymity(resp, "9.9.9.9") == "anonymous"

    def test_elite_no_proxy_headers(self):
        resp = {"headers": {"Host": "httpbin.org", "Accept": "*/*"}}
        assert classify_anonymity(resp, "9.9.9.9") == "elite"

    def test_case_insensitive_headers(self):
        resp = {"headers": {"x-forwarded-for": "1.2.3.4"}}
        assert classify_anonymity(resp, "1.2.3.4") == "transparent"


# ---------- flag_emoji ----------
class TestFlagEmoji:
    def test_us(self):
        assert flag_emoji("US") == "🇺🇸"

    def test_case_insensitive(self):
        assert flag_emoji("us") == "🇺🇸"

    def test_unknown_country(self):
        assert flag_emoji("UNKNOWN") == "🏳️"

    def test_empty(self):
        assert flag_emoji("") == "🏳️"

    def test_non_iso(self):
        assert flag_emoji("XX") == "🇽🇽"


# ---------- clash_proxy_name ----------
class TestClashProxyName:
    def test_name_has_flag_type_host_tier(self):
        p = Proxy(type="http", host="1.2.3.4", port=8080, latency_ms=100, country_code="US")
        name = subscription.clash_proxy_name(p, 1)
        assert "🇺🇸" in name
        assert "HTTP" in name
        assert "1.2.3.4:8080" in name
        assert "F" in name  # fast tier initial

    def test_unknown_country_uses_placeholder(self):
        p = Proxy(type="socks5", host="5.6.7.8", port=1080, latency_ms=2000)
        name = subscription.clash_proxy_name(p, 2)
        # Empty country_code falls back to "??"; flag_emoji("??") produces a flag-ish pair.
        assert "SOCKS5" in name
        assert "5.6.7.8:1080" in name


# ---------- _yaml_dump ----------
class TestYamlDump:
    def test_simple_dict(self):
        out = subscription._yaml_dump({"a": 1, "b": "hi"})
        assert "a: 1" in out
        assert "b: hi" in out

    def test_string_with_colon_quoted(self):
        out = subscription._yaml_dump({"k": "http://x:8080"})
        # Should be double-quoted because it contains colons.
        assert '"http://x:8080"' in out

    def test_bool_lowercase(self):
        out = subscription._yaml_dump({"udp": False})
        assert "udp: false" in out

    def test_list_of_strings(self):
        out = subscription._yaml_dump({"rules": ["MATCH,PROXY", "DIRECT"]})
        assert "- MATCH,PROXY" in out or '- "MATCH,PROXY"' in out
        assert "- DIRECT" in out or '- "DIRECT"' in out

    def test_list_of_dicts_block_style(self):
        out = subscription._yaml_dump({
            "proxies": [{"name": "p1", "type": "http", "server": "1.1.1.1", "port": 80}]
        })
        assert "- name: " in out
        assert "type: http" in out
        assert "server: 1.1.1.1" in out
        assert "port: 80" in out

    def test_empty_list(self):
        out = subscription._yaml_dump({"items": []})
        assert "items: []" in out

    def test_none_value(self):
        out = subscription._yaml_dump({"k": None})
        assert "k:" in out and "k: " not in out

    def test_produces_parseable_yaml(self):
        # Round-trip: the dumped YAML must parse back to the same structure.
        try:
            import yaml  # PyYAML
        except ImportError:
            pytest.skip("PyYAML not installed")
        obj = {
            "mixed-port": 7890,
            "proxies": [
                {"name": "🚀 P", "type": "http", "server": "1.2.3.4", "port": 8080, "udp": False},
                {"name": "n2", "type": "socks5", "server": "5.6.7.8", "port": 1080, "udp": True},
            ],
            "rules": ["MATCH,PROXY", "GEOIP,CN,DIRECT"],
            "allow-lan": False,
        }
        out = subscription._yaml_dump(obj)
        parsed = yaml.safe_load(out)
        assert parsed["mixed-port"] == 7890
        assert len(parsed["proxies"]) == 2
        assert parsed["proxies"][0]["server"] == "1.2.3.4"
        assert parsed["proxies"][1]["udp"] is True
        assert parsed["rules"] == ["MATCH,PROXY", "GEOIP,CN,DIRECT"]


# ---------- build_links / build_v2ray_sub ----------
class TestSubscriptionBuilders:
    def _proxy(self, **kw):
        defaults = {"type": "http", "host": "1.2.3.4", "port": 8080, "latency_ms": 100,
                    "country": "United States", "country_code": "US", "source": "test"}
        defaults.update(kw)
        return Proxy(**defaults)

    def test_build_links_http(self):
        proxies = [self._proxy(host=f"1.2.3.{i}") for i in range(3)]
        out = subscription.build_links(proxies, "http")
        assert "http://1.2.3.0:8080" in out
        assert "http://1.2.3.1:8080" in out
        assert "http://1.2.3.2:8080" in out

    def test_build_links_socks5(self):
        proxies = [self._proxy(type="socks5", host="5.6.7.0", port=1080)]
        out = subscription.build_links(proxies, "socks5")
        assert "socks5://5.6.7.0:1080" in out

    def test_build_links_dedup(self):
        proxies = [self._proxy(), self._proxy()]  # same hostport
        out = subscription.build_links(proxies)
        assert out.count("1.2.3.4:8080") == 1

    def test_build_v2ray_base64_decodes(self):
        proxies = [self._proxy(type="http", host="1.2.3.4", port=8080),
                   self._proxy(type="socks5", host="5.6.7.8", port=1080)]
        b64 = subscription.build_v2ray_sub(proxies)
        decoded = base64.b64decode(b64).decode("utf-8")
        assert "http://1.2.3.4:8080" in decoded
        assert "socks5://5.6.7.8:1080" in decoded

    def test_build_v2ray_empty(self):
        b64 = subscription.build_v2ray_sub([])
        decoded = base64.b64decode(b64).decode("utf-8")
        assert decoded == ""


# ---------- classify_ip_type (ASN-based datacenter/residential inference) ----------
class TestClassifyIpType:
    def test_empty_is_unknown(self):
        assert classify_ip_type("") == "unknown"

    def test_datacenter_cloud_providers(self):
        for org in ["Amazon.com Inc.", "Google LLC", "Microsoft Corporation",
                    "DigitalOcean LLC", "Cloudflare, Inc.", "OVH SAS", "Hetzner Online GmbH",
                    "Alibaba (US) Technology Co., Ltd.", "Tencent Building", "Huawei Cloud"]:
            assert classify_ip_type(org) == "datacenter", f"{org!r} should be datacenter"

    def test_residential_isps(self):
        for org in ["Comcast Cable Communications", "AT&T Services Inc.",
                    "China Telecom Group", "Vodafone Group", "Verizon Business"]:
            assert classify_ip_type(org) == "residential", f"{org!r} should be residential"

    def test_unknown_for_unlisted_org(self):
        assert classify_ip_type("Some Random Small ISP Co.") == "unknown"

    def test_case_insensitive(self):
        assert classify_ip_type("AMAZON.COM INC.") == "datacenter"
        assert classify_ip_type("comcast cable") == "residential"
