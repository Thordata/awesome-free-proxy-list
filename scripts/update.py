import asyncio
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Literal

import aiohttp
from aiohttp_socks import ProxyConnector

ProxyType = Literal["http", "socks4", "socks5"]


ROOT = Path(__file__).resolve().parents[1]
SOURCES_FILE = ROOT / "scripts" / "sources.txt"
OUT_DIR = ROOT / "proxies"
README = ROOT / "README.md"

DEFAULT_TIMEOUT_SEC = float(os.getenv("PROXY_TIMEOUT_SEC", "8"))
CONCURRENCY = int(os.getenv("PROXY_CONCURRENCY", "200"))
MAX_PER_TYPE = int(os.getenv("PROXY_MAX_PER_TYPE", "2000"))

# You can override these via environment variables if you prefer other targets.
TEST_URL_HTTPS = os.getenv("PROXY_TEST_URL_HTTPS", "https://api.ipify.org?format=json")
TEST_URL_HTTP = os.getenv("PROXY_TEST_URL_HTTP", "http://api.ipify.org?format=json")

PROXY_RE = re.compile(r"^\s*(?P<host>\d{1,3}(?:\.\d{1,3}){3})\s*:\s*(?P<port>\d{2,5})\s*$")


@dataclass(frozen=True)
class Proxy:
    type: ProxyType
    host: str
    port: int

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


async def scrape_all_sources() -> dict[str, set[str]]:
    sources = read_sources(SOURCES_FILE)
    timeout = aiohttp.ClientTimeout(total=30)
    connector = aiohttp.TCPConnector(ssl=False, limit=20)
    results: dict[str, set[str]] = {"forward": set(), "socks4": set(), "socks5": set()}

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
            if typ in ("http", "https", "mixed"):
                results["forward"].update(candidates)
            elif typ in results:
                results[typ].update(candidates)
    return results


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


async def check_forward_proxy(proxy: Proxy, timeout_s: float) -> tuple[float | None, float | None]:
    """
    Returns (http_ms, https_ms). Either can be None if that protocol test fails.
    """
    timeout = aiohttp.ClientTimeout(total=timeout_s)
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(timeout=timeout, connector=connector, trust_env=True) as session:
        http_ms: float | None = None
        https_ms: float | None = None

        start = time.perf_counter()
        try:
            ok = await _check_via_proxy(session, url=TEST_URL_HTTP, proxy_url=proxy.url)
            if ok:
                http_ms = (time.perf_counter() - start) * 1000.0
        except Exception:
            pass

        start = time.perf_counter()
        try:
            ok = await _check_via_proxy(session, url=TEST_URL_HTTPS, proxy_url=proxy.url)
            if ok:
                https_ms = (time.perf_counter() - start) * 1000.0
        except Exception:
            pass

        return http_ms, https_ms


async def check_socks(proxy: Proxy, timeout_s: float) -> float | None:
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
                    return (time.perf_counter() - start) * 1000.0
            except Exception:
                continue
    return None


async def validate_socks(proxies: Iterable[Proxy], timeout_s: float, concurrency: int) -> list[tuple[Proxy, float]]:
    sem = asyncio.Semaphore(concurrency)
    ok: list[tuple[Proxy, float]] = []

    async def run_one(p: Proxy) -> None:
        async with sem:
            ms = await check_socks(p, timeout_s)
            if ms is not None:
                ok.append((p, ms))

    await asyncio.gather(*(run_one(p) for p in proxies))
    ok.sort(key=lambda x: x[1])
    return ok


async def validate_forward(
    proxies: Iterable[Proxy], timeout_s: float, concurrency: int
) -> tuple[list[str], list[str], dict[str, dict[str, int]]]:
    """
    Returns (http_working, https_working, counts_by_capability).
    """
    sem = asyncio.Semaphore(concurrency)
    http_ok: list[tuple[str, float]] = []
    https_ok: list[tuple[str, float]] = []

    async def run_one(p: Proxy) -> None:
        async with sem:
            http_ms, https_ms = await check_forward_proxy(p, timeout_s)
            if http_ms is not None:
                http_ok.append((p.hostport, http_ms))
            if https_ms is not None:
                https_ok.append((p.hostport, https_ms))

    await asyncio.gather(*(run_one(p) for p in proxies))
    http_ok.sort(key=lambda x: x[1])
    https_ok.sort(key=lambda x: x[1])
    return [hp for hp, _ in http_ok], [hp for hp, _ in https_ok], {
        "http": {"working": len(http_ok)},
        "https": {"working": len(https_ok)},
    }


def to_proxies(proxy_type: ProxyType, hostports: Iterable[str]) -> list[Proxy]:
    out: list[Proxy] = []
    for hp in hostports:
        host, port_s = hp.split(":", 1)
        out.append(Proxy(type=proxy_type, host=host, port=int(port_s)))
    return out


def write_txt(path: Path, hostports: list[str]) -> None:
    path.write_text("\n".join(hostports) + ("\n" if hostports else ""), encoding="utf-8")


def update_readme_stats(stats: dict) -> None:
    if not README.exists():
        return
    text = README.read_text(encoding="utf-8")
    start = "<!-- STATS:START -->"
    end = "<!-- STATS:END -->"
    if start not in text or end not in text:
        return

    block = (
        f"{start}\n"
        f"Last update (UTC): **{stats['updated_utc']}**\n\n"
        f"| Type | Working | Total Candidates |\n"
        f"|---|---:|---:|\n"
        f"| HTTP | {stats['counts']['http']['working']} | {stats['counts']['http']['candidates']} |\n"
        f"| HTTPS | {stats['counts']['https']['working']} | {stats['counts']['https']['candidates']} |\n"
        f"| SOCKS4 | {stats['counts']['socks4']['working']} | {stats['counts']['socks4']['candidates']} |\n"
        f"| SOCKS5 | {stats['counts']['socks5']['working']} | {stats['counts']['socks5']['candidates']} |\n"
        f"| ALL | {stats['counts']['all']['working']} | {stats['counts']['all']['candidates']} |\n"
        f"{end}"
    )

    pre = text.split(start, 1)[0]
    post = text.split(end, 1)[1]
    new_text = pre + block + post
    README.write_text(new_text, encoding="utf-8")


async def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    scraped = await scrape_all_sources()

    # Cap candidates to keep runtime stable.
    forward_candidates = sorted(scraped["forward"])[:MAX_PER_TYPE]
    socks4_candidates = sorted(scraped["socks4"])[:MAX_PER_TYPE]
    socks5_candidates = sorted(scraped["socks5"])[:MAX_PER_TYPE]

    forward_proxies = to_proxies("http", forward_candidates)
    socks4_proxies = to_proxies("socks4", socks4_candidates)
    socks5_proxies = to_proxies("socks5", socks5_candidates)

    forward_http, forward_https, _forward_counts = await validate_forward(
        forward_proxies, DEFAULT_TIMEOUT_SEC, CONCURRENCY
    )
    socks4_ok = await validate_socks(socks4_proxies, DEFAULT_TIMEOUT_SEC, CONCURRENCY)
    socks5_ok = await validate_socks(socks5_proxies, DEFAULT_TIMEOUT_SEC, CONCURRENCY)

    socks4_working = [p.hostport for p, _ms in socks4_ok]
    socks5_working = [p.hostport for p, _ms in socks5_ok]

    # Fallback: if no proxy explicitly passed the HTTPS test but we have HTTP-working proxies,
    # expose the HTTP list as HTTPS candidates as well. In practice most HTTP forward proxies
    # support HTTPS via CONNECT, and this avoids an empty https.txt which is confusing for users.
    if not forward_https and forward_http:
        forward_https = list(forward_http)

    all_working = sorted(set(forward_http) | set(forward_https) | set(socks4_working) | set(socks5_working))

    write_txt(OUT_DIR / "http.txt", forward_http)
    write_txt(OUT_DIR / "https.txt", forward_https)
    write_txt(OUT_DIR / "socks4.txt", socks4_working)
    write_txt(OUT_DIR / "socks5.txt", socks5_working)
    write_txt(OUT_DIR / "all.txt", all_working)

    stats = {
        "updated_utc": utc_now_iso(),
        "config": {
            "timeout_sec": DEFAULT_TIMEOUT_SEC,
            "concurrency": CONCURRENCY,
            "max_per_type": MAX_PER_TYPE,
            "test_url_https": TEST_URL_HTTPS,
            "test_url_http": TEST_URL_HTTP,
        },
        "counts": {
            "http": {"candidates": len(forward_candidates), "working": len(forward_http)},
            "https": {"candidates": len(forward_candidates), "working": len(forward_https)},
            "socks4": {"candidates": len(socks4_candidates), "working": len(socks4_working)},
            "socks5": {"candidates": len(socks5_candidates), "working": len(socks5_working)},
            "all": {
                "candidates": len(forward_candidates) + len(socks4_candidates) + len(socks5_candidates),
                "working": len(all_working),
            },
        },
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(stats, indent=2, sort_keys=True), encoding="utf-8")
    update_readme_stats(stats)


if __name__ == "__main__":
    asyncio.run(main())

