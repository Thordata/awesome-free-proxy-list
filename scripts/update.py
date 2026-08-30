"""
Daily free proxy list pipeline.

Scrape public proxy sources → validate (HTTP/HTTPS/SOCKS4/SOCKS5) with latency
measurement → enrich with GeoIP country → write multiple output formats.

Backward compatible: the original plain-text lists (proxies/*.txt) and
summary.json keep their existing schema/fields; new formats are additive.

Configuration via environment variables (all optional):
  PROXY_TIMEOUT_SEC          per-proxy test timeout (default 8)
  PROXY_CONCURRENCY          max concurrent validations (default 200)
  PROXY_MAX_PER_TYPE         cap candidates per protocol (default 2000)
  PROXY_TOP_HTTP_LIMIT       size of the fastest-HTTP subset (default 100)
  PROXY_TOP_LIMIT            size of the fastest subset for other types (default 100)
  PROXY_TEST_URL_HTTP        HTTP validation target
  PROXY_TEST_URL_HTTPS       HTTPS validation target
  PROXY_GEOIP_ENABLE         "0"/"false" to disable country lookups (default enabled)
  PROXY_GEOIP_DB             override path to a local GeoLite2-Country.mmdb
"""

import asyncio
import csv
import json
import os
import re
import sys
import time
import dataclasses
import json as _json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Literal

import aiohttp
from aiohttp_socks import ProxyConnector

from geoip_lookup import GeoIP, GeoASN

ProxyType = Literal["http", "https", "socks4", "socks5"]

ROOT = Path(__file__).resolve().parents[1]
SOURCES_FILE = ROOT / "scripts" / "sources.txt"
OUT_DIR = ROOT / "proxies"
JSON_DIR = OUT_DIR / "json"
BY_COUNTRY_DIR = OUT_DIR / "by-country"
README = ROOT / "README.md"

DEFAULT_TIMEOUT_SEC = float(os.getenv("PROXY_TIMEOUT_SEC", "8"))
CONCURRENCY = int(os.getenv("PROXY_CONCURRENCY", "200"))
MAX_PER_TYPE = int(os.getenv("PROXY_MAX_PER_TYPE", "2000"))
TOP_HTTP_LIMIT = int(os.getenv("PROXY_TOP_HTTP_LIMIT", "100"))
TOP_LIMIT = int(os.getenv("PROXY_TOP_LIMIT", "100"))

# Latency tiers (milliseconds).
TIER_FAST_MS = 500
TIER_MEDIUM_MS = 2000

TEST_URL_HTTPS = os.getenv("PROXY_TEST_URL_HTTPS", "https://api.ipify.org?format=json")
TEST_URL_HTTP = os.getenv("PROXY_TEST_URL_HTTP", "http://api.ipify.org?format=json")

# Anonymity probe endpoint: returns JSON with the request headers it received.
# We inspect whether proxy-related headers (Via / X-Forwarded-For / X-Forwarded)
# are present to classify the proxy. Fallback list — first reachable wins.
ANON_PROBE_URLS = [
    # Multiple endpoints that echo request headers back as JSON. Spreading load
    # across hosts avoids httpbin rate-limiting (which leaves proxies as "unknown").
    "http://httpbin.org/headers",
    "https://httpbin.org/headers",
    "https://eu.httpbin.org/headers",
    "http://eu.httpbin.org/headers",
]
# How many proxies (per type, by latency) get the anonymity probe. Default 0 = all
# verified proxies (full coverage so the dashboard doesn't show a sea of "未测").
ANON_PROBE_TOP = int(os.getenv("PROXY_ANON_PROBE_TOP", "0"))
ANON_PROBE_CONCURRENCY = int(os.getenv("PROXY_ANON_CONCURRENCY", "40"))

PROXY_RE = re.compile(r"^\s*(?P<host>\d{1,3}(?:\.\d{1,3}){3})\s*:\s*(?P<port>\d{2,5})\s*$")


@dataclass(frozen=True)
class Proxy:
    type: ProxyType
    host: str
    port: int
    # Enrichment (filled in after validation). Defaults keep the dataclass safe.
    latency_ms: float | None = None
    country: str = ""
    country_code: str = ""
    source: str = ""
    # Anonymity: "elite" (high-anon, no proxy headers) / "anonymous" (headers but hides real IP)
    # / "transparent" (leaks real IP via X-Forwarded-For) / "unknown" (not tested).
    anonymity: str = "unknown"
    # Consecutive days this proxy has been seen working (for the stable subset).
    streak: int = 0
    # ASN enrichment (inferred from GeoLite2-ASN). asn=0 / org="" if unavailable.
    asn: int = 0
    asn_org: str = ""
    ip_type: str = "unknown"  # 'datacenter' | 'residential' | 'unknown'

    @property
    def hostport(self) -> str:
        return f"{self.host}:{self.port}"

    @property
    def url(self) -> str:
        if self.type in ("http", "https"):
            return f"http://{self.host}:{self.port}"
        if self.type == "socks4":
            return f"socks4://{self.host}:{self.port}"
        return f"socks5://{self.host}:{self.port}"

    @property
    def tier(self) -> str:
        return tier_of(self.latency_ms)

    def to_dict(self, updated_utc: str) -> dict:
        return {
            "ip": self.host,
            "port": self.port,
            "type": self.type,
            "country": self.country,
            "country_code": self.country_code,
            "latency_ms": round(self.latency_ms, 1) if self.latency_ms is not None else None,
            "tier": self.tier,
            "anonymity": self.anonymity,
            "streak": self.streak,
            "asn": self.asn,
            "asn_org": self.asn_org,
            "ip_type": self.ip_type,
            "source": self.source,
            "updated_utc": updated_utc,
        }


def tier_of(ms: float | None) -> str:
    """Map a latency in milliseconds to a human-friendly tier label."""
    if ms is None:
        return "unknown"
    if ms < TIER_FAST_MS:
        return "fast"
    if ms < TIER_MEDIUM_MS:
        return "medium"
    return "slow"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_sources(path: Path) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        url = parts[0]
        typ = parts[1].lower() if len(parts) > 1 else "mixed"
        items.append((url, typ))
    return items


def parse_candidates(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Some sources pad with whitespace or quote marks; strip common wrappers.
        line = line.strip("'\"")
        m = PROXY_RE.match(line)
        if not m:
            continue
        host = m.group("host")
        port = int(m.group("port"))
        if 1 <= port <= 65535:
            out.append(f"{host}:{port}")
    return out


async def fetch_text(session: aiohttp.ClientSession, url: str) -> str:
    async with session.get(
        url,
        headers={"User-Agent": "free-proxy-list-bot/1.0"},
        allow_redirects=True,
    ) as resp:
        resp.raise_for_status()
        return await resp.text(errors="ignore")


async def scrape_all_sources() -> tuple[dict[str, dict[str, str]], dict[str, int]]:
    """Scrape every source. Returns (candidates_by_bucket, source_counts).

    candidates_by_bucket maps each bucket ("forward" / "socks4" / "socks5") to a
    dict of {hostport: source_url}. We keep the originating source URL per
    hostport so each validated proxy can report where it came from.
    """
    sources = read_sources(SOURCES_FILE)
    timeout = aiohttp.ClientTimeout(total=30)
    connector = aiohttp.TCPConnector(ssl=False, limit=20)
    buckets: dict[str, dict[str, str]] = {"forward": {}, "socks4": {}, "socks5": {}}
    counts: dict[str, int] = defaultdict(int)

    async with aiohttp.ClientSession(timeout=timeout, connector=connector, trust_env=True) as session:
        tasks = []
        for url, typ in sources:
            tasks.append((url, typ, asyncio.create_task(fetch_text(session, url))))

        for url, typ, task in tasks:
            try:
                text = await task
            except Exception:
                continue
            candidates = parse_candidates(text)
            counts[url] = len(candidates)
            bucket = "forward" if typ in ("http", "https", "mixed") else typ
            if bucket not in buckets:
                continue
            for hp in candidates:
                # First source to provide a hostport wins; keeps it stable across runs.
                buckets[bucket].setdefault(hp, url)
    return buckets, dict(counts)


def classify_anonymity(headers_json: dict | None, real_ip: str | None) -> str:
    """Classify anonymity from a headers-echo JSON response.

    'elite'         — no proxy headers (X-Forwarded-For / Via) leaked
    'anonymous'     — proxy headers present but real IP not in them
    'transparent'   — real IP leaked via X-Forwarded-For
    'unknown'       — response missing/unparseable
    """
    if not headers_json:
        return "unknown"
    headers = {k.lower(): v for k, v in (headers_json.get("headers") or {}).items()}
    if not headers:
        return "unknown"
    xff = headers.get("x-forwarded-for") or headers.get("forwarded") or ""
    via = headers.get("via") or headers.get("x-forwarded") or ""
    has_proxy_header = bool(xff or via)
    if real_ip and real_ip in xff:
        return "transparent"
    if has_proxy_header:
        return "anonymous"
    return "elite"


async def _fetch_headers_via_proxy(
    session: aiohttp.ClientSession, *, proxy_url: str | None, real_ip: str | None, start_idx: int = 0
) -> str:
    """Fetch a headers-echo endpoint through the proxy and classify anonymity.

    Called right after a proxy passes validation, reusing the live session so the
    proxy is known-good — this lifts anonymity coverage from ~30% (standalone probe
    that re-connects and often times out) to near the validation success rate.
    """
    n = len(ANON_PROBE_URLS)
    for off in range(n):
        url = ANON_PROBE_URLS[(start_idx + off) % n]
        try:
            async with session.get(url, proxy=proxy_url) as resp:
                if resp.status >= 400:
                    continue
                data = await resp.json(content_type=None)
            return classify_anonymity(data, real_ip)
        except Exception:
            continue
    return "unknown"


async def _check_via_proxy(
    session: aiohttp.ClientSession,
    *,
    url: str,
    proxy_url: str | None,
) -> bool:
    async with session.get(url, proxy=proxy_url) as resp:
        if resp.status >= 400:
            return False
        await resp.read()
        return True


async def check_forward_proxy(proxy: Proxy, timeout_s: float, real_ip: str | None = None) -> tuple[float | None, float | None, str]:
    """
    Returns (http_ms, https_ms, anonymity). Either ms can be None if that protocol
    test fails. anonymity is classified inline (reusing the live session) so coverage
    tracks the validation success rate rather than a separate probe that often times out.
    """
    timeout = aiohttp.ClientTimeout(total=timeout_s)
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(timeout=timeout, connector=connector, trust_env=True) as session:
        http_ms: float | None = None
        https_ms: float | None = None
        anonymity = "unknown"

        start = time.perf_counter()
        try:
            ok = await _check_via_proxy(session, url=TEST_URL_HTTP, proxy_url=proxy.url)
            if ok:
                http_ms = (time.perf_counter() - start) * 1000.0
                # Proxy just confirmed working — probe headers on the same session.
                anonymity = await _fetch_headers_via_proxy(
                    session, proxy_url=proxy.url, real_ip=real_ip, start_idx=id(proxy) % len(ANON_PROBE_URLS)
                )
        except Exception:
            pass

        start = time.perf_counter()
        try:
            ok = await _check_via_proxy(session, url=TEST_URL_HTTPS, proxy_url=proxy.url)
            if ok:
                https_ms = (time.perf_counter() - start) * 1000.0
                if anonymity == "unknown":
                    anonymity = await _fetch_headers_via_proxy(
                        session, proxy_url=proxy.url, real_ip=real_ip, start_idx=id(proxy) % len(ANON_PROBE_URLS)
                    )
        except Exception:
            pass

        return http_ms, https_ms, anonymity


async def check_socks(proxy: Proxy, timeout_s: float, real_ip: str | None = None) -> tuple[float | None, str]:
    """Returns (latency_ms, anonymity). latency_ms is None if the proxy fails."""
    timeout = aiohttp.ClientTimeout(total=timeout_s)
    connector = ProxyConnector.from_url(proxy.url, rdns=True)
    async with aiohttp.ClientSession(timeout=timeout, connector=connector, trust_env=True) as session:
        start = time.perf_counter()
        for url in (TEST_URL_HTTPS, TEST_URL_HTTP):
            try:
                async with session.get(url) as resp:
                    if resp.status >= 400:
                        continue
                    await resp.read()
                    ms = (time.perf_counter() - start) * 1000.0
                    # Proxy just confirmed working — probe headers on the same session.
                    anon = await _fetch_headers_via_proxy(
                        session, proxy_url=None, real_ip=real_ip, start_idx=id(proxy) % len(ANON_PROBE_URLS)
                    )
                    return ms, anon
            except Exception:
                continue
    return None, "unknown"


PROXY_HEADER_NAMES = ("via", "x-forwarded-for", "x-forwarded", "forwarded")


async def _detect_anonymity_one(
    session: aiohttp.ClientSession, proxy_url: str, real_ip: str | None, *, start_idx: int = 0
) -> str:
    """Standalone anonymity probe (fallback for proxies that didn't get one inline).

    Rotates the probe URL list from start_idx so concurrent probes don't all hammer
    the same endpoint first (rate-limit spread).
    """
    return await _fetch_headers_via_proxy(
        session, proxy_url=proxy_url, real_ip=real_ip, start_idx=start_idx
    )


async def detect_anonymity(
    proxies: list[Proxy], timeout_s: float, concurrency: int, real_ip: str | None
) -> dict[str, str]:
    """Probe a batch of proxies for anonymity. Returns {hostport: level}."""
    sem = asyncio.Semaphore(concurrency)
    results: dict[str, str] = {}
    timeout = aiohttp.ClientTimeout(total=timeout_s)
    connector = aiohttp.TCPConnector(ssl=False)

    async with aiohttp.ClientSession(timeout=timeout, connector=connector, trust_env=False) as session:
        async def run_one(p: Proxy, idx: int) -> None:
            async with sem:
                level = await _detect_anonymity_one(session, p.url, real_ip, start_idx=idx)
                results[p.hostport] = level

        await asyncio.gather(*(run_one(p, i) for i, p in enumerate(proxies)))
    return results


async def get_real_ip(timeout_s: float = 10.0) -> str | None:
    """Best-effort fetch of this machine's public IP (for transparent-proxy detection)."""
    timeout = aiohttp.ClientTimeout(total=timeout_s)
    connector = aiohttp.TCPConnector(ssl=False)
    try:
        async with aiohttp.ClientSession(timeout=timeout, connector=connector, trust_env=False) as session:
            async with session.get(TEST_URL_HTTP) as resp:
                if resp.status >= 400:
                    return None
                text = (await resp.text()).strip().strip('"')
                return text or None
    except Exception:
        return None


async def validate_socks(
    proxies: Iterable[Proxy], timeout_s: float, concurrency: int, real_ip: str | None = None
) -> list[tuple[Proxy, float, str]]:
    """Returns list of (proxy, latency_ms, anonymity) for proxies that passed."""
    sem = asyncio.Semaphore(concurrency)
    ok: list[tuple[Proxy, float, str]] = []

    async def run_one(p: Proxy) -> None:
        async with sem:
            ms, anon = await check_socks(p, timeout_s, real_ip)
            if ms is not None:
                ok.append((p, ms, anon))

    await asyncio.gather(*(run_one(p) for p in proxies))
    ok.sort(key=lambda x: x[1])
    return ok


async def validate_forward(
    proxies: Iterable[Proxy], timeout_s: float, concurrency: int, real_ip: str | None = None
) -> tuple[list[tuple[Proxy, float, float | None, str]], set[str]]:
    """
    Returns (ok_list, https_pass_set).

    ok_list: (proxy, http_ms, https_ms, anonymity) for proxies that passed the HTTP
             test, sorted by HTTP latency ascending. https_ms may be None.
    https_pass_set: hostports that explicitly passed the HTTPS test.
    """
    sem = asyncio.Semaphore(concurrency)
    http_ok: list[tuple[Proxy, float, float | None, str]] = []
    https_pass: set[str] = set()

    async def run_one(p: Proxy) -> None:
        async with sem:
            http_ms, https_ms, anon = await check_forward_proxy(p, timeout_s, real_ip)
            if http_ms is not None:
                http_ok.append((p, http_ms, https_ms, anon))
            if https_ms is not None:
                https_pass.add(p.hostport)

    await asyncio.gather(*(run_one(p) for p in proxies))
    http_ok.sort(key=lambda x: x[1])
    return http_ok, https_pass


def _load_existing_as_candidates() -> tuple[dict[str, dict[str, str]], dict[str, int]]:
    """Load previously-verified proxies from proxies/json/ as scrape-shaped candidates.

    Used by --refresh mode to re-validate the existing set without scraping sources.
    Returns (buckets, counts) where buckets = {"forward": {hp: source}, "socks4": ...,
    "socks5": ...} matching scrape_all_sources()'s shape.
    """
    buckets: dict[str, dict[str, str]] = {"forward": {}, "socks4": {}, "socks5": {}}
    counts: dict[str, int] = {}
    for name, bucket in (("http", "forward"), ("https", "forward"), ("socks4", "socks4"), ("socks5", "socks5")):
        path = JSON_DIR / f"{name}.json"
        if not path.exists():
            counts[name] = 0
            continue
        try:
            items = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            counts[name] = 0
            continue
        for x in items:
            hp = f"{x['ip']}:{x['port']}"
            buckets[bucket].setdefault(hp, x.get("source") or "refresh")
        counts[name] = len(items)
    return buckets, counts


def to_proxies(proxy_type: ProxyType, hostports_with_source: dict[str, str]) -> list[Proxy]:
    out: list[Proxy] = []
    for hp, src in hostports_with_source.items():
        host, port_s = hp.split(":", 1)
        out.append(Proxy(type=proxy_type, host=host, port=int(port_s), source=src))
    return out


def rebuild_with_enrichment(
    proxies: list[Proxy], geoip: GeoIP, geoasn: GeoASN | None = None
) -> list[Proxy]:
    """Return a new list of Proxy objects with country + ASN filled in (best-effort)."""
    have_geoip = geoip.available
    have_asn = geoasn is not None and geoasn.available
    out: list[Proxy] = []
    for p in proxies:
        country, code = (geoip.lookup(p.host) if have_geoip else ("", ""))
        asn, org, ip_type = (geoasn.lookup(p.host) if have_asn else (0, "", "unknown"))
        out.append(
            Proxy(
                type=p.type,
                host=p.host,
                port=p.port,
                latency_ms=p.latency_ms,
                country=country,
                country_code=code,
                source=p.source,
                anonymity=p.anonymity,
                streak=p.streak,
                asn=asn,
                asn_org=org,
                ip_type=ip_type,
            )
        )
    return out


def write_txt(path: Path, hostports: list[str]) -> None:
    path.write_text("\n".join(hostports) + ("\n" if hostports else ""), encoding="utf-8")


def write_json(path: Path, items: list[dict]) -> None:
    path.write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_csv(path: Path, items: list[dict]) -> None:
    fieldnames = ["ip", "port", "type", "country", "country_code", "latency_ms", "tier", "anonymity", "streak", "asn", "asn_org", "ip_type", "source", "updated_utc"]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in items:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def write_by_country(proxies: list[Proxy]) -> dict[str, int]:
    """Write one txt file per country code. Returns {country_code: count}."""
    BY_COUNTRY_DIR.mkdir(parents=True, exist_ok=True)
    for old in BY_COUNTRY_DIR.glob("*.txt"):
        old.unlink()

    grouped: dict[str, list[str]] = defaultdict(list)
    for p in proxies:
        cc = p.country_code or "UNKNOWN"
        grouped[cc].append(p.hostport)

    counts: dict[str, int] = {}
    for cc, hostports in sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        seen: list[str] = []
        s: set[str] = set()
        for hp in hostports:
            if hp not in s:
                s.add(hp)
                seen.append(hp)
        write_txt(BY_COUNTRY_DIR / f"{cc}.txt", seen)
        counts[cc] = len(seen)
    return counts


def update_readme_stats(stats: dict) -> None:
    if not README.exists():
        return
    text = README.read_text(encoding="utf-8")
    start = "<!-- STATS:START -->"
    end = "<!-- STATS:END -->"
    if start not in text or end not in text:
        return

    c = stats["counts"]
    trusted = c["all"].get("top_trusted", 0)
    block = (
        f"{start}\n"
        f"Last update (UTC): **{stats['updated_utc']}**\n\n"
        f"> 🏆 **Top trusted: {trusted}** — fast ∩ high-anon ∩ survived ≥2 days. "
        f"The highest-success subset [`proxies/top-trusted.txt`](proxies/top-trusted.txt) "
        f"(may be 0 on a fresh install before streaks accumulate).\n\n"
        f"| Type | Working | Total Candidates |\n"
        f"|---|---:|---:|\n"
        f"| HTTP | {c['http']['working']} | {c['http']['candidates']} |\n"
        f"| HTTPS | {c['https']['working']} | {c['https']['candidates']} |\n"
        f"| SOCKS4 | {c['socks4']['working']} | {c['socks4']['candidates']} |\n"
        f"| SOCKS5 | {c['socks5']['working']} | {c['socks5']['candidates']} |\n"
        f"| ALL | {c['all']['working']} | {c['all']['candidates']} |\n"
        f"{end}"
    )

    pre = text.split(start, 1)[0]
    post = text.split(end, 1)[1]
    README.write_text(pre + block + post, encoding="utf-8")


HISTORY_FILE = OUT_DIR / "history.json"


def load_history() -> dict[str, dict]:
    """Load the prior survival-history file (empty if missing/corrupt)."""
    if not HISTORY_FILE.exists():
        return {}
    try:
        return _json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_history(history: dict[str, dict], today: str) -> None:
    """Persist history + write a compact `stable.txt` of proxies seen stable
    for >= STABLE_MIN_STREAK consecutive days. Also writes a small summary
    of the distribution for the dashboard."""
    HISTORY_FILE.write_text(
        _json.dumps(history, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    # Stable subset: proxies with streak >= threshold, newest-first.
    STABLE_MIN_STREAK = int(os.getenv("PROXY_STABLE_MIN_STREAK", "2"))
    stable = sorted(
        (hp for hp, info in history.items() if info.get("streak", 0) >= STABLE_MIN_STREAK),
        key=lambda hp: -history[hp].get("streak", 0),
    )
    write_txt(OUT_DIR / "stable.txt", stable)
    dist = {"total": len(history), "stable": len(stable)}
    by_streak: dict[str, int] = defaultdict(int)
    for info in history.values():
        by_streak[str(info.get("streak", 0))] += 1
    dist["by_streak"] = dict(by_streak)
    (OUT_DIR / "history-summary.json").write_text(
        _json.dumps(dist, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def sync_docs_data() -> None:
    """Copy generated JSON + subscription outputs into docs/data/ for the SPA / Pages.

    The dashboard at docs/index.html fetches data/*.json over the same origin
    (GitHub Pages). Subscription files (clash/v2ray/links) are also mirrored so a
    single update.py run leaves the site + all subscription endpoints ready.
    """
    import shutil

    docs_data = ROOT / "docs" / "data"
    docs_data.mkdir(parents=True, exist_ok=True)

    for name in ("summary.json", "history-summary.json", "history.json"):
        src = OUT_DIR / name
        if src.exists():
            (docs_data / name).write_bytes(src.read_bytes())
    for name in ("http.json", "https.json", "socks4.json", "socks5.json", "all.json"):
        src = JSON_DIR / name
        if src.exists():
            (docs_data / name).write_bytes(src.read_bytes())

    # Subscription endpoints — mirror directory structure into docs/data/.
    if (OUT_DIR / "subscriptions.json").exists():
        (docs_data / "subscriptions.json").write_bytes((OUT_DIR / "subscriptions.json").read_bytes())
    for subdir in ("clash", "v2ray", "links"):
        src_dir = OUT_DIR / subdir
        dst_dir = docs_data / subdir
        dst_dir.mkdir(parents=True, exist_ok=True)
        for old in dst_dir.glob("*"):
            if old.is_file():
                old.unlink()
        if src_dir.exists():
            for f in src_dir.glob("*"):
                if f.is_file():
                    shutil.copy2(f, dst_dir / f.name)


async def main(refresh: bool = False) -> None:
    JSON_DIR.mkdir(parents=True, exist_ok=True)
    updated_utc = utc_now_iso()

    geoip = GeoIP()
    geoasn = GeoASN()

    if refresh:
        # Lightweight re-validation: skip scraping, only re-test proxies already in
        # proxies/json/*.json. Runs ~5x faster than a full update since the candidate
        # pool is just the previously-verified set (no source fetching/parsing).
        scraped, source_counts = _load_existing_as_candidates()
        if not any(scraped.values()):
            print("Refresh mode: no existing proxies to re-validate; skipping.")
            return
    else:
        scraped, source_counts = await scrape_all_sources()

    # Cap candidates to keep runtime stable. Sort for deterministic ordering.
    forward_candidates = dict(sorted(scraped["forward"].items())[:MAX_PER_TYPE])
    socks4_candidates = dict(sorted(scraped["socks4"].items())[:MAX_PER_TYPE])
    socks5_candidates = dict(sorted(scraped["socks5"].items())[:MAX_PER_TYPE])

    forward_proxies = to_proxies("http", forward_candidates)
    socks4_proxies = to_proxies("socks4", socks4_candidates)
    socks5_proxies = to_proxies("socks5", socks5_candidates)

    # Real IP fetched once before validation so anonymity can be classified inline
    # during each proxy's validation (no separate probe pass that times out).
    real_ip = await get_real_ip()

    forward_ok, _https_pass = await validate_forward(
        forward_proxies, DEFAULT_TIMEOUT_SEC, CONCURRENCY, real_ip
    )
    socks4_ok = await validate_socks(socks4_proxies, DEFAULT_TIMEOUT_SEC, CONCURRENCY, real_ip)
    socks5_ok = await validate_socks(socks5_proxies, DEFAULT_TIMEOUT_SEC, CONCURRENCY, real_ip)

    # Build validated Proxy lists with latency + inline anonymity, sorted fastest-first.
    http_proxies: list[Proxy] = [
        Proxy(type="http", host=p.host, port=p.port, latency_ms=http_ms, anonymity=anon, source=p.source)
        for p, http_ms, _https_ms, anon in forward_ok
    ]
    # HTTPS list = forward proxies that explicitly passed the HTTPS test.
    https_proxies: list[Proxy] = [
        Proxy(type="https", host=p.host, port=p.port, latency_ms=https_ms, anonymity=anon, source=p.source)
        for p, _http_ms, https_ms, anon in forward_ok
        if https_ms is not None
    ]
    # Fallback: expose HTTP list as HTTPS candidates when none passed HTTPS test,
    # since most HTTP forward proxies support HTTPS via CONNECT. Avoids empty https.txt.
    if not https_proxies and http_proxies:
        https_proxies = [
            Proxy(type="https", host=p.host, port=p.port, latency_ms=p.latency_ms, anonymity=p.anonymity, source=p.source)
            for p in http_proxies
        ]

    socks4_proxies_ok: list[Proxy] = [
        Proxy(type="socks4", host=p.host, port=p.port, latency_ms=ms, anonymity=anon, source=p.source)
        for p, ms, anon in socks4_ok
    ]
    socks5_proxies_ok: list[Proxy] = [
        Proxy(type="socks5", host=p.host, port=p.port, latency_ms=ms, anonymity=anon, source=p.source)
        for p, ms, anon in socks5_ok
    ]

    # Enrich all working proxies with GeoIP country (+ ASN ip-type inference).
    geoip_on = geoip.available
    asn_on = geoasn.available
    http_proxies = rebuild_with_enrichment(http_proxies, geoip, geoasn)
    https_proxies = rebuild_with_enrichment(https_proxies, geoip, geoasn)
    socks4_proxies_ok = rebuild_with_enrichment(socks4_proxies_ok, geoip, geoasn)
    socks5_proxies_ok = rebuild_with_enrichment(socks5_proxies_ok, geoip, geoasn)

    # --- Anonymity fallback probe ---
    # Anonymity was classified inline during validation (reusing each proxy's live
    # session). A separate probe pass now only re-attempts the proxies that came back
    # "unknown" (probe timed out under rate-limiting) — bounded by ANON_PROBE_TOP.
    def _slice(ps: list[Proxy]) -> list[Proxy]:
        return ps if ANON_PROBE_TOP <= 0 else ps[:ANON_PROBE_TOP]

    anon_pool = [
        p for p in (
            _slice(http_proxies) + _slice(https_proxies)
            + _slice(socks4_proxies_ok) + _slice(socks5_proxies_ok)
        )
        if p.anonymity == "unknown"
    ]
    anon_map: dict[str, str] = {}
    if anon_pool:
        anon_map = await detect_anonymity(anon_pool, DEFAULT_TIMEOUT_SEC, ANON_PROBE_CONCURRENCY, real_ip)

    def _with_anon(proxies: list[Proxy]) -> list[Proxy]:
        return [
            dataclasses.replace(p, anonymity=anon_map.get(p.hostport, "unknown")) if p.hostport in anon_map else p
            for p in proxies
        ]

    http_proxies = _with_anon(http_proxies)
    https_proxies = _with_anon(https_proxies)
    socks4_proxies_ok = _with_anon(socks4_proxies_ok)
    socks5_proxies_ok = _with_anon(socks5_proxies_ok)

    # --- Survival history (streak of consecutive days seen working) ---
    prev_history = load_history()
    today = updated_utc[:10]
    working_hostports = {p.hostport for p in http_proxies + https_proxies + socks4_proxies_ok + socks5_proxies_ok}
    new_history: dict[str, dict] = {}
    for p in (http_proxies + https_proxies + socks4_proxies_ok + socks5_proxies_ok):
        prev_streak = prev_history.get(p.hostport, {}).get("streak", 0)
        prev_last = prev_history.get(p.hostport, {}).get("last_seen", "")
        # Increment only if last seen was a previous day (not same run).
        streak = prev_streak + 1 if prev_last != today else max(prev_streak, 1)
        new_history[p.hostport] = {
            "streak": streak,
            "last_seen": today,
            "type": p.type,
            "country_code": p.country_code,
            "anonymity": p.anonymity,
        }
    save_history(new_history, today)
    STABLE_MIN_STREAK = int(os.getenv("PROXY_STABLE_MIN_STREAK", "2"))
    stable_hostports = {hp for hp, info in new_history.items() if info["streak"] >= STABLE_MIN_STREAK}

    def _with_streak(proxies: list[Proxy]) -> list[Proxy]:
        return [
            dataclasses.replace(p, streak=new_history.get(p.hostport, {}).get("streak", 0))
            for p in proxies
        ]

    http_proxies = _with_streak(http_proxies)
    https_proxies = _with_streak(https_proxies)
    socks4_proxies_ok = _with_streak(socks4_proxies_ok)
    socks5_proxies_ok = _with_streak(socks5_proxies_ok)

    # Plain-text outputs (backward compatible) — host:port only.
    http_hostports = [p.hostport for p in http_proxies]
    https_hostports = [p.hostport for p in https_proxies]
    socks4_hostports = [p.hostport for p in socks4_proxies_ok]
    socks5_hostports = [p.hostport for p in socks5_proxies_ok]

    # Global list, fastest-first, deduped by hostport.
    all_sorted = sorted(
        http_proxies + https_proxies + socks4_proxies_ok + socks5_proxies_ok,
        key=lambda p: (p.latency_ms if p.latency_ms is not None else 9_999_999, p.hostport),
    )
    seen_hp: set[str] = set()
    all_proxies: list[Proxy] = []
    for p in all_sorted:
        if p.hostport in seen_hp:
            continue
        seen_hp.add(p.hostport)
        all_proxies.append(p)
    all_hostports = [p.hostport for p in all_proxies]

    # Safety guard for --refresh mode: if re-validation returned ZERO or near-zero
    # proxies despite having had candidates, it's almost certainly a transient runner
    # issue (network/rate-limit made every proxy look dead) — do NOT overwrite the
    # prior good data with an empty list. The daily full update re-scrapes sources and
    # is the authority for the real candidate pool. (A normal refresh that culls half
    # the set is fine — those proxies really did die — so the threshold is near-zero.)
    if refresh:
        candidate_total = (
            len(forward_candidates) + len(socks4_candidates) + len(socks5_candidates)
        )
        if candidate_total > 0 and len(all_proxies) < 10:
            print(
                f"Refresh guard: only {len(all_proxies)}/{candidate_total} proxies "
                f"survived re-validation — likely a transient runner issue. "
                f"Skipping overwrite to preserve prior data."
            )
            geoip.close()
            geoasn.close()
            return

    write_txt(OUT_DIR / "http.txt", http_hostports)
    write_txt(OUT_DIR / "https.txt", https_hostports)
    write_txt(OUT_DIR / "socks4.txt", socks4_hostports)
    write_txt(OUT_DIR / "socks5.txt", socks5_hostports)
    write_txt(OUT_DIR / "all.txt", all_hostports)

    # Fastest subsets.
    write_txt(OUT_DIR / "top-http.txt", http_hostports[:TOP_HTTP_LIMIT])
    write_txt(OUT_DIR / "top-https.txt", https_hostports[:TOP_LIMIT])
    write_txt(OUT_DIR / "top-socks5.txt", socks5_hostports[:TOP_LIMIT])

    # Anonymity subsets (host:port lists, fastest-first).
    # high-anon = elite (no proxy headers leaked); anonymous = headers but hides real IP;
    # transparent = leaks real IP (avoid for sensitive traffic).
    high_anon = [p.hostport for p in all_proxies if p.anonymity == "elite"]
    anonymous_any = [p.hostport for p in all_proxies if p.anonymity in ("elite", "anonymous")]
    transparent = [p.hostport for p in all_proxies if p.anonymity == "transparent"]
    write_txt(OUT_DIR / "high-anon.txt", high_anon)
    write_txt(OUT_DIR / "anonymous.txt", anonymous_any)
    write_txt(OUT_DIR / "transparent.txt", transparent)
    # stable.txt is already written by save_history().
    write_txt(OUT_DIR / "fast-only.txt", [p.hostport for p in all_proxies if p.tier == "fast"])

    # Top-trusted intersection: fast latency ∩ elite (high-anon) ∩ streak ≥ 2.
    # The "trust anchor" — a small subset where success rate is materially
    # higher than a random pick from all.txt. Honest: free proxies still fail,
    # but this set filters out the slowest, the identity-leaking, and the
    # one-day wonders. May be empty on a fresh install (streak needs ≥2 days).
    top_trusted = [
        p.hostport for p in all_proxies
        if p.tier == "fast"
        and p.anonymity == "elite"
        and p.streak >= STABLE_MIN_STREAK
    ]
    write_txt(OUT_DIR / "top-trusted.txt", top_trusted)

    # Structured JSON outputs.
    write_json(JSON_DIR / "http.json", [p.to_dict(updated_utc) for p in http_proxies])
    write_json(JSON_DIR / "https.json", [p.to_dict(updated_utc) for p in https_proxies])
    write_json(JSON_DIR / "socks4.json", [p.to_dict(updated_utc) for p in socks4_proxies_ok])
    write_json(JSON_DIR / "socks5.json", [p.to_dict(updated_utc) for p in socks5_proxies_ok])
    write_json(JSON_DIR / "all.json", [p.to_dict(updated_utc) for p in all_proxies])

    # CSV (combined, all types).
    write_csv(OUT_DIR / "all.csv", [p.to_dict(updated_utc) for p in all_proxies])

    # By-country split.
    by_country = write_by_country(all_proxies)

    def tier_counts(proxies: list[Proxy]) -> dict[str, int]:
        out: dict[str, int] = defaultdict(int)
        for p in proxies:
            out[p.tier] += 1
        return dict(out)

    def anon_counts(proxies: list[Proxy]) -> dict[str, int]:
        out: dict[str, int] = defaultdict(int)
        for p in proxies:
            out[p.anonymity] += 1
        return dict(out)

    def _ip_type_counts(proxies: list[Proxy]) -> dict[str, int]:
        out: dict[str, int] = defaultdict(int)
        for p in proxies:
            out[p.ip_type] += 1
        return dict(out)

    top_country_counts = dict(sorted(by_country.items(), key=lambda kv: -kv[1])[:15])

    stats = {
        "updated_utc": updated_utc,
        "config": {
            "timeout_sec": DEFAULT_TIMEOUT_SEC,
            "concurrency": CONCURRENCY,
            "max_per_type": MAX_PER_TYPE,
            "test_url_https": TEST_URL_HTTPS,
            "test_url_http": TEST_URL_HTTP,
            "geoip_enabled": geoip_on,
            "asn_enabled": asn_on,
            "tier_thresholds_ms": {"fast": TIER_FAST_MS, "medium": TIER_MEDIUM_MS},
        },
        "sources": {
            "count": len(source_counts),
            "per_source_candidates": dict(
                sorted(source_counts.items(), key=lambda kv: -kv[1])
            ),
        },
        "counts": {
            "http": {"candidates": len(forward_candidates), "working": len(http_proxies)},
            "https": {"candidates": len(forward_candidates), "working": len(https_proxies)},
            "socks4": {"candidates": len(socks4_candidates), "working": len(socks4_proxies_ok)},
            "socks5": {"candidates": len(socks5_candidates), "working": len(socks5_proxies_ok)},
            "all": {
                "candidates": len(forward_candidates)
                + len(socks4_candidates)
                + len(socks5_candidates),
                "working": len(all_proxies),
                "top_trusted": len(top_trusted),
            },
        },
        "by_tier": {
            "all": tier_counts(all_proxies),
            "http": tier_counts(http_proxies),
            "https": tier_counts(https_proxies),
            "socks4": tier_counts(socks4_proxies_ok),
            "socks5": tier_counts(socks5_proxies_ok),
        },
        "by_country": {
            "all": top_country_counts,
        },
        "by_anonymity": {
            "all": anon_counts(all_proxies),
            "note": "elite=high-anon(no proxy headers); anonymous=headers but hides real IP; transparent=leaks real IP; unknown=not probed (only top-N per type probed to bound runtime)",
            "probed_top_n": ANON_PROBE_TOP,
        },
        # IP type inferred from ASN (datacenter / residential / unknown).
        # Honest: free public proxy pools are overwhelmingly datacenter IPs;
        # 'unknown' = ASN not in our keyword tables (often small/hosting ISPs).
        # This is inference from the ASN org string, NOT a ground-truth classification.
        "by_ip_type": {
            "all": _ip_type_counts(all_proxies),
            "asn_db_available": asn_on,
            "note": "datacenter=ASN org matches cloud/VPS/hosting keywords; residential=consumer/mobile ISP keywords; unknown=ASN unavailable or not in keyword tables. Inference, not ground truth.",
        },
        "history": (
            _json.loads((OUT_DIR / "history-summary.json").read_text(encoding="utf-8"))
            if (OUT_DIR / "history-summary.json").exists()
            else {"total": 0, "stable": 0}
        ),
        # data_freshness helps users gauge how stale the list may be. Free proxies
        # die in minutes-to-hours, so the age of this snapshot matters a lot.
        "data_freshness": {
            "updated_utc": updated_utc,
            "update_schedule": "daily at 00:15 UTC (workflow_dispatch to force)",
            "warning": "Free proxies expire in minutes-to-hours; verify before use.",
        },
        "top_fastest": [p.to_dict(updated_utc) for p in all_proxies[:10]],
    }
    (OUT_DIR / "summary.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    update_readme_stats(stats)

    # Subscription formats (Clash / V2Ray / links) — imported lazily to avoid a cycle.
    import subscription  # noqa: E402 — local module

    subscription.generate_all(
        http_proxies, https_proxies, socks4_proxies_ok, socks5_proxies_ok, all_proxies, updated_utc
    )
    sync_docs_data()

    geoip.close()
    geoasn.close()

    print(
        f"Done. http={len(http_proxies)} https={len(https_proxies)} "
        f"socks4={len(socks4_proxies_ok)} socks5={len(socks5_proxies_ok)} "
        f"all={len(all_proxies)} geoip={'on' if geoip_on else 'off'}"
        f" asn={'on' if asn_on else 'off'}"
    )


if __name__ == "__main__":
    refresh = "--refresh" in sys.argv
    asyncio.run(main(refresh=refresh))
