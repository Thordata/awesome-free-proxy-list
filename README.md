# Free Proxy List (Daily Updated)

This repository provides a **free proxy list** that is **automatically updated daily** via GitHub Actions (no server cost).

- **Pipeline**: scrape public proxy sources → validate availability → format outputs → commit updates
- **Target**: global audience, simple formats, easy to consume

## Download

All outputs are generated into the `proxies/` directory:

- `proxies/http.txt`
- `proxies/https.txt`
- `proxies/socks4.txt`
- `proxies/socks5.txt`
- `proxies/all.txt`
- `proxies/summary.json`

## Stats

<!-- STATS:START -->
Last update (UTC): **2026-02-26T06:38:55+00:00**

| Type | Working | Total Candidates |
|---|---:|---:|
| HTTP | 280 | 2000 |
| HTTPS | 7 | 2000 |
| SOCKS4 | 0 | 2000 |
| SOCKS5 | 0 | 2000 |
| ALL | 280 | 6000 |
<!-- STATS:END -->

## How it works

- Sources are defined in `scripts/sources.txt`
- One script does everything: `scripts/update.py`
- GitHub Actions runs daily and pushes changes if outputs changed

## Run locally

```bash
python -m venv .venv
source .venv/Scripts/activate  # Windows Git Bash
pip install -r requirements.txt
python scripts/update.py
```

## Disclaimer

Free proxies are often unstable and may be abused by third parties. Use at your own risk. Do not use for sensitive traffic.

## License

MIT

