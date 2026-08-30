"""
Deep-dive diagnostics for a single proxy.

Given an ip:port (and an optional --type), reports:
  - HTTP connectivity + latency
  - HTTPS (CONNECT) connectivity + latency
  - Exit IP and whether it differs from your real IP (anonymity hint)
  - GeoIP country of the exit IP (if a mmdb is available)
  - A one-line verdict

Usage:
    python scripts/check.py 1.2.3.4:8080
    python scripts/check.py 1.2.3.4:1080 --type socks5
    python scripts/check.py 1.2.3.4:8080 --json
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import aiohttp
from aiohttp_socks import ProxyConnector

# Allow importing geoip_lookup when running from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from geoip_lookup import GeoIP  # noqa: E402

IP_URL = "http://api.ipify.org?format=json"
HTTPS_URL = "https://api.ipify.org?format=json"
TIMEOUT_SEC = 12.0


def parse_target(target: str) -> tuple[str, int]:
    if ":" not in target:
        raise SystemExit(f"Expected ip:port, got: {target!r}")
    host, port_s = target.rsplit(":", 1)
    try:
        port = int(port_s)
    except ValueError:
        raise SystemExit(f"Invalid port: {port_s!r}")
    if not (1 <= port <= 65535):
        raise SystemExit(f"Port out of range: {port}")
    return host, port


def build_url(host: str, port: int, ptype: str) -> str:
    if ptype in ("http", "https"):
        return f"http://{host}:{port}"
    if ptype == "socks4":
        return f"socks4://{host}:{port}"
    return f"socks5://{host}:{port}"


async def fetch_via(session: aiohttp.ClientSession, url: str, *, proxy_url: str | None = None) -> tuple[bool, float | None, str | None, str | None]:
    """GET url through the session. Returns (ok, latency_ms, body_text, error)."""
    start = time.perf_counter()
    try:
        async with session.get(url, proxy=proxy_url) as resp:
            if resp.status >= 400:
                return False, None, None, f"http {resp.status}"
            text = await resp.text()
            return True, (time.perf_counter() - start) * 1000, text, None
    except Exception as e:
        return False, None, None, type(e).__name__


async def check(host: str, port: int, ptype: str, geoip: GeoIP) -> dict:
    url = build_url(host, port, ptype)
    is_socks = ptype in ("socks4", "socks5")
    timeout = aiohttp.ClientTimeout(total=TIMEOUT_SEC)

    # One session for direct requests; one for proxied (socks uses a connector).
    direct_session = aiohttp.ClientSession(timeout=timeout, trust_env=True)
    if is_socks:
        proxied_session = aiohttp.ClientSession(
            timeout=timeout,
            connector=ProxyConnector.from_url(url, rdns=True),
            trust_env=True,
        )
        proxy_arg = None  # connector handles routing
    else:
        proxied_session = aiohttp.ClientSession(timeout=timeout, trust_env=True)
        proxy_arg = url

    try:
        # Direct: learn our own IP (best effort).
        _ok, _ms, direct_body, _err = await fetch_via(direct_session, IP_URL)
        my_ip = None
        if direct_body:
            try:
                my_ip = json.loads(direct_body).get("ip")
            except Exception:
                my_ip = None

        # HTTP through the proxy.
        http_ok, http_ms, http_body, http_err = await fetch_via(proxied_session, IP_URL, proxy_url=proxy_arg)
        # HTTPS through the proxy (tests CONNECT capability).
        https_ok, https_ms, https_body, https_err = await fetch_via(proxied_session, HTTPS_URL, proxy_url=proxy_arg)
    finally:
        await direct_session.close()
        await proxied_session.close()

    exit_ip = None
    for body in (http_body, https_body):
        if body:
            try:
                exit_ip = json.loads(body).get("ip")
                if exit_ip:
                    break
            except Exception:
                pass

    country, country_code = geoip.lookup(exit_ip) if exit_ip else ("", "")
    anonymous = bool(my_ip and exit_ip and my_ip != exit_ip)

    verdict = "unusable"
    if https_ok:
        verdict = "excellent (HTTP + HTTPS)"
    elif http_ok:
        verdict = "limited (HTTP only, no HTTPS/CONNECT)"

    return {
        "proxy": f"{host}:{port}", "type": ptype, "url": url,
        "http": {"ok": http_ok, "latency_ms": round(http_ms, 1) if http_ms else None, "error": http_err},
        "https": {"ok": https_ok, "latency_ms": round(https_ms, 1) if https_ms else None, "error": https_err},
        "your_ip": my_ip, "exit_ip": exit_ip,
        "country": country, "country_code": country_code,
        "anonymous": anonymous, "verdict": verdict,
    }


def print_report(r: dict) -> None:
    print(f"\n  Proxy:   {r['proxy']}  ({r['type']})")
    print(f"  URL:     {r['url']}")
    print(f"  HTTP:    {'✅ ' + str(r['http']['latency_ms']) + 'ms' if r['http']['ok'] else '❌ ' + (r['http']['error'] or 'failed')}")
    print(f"  HTTPS:   {'✅ ' + str(r['https']['latency_ms']) + 'ms' if r['https']['ok'] else '❌ ' + (r['https']['error'] or 'failed')}")
    print(f"  Your IP: {r['your_ip'] or 'unknown'}")
    print(f"  Exit IP: {r['exit_ip'] or 'unknown'}"
          + (f"   🇺 {r['country']} ({r['country_code']})" if r['country_code'] else ""))
    anon = "🟢 yes" if r['anonymous'] else ("🔴 no" if r['exit_ip'] else "⚪ unknown")
    print(f"  Anonymous (exit ≠ your IP): {anon}")
    print(f"  Verdict: {r['verdict']}\n")


def main() -> None:
    # Windows consoles default to GBK; force UTF-8 so emoji + CJK render correctly.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Deep-dive diagnostics for a single proxy.")
    parser.add_argument("target", help="ip:port of the proxy to check.")
    parser.add_argument("--type", choices=["http", "https", "socks4", "socks5"], default="http",
                        help="Proxy type (default: http).")
    parser.add_argument("--json", action="store_true", help="Output JSON only.")
    args = parser.parse_args()

    host, port = parse_target(args.target)
    geoip = GeoIP()
    r = asyncio.run(check(host, port, args.type, geoip))
    geoip.close()

    if args.json:
        print(json.dumps(r, indent=2, ensure_ascii=False))
    else:
        print_report(r)
    sys.exit(0 if r["http"]["ok"] or r["https"]["ok"] else 1)


if __name__ == "__main__":
    main()
