# Security Policy

## Supported version

Only the `main` branch is supported. Automated data refreshes land there continuously — always test against the latest commit.

## In scope

- The scripts in `scripts/` (scraper, validator, GeoIP enrichment, subscription generator, checker) and the static dashboard in `docs/`.
- Dependency vulnerabilities in `requirements.txt` / `scripts/requirements-dev.txt`.
- Workflow security issues (`.github/workflows/`) such as injection via untrusted input or excessive permissions.

## Out of scope

- **The listed proxies themselves.** Every proxy in `proxies/` comes from third-party public sources and is untrusted by design. A proxy misbehaving, injecting content, or logging traffic is expected behavior for free public proxies, not a vulnerability in this project — the README's risk disclosure exists precisely for this. Reports of "this proxy stole my cookies" will be closed.
- Whether a given proxy works right now. Free proxies live for minutes to hours; check `proxies/summary.json` timestamps first.

## How to report

Use GitHub's [private vulnerability reporting](https://github.com/Thordata/awesome-free-proxy-list/security/advisories/new) on this repository. Please do not open a public issue for anything in scope.

Include: affected script/file, the commit SHA, and a minimal reproduction. You can also run `python scripts/check.py IP:PORT` to capture per-proxy diagnostics worth attaching.

## Notes for users

Never route logins, payments, or private data through any proxy from this list — including `elite` ones. The anonymity rating describes what the proxy *claims* to hide, not whether its operator is trustworthy.
