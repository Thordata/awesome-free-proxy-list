"""
Quickly test a few proxies from the generated lists (no curl dependency).

Reads proxies/<type>.txt (or the JSON variant), samples N of them, and verifies
each through aiohttp — reporting latency, success rate, and the exit IP when
available. Cross-platform (Windows / macOS / Linux).

Usage:
    python scripts/test_proxies.py --type http --limit 5
    python scripts/test_proxies.py --type socks5 --limit 10 --latency
    python scripts/test_proxies.py --type https --limit 3 --json
    python scripts/test_proxies.py --type http --country US --tier fast
"""

import argparse
import asyncio
import json
import random
import sys
import time
from pathlib import Path

import aiohttp
from aiohttp_socks import ProxyConnector

ROOT = Path(__file__).resolve().parents[1]
PROXIES_DIR = ROOT / "proxies"

TEST_URL = "https://api.ipify.org?format=json"
TIMEOUT_SEC = 10.0


def load_proxies(kind: str, *, country: str | None = None, tier: str | None = None) -> list[dict]:
    """Load proxies of a type. Prefers JSON (has country/latency/tier) for filtering."""
    json_path = PROXIES_DIR / "json" / f"{kind}.json"
    txt_path = PROXIES_DIR / f"{kind}.txt"

    if (country or tier) and json_path.exists():
        items = json.loads(json_path.read_text(encoding="utf-8"))
        if country:
            items = [p for p in items if (p.get("country_code") or "").upper() == country.upper()]
        if tier:
            items = [p for p in items if p.get("tier") == tier]
        return items

    if json_path.exists():
        return json.loads(json_path.read_text(encoding="utf-8"))

    if not txt_path.exists():
        raise SystemExit(f"Neither {json_path} nor {txt_path} exist. Run scripts/update.py first.")
    lines = [ln.strip() for ln in txt_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return [{"ip": hp.split(":")[0], "port": int(hp.split(":")[1]), "type": kind} for hp in lines]


def proxy_url(p: dict) -> str:
    t = p.get("type", "http")
    if t in ("http", "https"):
        return f"http://{p['ip']}:{p['port']}"
    if t == "socks4":
        return f"socks4://{p['ip']}:{p['port']}"
    return f"socks5://{p['ip']}:{p['port']}"


async def test_one(p: dict, idx: int, total: int) -> dict:
    url = proxy_url(p)
    is_socks = p.get("type") in ("socks4", "socks5")
    connector = ProxyConnector.from_url(url, rdns=True) if is_socks else None

    timeout = aiohttp.ClientTimeout(total=TIMEOUT_SEC)
    start = time.perf_counter()
    result = {
        "idx": idx, "proxy": f"{p['ip']}:{p['port']}", "type": p.get("type", "http"),
        "ok": False, "latency_ms": None, "exit_ip": None, "country": p.get("country", ""),
        "country_code": p.get("country_code", ""), "error": None,
    }

    try:
        session_kwargs: dict = {"timeout": timeout}
        get_kwargs: dict = {}
        if connector is not None:
            session_kwargs["connector"] = connector
        else:
            get_kwargs["proxy"] = url
        async with aiohttp.ClientSession(**session_kwargs) as session:
            async with session.get(TEST_URL, **get_kwargs) as resp:
                if resp.status >= 400:
                    result["error"] = f"http {resp.status}"
                    return result
                data = await resp.json(content_type=None)
                result["latency_ms"] = round((time.perf_counter() - start) * 1000, 1)
                result["exit_ip"] = data.get("ip") if isinstance(data, dict) else None
                result["ok"] = True
    except Exception as e:
        result["error"] = type(e).__name__
    return result


def fmt_latency(ms: float | None) -> str:
    if ms is None:
        return "  —  "
    return f"{ms:>6.0f}ms"


async def run(args: argparse.Namespace) -> int:
    proxies = load_proxies(args.type, country=args.country, tier=args.tier)
    if not proxies:
        print(f"No proxies match the filter ({args.type}"
              + (f" country={args.country}" if args.country else "")
              + (f" tier={args.tier}" if args.tier else "") + ").")
        return 1

    sample = random.sample(proxies, min(args.limit, len(proxies)))
    print(f"Loaded {len(proxies)} '{args.type}' proxies"
          + (f" (filtered)" if args.country or args.tier else "")
          + f", testing {len(sample)} of them.\n")

    results = await asyncio.gather(*[test_one(p, i + 1, len(sample)) for i, p in enumerate(sample)])

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print(f"{'#':>3}  {'Proxy':22}  {'Type':6}  {'Latency':9}  {'Exit IP':16}  Result")
        print("-" * 80)
        for r in results:
            status = "✅ " if r["ok"] else "❌ " + (r["error"] or "")
            print(f"{r['idx']:>3}  {r['proxy']:22}  {r['type']:6}  "
                  f"{fmt_latency(r['latency_ms']):9}  {(r['exit_ip'] or '—'):16}  {status}")

    ok = sum(1 for r in results if r["ok"])
    print(f"\nSummary: {ok}/{len(results)} succeeded.")
    return 0 if ok else 1


def main() -> None:
    # Windows consoles default to GBK; force UTF-8 so emoji + CJK render correctly.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Quickly test a few proxies from the generated lists.")
    parser.add_argument("--type", choices=["http", "https", "socks4", "socks5"], default="http",
                        help="Which proxies file to use (default: http).")
    parser.add_argument("--limit", type=int, default=5, help="How many random proxies to test (default: 5).")
    parser.add_argument("--country", default=None, help="Filter to a country code (e.g. US). Needs json/*.json.")
    parser.add_argument("--tier", choices=["fast", "medium", "slow", "unknown"], default=None,
                        help="Filter to a latency tier. Needs json/*.json.")
    parser.add_argument("--json", action="store_true", help="Output results as JSON.")
    parser.add_argument("--latency", action="store_true", help="Alias kept for compatibility; latency is always shown.")
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
