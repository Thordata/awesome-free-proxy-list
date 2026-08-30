"""
Generate subscription files for popular proxy clients from validated proxies.

Outputs (written into proxies/ and mirrored to docs/data/ for the SPA + Pages):
  - proxies/clash/all.yaml            — Clash/Mihomo config (HTTP + SOCKS5)
  - proxies/clash/http.yaml           — HTTP only
  - proxies/clash/socks5.yaml         — SOCKS5 only
  - proxies/v2ray/all.txt             — V2Ray-style base64 subscription
  - proxies/links/http.txt            — one "http://ip:port" per line
  - proxies/links/socks5.txt          — one "socks5://ip:port" per line
  - proxies/subscriptions.json        — manifest of all subscription URLs (for the SPA)

Design notes:
- Clash proxies get a human-friendly `name` like "{flag} {type} {ip}:{port} {tier}".
- proxy-groups include per-type and per-country SELECT groups + a final AUTO/PROXY.
- We do NOT emit username/password (public free proxies have none).
- base64 subscriptions are newline-joined before encoding (V2Ray convention).
"""

from __future__ import annotations

import base64
import json
from collections import defaultdict
from pathlib import Path

from update import Proxy, tier_of  # reuse the dataclass + tier helper

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "proxies"
JSON_DIR = OUT_DIR / "json"
CLASH_DIR = OUT_DIR / "clash"
V2RAY_DIR = OUT_DIR / "v2ray"
LINKS_DIR = OUT_DIR / "links"


def flag_emoji(cc: str) -> str:
    if not cc or cc == "UNKNOWN" or len(cc) != 2:
        return "🏳️"
    cp = [0x1F1E6 + (ord(c) - 65) for c in cc.upper()]
    return "".join(chr(p) for p in cp)


def clash_proxy_name(p: Proxy, idx: int) -> str:
    cc = p.country_code or "??"
    flag = flag_emoji(cc)
    tier = tier_of(p.latency_ms)
    return f"{flag} {p.type.upper()} {p.host}:{p.port} {tier[:1].upper()}"


def clash_proxy_entry(p: Proxy, name: str) -> dict:
    """One Clash/Mihomo proxy node as a dict (will be YAML-dumped)."""
    return {
        "name": name,
        "type": "http" if p.type in ("http", "https") else p.type,
        "server": p.host,
        "port": p.port,
        "udp": False,
    }


def _yaml_dump(obj) -> str:
    """Minimal YAML emitter (block style, no external dep).

    Produces standard block YAML that every parser (PyYAML, ruamel, Clash/Mihomo)
    accepts. Handles dict / list / str / int / float / bool / None. Strings that
    contain special characters are double-quoted.
    """
    NEEDS_QUOTE = set(':#{}[],&*!|>?"@`')

    def esc(s: str) -> str:
        if s == "":
            return '""'
        if any(c in s for c in NEEDS_QUOTE) or s[0] in "- " or s.lower() in ("true", "false", "null", "yes", "no", "on", "off"):
            return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
        return s

    def fmt_scalar(v) -> str:
        if v is None:
            return ""
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, str):
            return esc(v)
        return str(v)

    def emit(val, indent: int) -> list[str]:
        pad = "  " * indent
        lines: list[str] = []
        if isinstance(val, dict):
            for k, v in val.items():
                if isinstance(v, dict) and v:
                    lines.append(f"{pad}{k}:")
                    lines.extend(emit(v, indent + 1))
                elif isinstance(v, list) and v:
                    lines.append(f"{pad}{k}:")
                    lines.extend(emit_list(v, indent + 1))
                elif isinstance(v, list):
                    lines.append(f"{pad}{k}: []")
                elif isinstance(v, dict):
                    lines.append(f"{pad}{k}: {{}}")
                elif v is None:
                    lines.append(f"{pad}{k}:")
                else:
                    lines.append(f"{pad}{k}: {fmt_scalar(v)}")
        elif isinstance(val, list):
            lines.extend(emit_list(val, indent))
        else:
            lines.append(pad + fmt_scalar(val))
        return lines

    def emit_list(val: list, indent: int) -> list[str]:
        pad = "  " * indent
        lines: list[str] = []
        for item in val:
            if isinstance(item, dict) and item:
                items = list(item.items())
                first_k, first_v = items[0]
                if isinstance(first_v, dict) and first_v:
                    lines.append(f"{pad}- {first_k}:")
                    lines.extend(emit(first_v, indent + 2))
                elif isinstance(first_v, list) and first_v:
                    lines.append(f"{pad}- {first_k}:")
                    lines.extend(emit_list(first_v, indent + 2))
                elif isinstance(first_v, list):
                    lines.append(f"{pad}- {first_k}: []")
                elif first_v is None:
                    lines.append(f"{pad}- {first_k}:")
                else:
                    lines.append(f"{pad}- {first_k}: {fmt_scalar(first_v)}")
                for k, v in items[1:]:
                    sub_pad = "  " * (indent + 1)
                    if isinstance(v, dict) and v:
                        lines.append(f"{sub_pad}{k}:")
                        lines.extend(emit(v, indent + 2))
                    elif isinstance(v, list) and v:
                        lines.append(f"{sub_pad}{k}:")
                        lines.extend(emit_list(v, indent + 2))
                    elif isinstance(v, list):
                        lines.append(f"{sub_pad}{k}: []")
                    elif isinstance(v, dict):
                        lines.append(f"{sub_pad}{k}: {{}}")
                    elif v is None:
                        lines.append(f"{sub_pad}{k}:")
                    else:
                        lines.append(f"{sub_pad}{k}: {fmt_scalar(v)}")
            elif isinstance(item, list):
                lines.append(f"{pad}-")
                lines.extend(emit_list(item, indent + 1))
            else:
                lines.append(f"{pad}- {fmt_scalar(item)}")
        return lines

    return "\n".join(emit(obj, 0)) + "\n"


def build_clash_config(proxies: list[Proxy], *, title: str, updated_utc: str) -> str:
    """Build a minimal, valid Clash/Mihomo YAML config from a proxy list."""
    seen: set[str] = set()
    unique: list[Proxy] = []
    for p in proxies:
        if p.hostport in seen:
            continue
        seen.add(p.hostport)
        unique.append(p)
    # Cap to keep configs manageable for clients.
    unique = unique[:500]

    nodes: list[dict] = []
    names: list[str] = []
    by_type: dict[str, list[str]] = defaultdict(list)
    by_country: dict[str, list[str]] = defaultdict(list)

    for i, p in enumerate(unique, start=1):
        name = clash_proxy_name(p, i)
        names.append(name)
        nodes.append(clash_proxy_entry(p, name))
        by_type[p.type].append(name)
        by_country[p.country_code or "UNKNOWN"].append(name)

    groups: list[dict] = [
        {"name": "🚀 PROXY", "type": "select", "proxies": ["♻️ AUTO", "DIRECT"] + names[:200]},
        {"name": "♻️ AUTO", "type": "url-test", "proxies": names[:200],
         "url": "http://www.gstatic.com/generate_204", "interval": 300},
    ]
    for t, ns in by_type.items():
        if ns:
            groups.append({"name": f"📦 {t.upper()}", "type": "select", "proxies": ns[:200]})
    top_cc = sorted(by_country.items(), key=lambda kv: -len(kv[1]))[:8]
    for cc, ns in top_cc:
        if cc == "UNKNOWN" or not ns:
            continue
        groups.append({"name": f"{flag_emoji(cc)} {cc}", "type": "select", "proxies": ns[:200]})

    config = {
        # mixed-port serves both HTTP and SOCKS5 on the same port (Clash Verge uses it).
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "warning",
        "external-controller": "127.0.0.1:9090",
        "proxies": nodes,
        "proxy-groups": groups,
        "rules": [
            "DOMAIN-SUFFIX,local,DIRECT",
            "IP-CIDR,127.0.0.0/8,DIRECT",
            "IP-CIDR,172.16.0.0/12,DIRECT",
            "IP-CIDR,192.168.0.0/16,DIRECT",
            "IP-CIDR,10.0.0.0/8,DIRECT",
            "GEOIP,CN,DIRECT",
            "MATCH,🚀 PROXY",
        ],
    }
    header = (
        f"# {title}\n"
        f"# Generated: {updated_utc}\n"
        f"# Proxies: {len(unique)}\n"
        f"# Source: kael-odin/awesome-free-proxy-list\n\n"
    )
    return header + _yaml_dump(config)


def build_v2ray_sub(proxies: list[Proxy]) -> str:
    """V2Ray base64 subscription: each line is a proxy URL, then base64 the whole thing."""
    urls: list[str] = []
    seen: set[str] = set()
    for p in proxies:
        if p.hostport in seen:
            continue
        seen.add(p.hostport)
        if p.type in ("http", "https"):
            urls.append(f"http://{p.host}:{p.port}")
        elif p.type == "socks5":
            urls.append(f"socks5://{p.host}:{p.port}")
        elif p.type == "socks4":
            urls.append(f"socks4://{p.host}:{p.port}")
    joined = "\n".join(urls)
    return base64.b64encode(joined.encode("utf-8")).decode("ascii")


def build_links(proxies: list[Proxy], ptype: str | None = None) -> str:
    """Plain proxy URL list (one per line)."""
    urls: list[str] = []
    seen: set[str] = set()
    for p in proxies:
        if ptype and p.type != ptype:
            continue
        if p.hostport in seen:
            continue
        seen.add(p.hostport)
        if p.type in ("http", "https"):
            urls.append(f"http://{p.host}:{p.port}")
        elif p.type == "socks5":
            urls.append(f"socks5://{p.host}:{p.port}")
        elif p.type == "socks4":
            urls.append(f"socks4://{p.host}:{p.port}")
    return "\n".join(urls) + ("\n" if urls else "")


def build_manifest(updated_utc: str, proxy_counts: dict, categories: dict) -> dict:
    """Manifest describing every subscription file + its public Pages URL.

    `categories` maps a category key (e.g. "fast", "us", "high-anon") to a human
    label, so the SPA can render grouped subscription cards.
    """
    base = "https://kael-odin.github.io/awesome-free-proxy-list/data"
    raw_base = "https://raw.githubusercontent.com/kael-odin/awesome-free-proxy-list/main/proxies"
    files = [
        # --- Clash configs ---
        {"name": "Clash / Mihomo — 全部 (HTTP+SOCKS5)", "name_en": "Clash/Mihomo — All (HTTP+SOCKS5)",
         "format": "clash", "category": "all", "path": "clash/all.yaml",
         "pages": f"{base}/clash/all.yaml", "raw": f"{raw_base}/clash/all.yaml"},
        {"name": "Clash / Mihomo — 仅 HTTP", "name_en": "Clash/Mihomo — HTTP only",
         "format": "clash", "category": "by_type", "path": "clash/http.yaml",
         "pages": f"{base}/clash/http.yaml", "raw": f"{raw_base}/clash/http.yaml"},
        {"name": "Clash / Mihomo — 仅 SOCKS5", "name_en": "Clash/Mihomo — SOCKS5 only",
         "format": "clash", "category": "by_type", "path": "clash/socks5.yaml",
         "pages": f"{base}/clash/socks5.yaml", "raw": f"{raw_base}/clash/socks5.yaml"},
        {"name": "Clash — 仅快速 (fast 档)", "name_en": "Clash — Fast tier only",
         "format": "clash", "category": "by_tier", "path": "clash/fast.yaml",
         "pages": f"{base}/clash/fast.yaml", "raw": f"{raw_base}/clash/fast.yaml"},
        {"name": "Clash — 高匿 (elite)", "name_en": "Clash — High-anon (elite)",
         "format": "clash", "category": "by_anon", "path": "clash/high-anon.yaml",
         "pages": f"{base}/clash/high-anon.yaml", "raw": f"{raw_base}/clash/high-anon.yaml"},
        {"name": "Clash — 稳定 (连续多日可用)", "name_en": "Clash — Stable (multi-day)",
         "format": "clash", "category": "stable", "path": "clash/stable.yaml",
         "pages": f"{base}/clash/stable.yaml", "raw": f"{raw_base}/clash/stable.yaml"},
        # --- V2Ray ---
        {"name": "V2Ray base64 订阅 (全部)", "name_en": "V2Ray base64 subscription (all)",
         "format": "v2ray", "category": "all", "path": "v2ray/all.txt",
         "pages": f"{base}/v2ray/all.txt", "raw": f"{raw_base}/v2ray/all.txt"},
        # --- Link lists ---
        {"name": "链接列表 — HTTP", "name_en": "Link list — HTTP",
         "format": "links", "category": "by_type", "path": "links/http.txt",
         "pages": f"{base}/links/http.txt", "raw": f"{raw_base}/links/http.txt"},
        {"name": "链接列表 — SOCKS5", "name_en": "Link list — SOCKS5",
         "format": "links", "category": "by_type", "path": "links/socks5.txt",
         "pages": f"{base}/links/socks5.txt", "raw": f"{raw_base}/links/socks5.txt"},
        {"name": "链接列表 — 全部", "name_en": "Link list — All",
         "format": "links", "category": "all", "path": "links/all.txt",
         "pages": f"{base}/links/all.txt", "raw": f"{raw_base}/links/all.txt"},
        {"name": "链接列表 — 高匿", "name_en": "Link list — High-anon",
         "format": "links", "category": "by_anon", "path": "links/high-anon.txt",
         "pages": f"{base}/links/high-anon.txt", "raw": f"{raw_base}/links/high-anon.txt"},
        {"name": "链接列表 — 稳定", "name_en": "Link list — Stable",
         "format": "links", "category": "stable", "path": "links/stable.txt",
         "pages": f"{base}/links/stable.txt", "raw": f"{raw_base}/links/stable.txt"},
    ]
    return {
        "updated_utc": updated_utc,
        "counts": proxy_counts,
        "categories": categories,
        "subscriptions": files,
        "import_guides": {
            "clash_verge": "打开 Clash Verge → 订阅 → 粘贴 .yaml 的 Pages URL → 更新 → 选中配置",
            "clash_verge_en": "Clash Verge → Profiles → paste the .yaml Pages URL → Update → select the profile",
            "v2rayn": "V2RayN → 订阅 → 订阅设置 → 粘贴 v2ray/all.txt 的 Pages URL → 更新",
            "surge": "Surge → 策略组 → 外部代理列表 → 粘贴 links/http.txt URL",
        },
    }


def generate_all(
    http_proxies: list[Proxy],
    https_proxies: list[Proxy],
    socks4_proxies: list[Proxy],
    socks5_proxies: list[Proxy],
    all_proxies: list[Proxy],
    updated_utc: str,
) -> dict:
    """Write every subscription format. Returns the manifest dict."""
    CLASH_DIR.mkdir(parents=True, exist_ok=True)
    V2RAY_DIR.mkdir(parents=True, exist_ok=True)
    LINKS_DIR.mkdir(parents=True, exist_ok=True)

    forward_all = http_proxies + https_proxies
    socks_all = socks5_proxies + socks4_proxies
    clash_combined = forward_all + socks_all

    (CLASH_DIR / "all.yaml").write_text(
        build_clash_config(clash_combined, title="Free Proxy List — All (HTTP + SOCKS5)", updated_utc=updated_utc),
        encoding="utf-8",
    )
    (CLASH_DIR / "http.yaml").write_text(
        build_clash_config(forward_all, title="Free Proxy List — HTTP", updated_utc=updated_utc),
        encoding="utf-8",
    )
    (CLASH_DIR / "socks5.yaml").write_text(
        build_clash_config(socks_all, title="Free Proxy List — SOCKS5", updated_utc=updated_utc),
        encoding="utf-8",
    )

    # --- Filtered Clash configs: fast tier / high-anon / stable ---
    fast_proxies = [p for p in clash_combined if p.tier == "fast"]
    high_anon_proxies = [p for p in clash_combined if p.anonymity == "elite"]
    stable_proxies = [p for p in clash_combined if p.streak >= 2]
    if fast_proxies:
        (CLASH_DIR / "fast.yaml").write_text(
            build_clash_config(fast_proxies, title="Free Proxy List — Fast tier (<500ms)", updated_utc=updated_utc),
            encoding="utf-8",
        )
    else:
        (CLASH_DIR / "fast.yaml").unlink(missing_ok=True)
    if high_anon_proxies:
        (CLASH_DIR / "high-anon.yaml").write_text(
            build_clash_config(high_anon_proxies, title="Free Proxy List — High-anonymity (elite)", updated_utc=updated_utc),
            encoding="utf-8",
        )
    else:
        (CLASH_DIR / "high-anon.yaml").unlink(missing_ok=True)
    if stable_proxies:
        (CLASH_DIR / "stable.yaml").write_text(
            build_clash_config(stable_proxies, title="Free Proxy List — Stable (multi-day)", updated_utc=updated_utc),
            encoding="utf-8",
        )
    else:
        (CLASH_DIR / "stable.yaml").unlink(missing_ok=True)

    (V2RAY_DIR / "all.txt").write_text(build_v2ray_sub(clash_combined), encoding="utf-8")

    (LINKS_DIR / "http.txt").write_text(build_links(forward_all, "http"), encoding="utf-8")
    (LINKS_DIR / "socks5.txt").write_text(build_links(socks5_proxies, "socks5"), encoding="utf-8")
    (LINKS_DIR / "all.txt").write_text(build_links(clash_combined), encoding="utf-8")
    (LINKS_DIR / "high-anon.txt").write_text(build_links(high_anon_proxies), encoding="utf-8")
    (LINKS_DIR / "stable.txt").write_text(build_links(stable_proxies), encoding="utf-8")

    counts = {
        "http": len(http_proxies),
        "https": len(https_proxies),
        "socks4": len(socks4_proxies),
        "socks5": len(socks5_proxies),
        "all": len(all_proxies),
        "fast": len(fast_proxies),
        "high_anon": len(high_anon_proxies),
        "stable": len(stable_proxies),
    }
    categories = {
        "all": {"zh": "全部", "en": "All"},
        "by_type": {"zh": "按协议", "en": "By protocol"},
        "by_tier": {"zh": "按延迟档", "en": "By latency tier"},
        "by_anon": {"zh": "按匿名度", "en": "By anonymity"},
        "stable": {"zh": "稳定代理", "en": "Stable proxies"},
    }
    manifest = build_manifest(updated_utc, counts, categories)
    (OUT_DIR / "subscriptions.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


if __name__ == "__main__":
    # Standalone: regenerate subscriptions from proxies/json/*.json (no re-validation).
    def load(name):
        p = JSON_DIR / f"{name}.json"
        if not p.exists():
            return []
        return [
            Proxy(
                type=x["type"], host=x["ip"], port=x["port"], latency_ms=x.get("latency_ms"),
                country=x.get("country", ""), country_code=x.get("country_code", ""),
                source=x.get("source", ""),
                anonymity=x.get("anonymity", "unknown"),
                streak=x.get("streak", 0),
            )
            for x in json.loads(p.read_text(encoding="utf-8"))
        ]

    import sys
    from update import utc_now_iso

    m = generate_all(load("http"), load("https"), load("socks4"), load("socks5"), load("all"), utc_now_iso())
    print(f"OK — {len(m['subscriptions'])} subscription files generated.", file=sys.stderr)
