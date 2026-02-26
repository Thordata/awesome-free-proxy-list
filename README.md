# Free Proxy List (Daily Updated)

This repository provides a **free proxy list** that is **automatically updated daily** via GitHub Actions (no server cost).

- **Pipeline**: scrape public proxy sources → validate availability → format outputs → commit updates
- **Target**: global audience, simple formats, easy to consume

## Status

- Last update and counts are auto-filled in the table below.
- Once pushed, you can view this repo at: `https://github.com/Thordata/awesome-free-proxy-list`

## Download

All outputs are generated into the `proxies/` directory:

- `proxies/http.txt`
- `proxies/https.txt`
- `proxies/socks4.txt`
- `proxies/socks5.txt`
- `proxies/all.txt`
- `proxies/summary.json`

## Quick start

- **Download all working proxies (HTTP + HTTPS + SOCKS)**

```bash
curl -s https://raw.githubusercontent.com/Thordata/awesome-free-proxy-list/main/proxies/all.txt | head
```

- **Download only HTTP proxies**

```bash
curl -s https://raw.githubusercontent.com/Thordata/awesome-free-proxy-list/main/proxies/http.txt | head
```

- **Download only HTTPS-capable proxies**

```bash
curl -s https://raw.githubusercontent.com/Thordata/awesome-free-proxy-list/main/proxies/https.txt | head
```

- **Use one proxy in Python `requests`**

```python
import requests

proxy = "http://IP:PORT"  # pick one line from http.txt or https.txt
proxies = {
    "http": proxy,
    "https": proxy,
}

resp = requests.get("https://httpbin.org/ip", proxies=proxies, timeout=10)
print(resp.text)
```

## Stats

<!-- STATS:START -->
Last update (UTC): **2026-02-26T08:00:06+00:00**

| Type | Working | Total Candidates |
|---|---:|---:|
| HTTP | 303 | 2000 |
| HTTPS | 5 | 2000 |
| SOCKS4 | 0 | 2000 |
| SOCKS5 | 0 | 1707 |
| ALL | 303 | 5707 |
<!-- STATS:END -->

## How it works

- Sources are defined in `scripts/sources.txt`
- One script does everything: `scripts/update.py`
- GitHub Actions runs daily and pushes changes if outputs changed

If you want to quickly sanity-check a few proxies from the lists, you can also run:

```bash
python scripts/test_proxies.py --type http --limit 5
```

## Run locally

```bash
python -m venv .venv
source .venv/Scripts/activate  # Windows Git Bash
pip install -r requirements.txt
python scripts/update.py
```

## Disclaimer

Free proxies are often unstable and may be abused by third parties. Use at your own risk. Do not use for sensitive traffic.

### FAQ

- **Why are `socks4.txt` and `socks5.txt` sometimes empty?**  
  Public SOCKS proxies are very unstable. The script only publishes proxies that successfully pass a real HTTP/HTTPS request, so on many runs it is normal to end up with zero working SOCKS proxies.

- **Does it work behind a system proxy or VPN (e.g. Clash / TUN mode)?**  
  Yes, but your traffic will go through your system proxy/VPN first and then through the free proxy (a proxy chain). If your system proxy/VPN IP is blocked by some public proxies or by `httpbin.org`, you may see more failures. For cleaner testing, you can temporarily disable the system proxy while running the tests.

- **Why is `https.txt` non-empty even when HTTPS validation is strict?**  
  Every proxy in `https.txt` has at least passed the HTTP test. In practice most HTTP forward proxies can also handle HTTPS via CONNECT, so when no proxy explicitly passes the HTTPS test, the HTTP-validated list is exposed as HTTPS candidates as well. This avoids an empty `https.txt` while still keeping a reasonable quality bar.

## License

MIT

