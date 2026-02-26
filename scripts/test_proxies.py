"""
Small helper to quickly test a few proxies from the generated lists.

Usage (after running scripts/update.py):

    python scripts/test_proxies.py --type http --limit 5
"""

import argparse
import random
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROXIES_DIR = ROOT / "proxies"


def load_proxies(kind: str) -> list[str]:
    path = PROXIES_DIR / f"{kind}.txt"
    if not path.exists():
        raise SystemExit(f"{path} does not exist. Run scripts/update.py first.")
    proxies = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not proxies:
        raise SystemExit(f"No proxies found in {path}.")
    return proxies


def test_with_curl(proxy: str, scheme: str, url: str) -> int:
    """
    Use curl so that behaviour is very close to how users will actually test.
    This calls https://httpbin.org/ip through the given proxy.
    """
    print(f"\n=== Testing proxy: {proxy} ({scheme.upper()} {url}) ===")
    cmd = [
        "curl",
        "-x",
        f"{scheme}://{proxy}",
        url,
        "--max-time",
        "10",
        "-s",
        "-v",
    ]
    try:
        result = subprocess.run(cmd, check=False)
        return result.returncode
    except FileNotFoundError:
        raise SystemExit("curl is not installed or not found in PATH.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Quickly test a few proxies using curl.")
    parser.add_argument(
        "--type",
        choices=["http", "https", "socks4", "socks5"],
        default="http",
        help="Which proxies file to use under proxies/ (default: http).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="How many random proxies to test (default: 5).",
    )
    parser.add_argument(
        "--scheme",
        choices=["http", "https"],
        default="http",
        help="Whether to test an HTTP or HTTPS target (default: http).",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Override test URL. By default uses http(s)://api.ipify.org?format=json.",
    )
    args = parser.parse_args()

    proxies = load_proxies(args.type)
    sample = random.sample(proxies, min(args.limit, len(proxies)))
    print(f"Loaded {len(proxies)} proxies from proxies/{args.type}.txt, testing {len(sample)} of them.")

    if args.url:
        url = args.url
    else:
        base = "http://api.ipify.org?format=json" if args.scheme == "http" else "https://api.ipify.org?format=json"
        url = base

    successes = 0
    for p in sample:
        code = test_with_curl(p, args.scheme, url)
        if code == 0:
            successes += 1

    print(f"\nSummary: {successes}/{len(sample)} succeeded (curl exit code 0).")


if __name__ == "__main__":
    main()

