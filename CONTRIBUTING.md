# 贡献指南 · Contributing

中文 · [English](#english)

感谢你有兴趣为 awesome-free-proxy-list 做贡献！⭐ Star 是最简单的支持方式。

## 🙋 贡献方式

- **新增代理来源** — 在 `scripts/sources.txt` 加一行 `<raw_url> <type>`，type 为 `http|https|socks4|socks5|mixed`
- **改进验证逻辑** — `scripts/update.py`（延迟测量、并发、超时等）
- **完善仪表盘** — `docs/index.html` / `docs/assets/*`（纯静态，无构建）
- **修复 bug / 完善文档** — 任意文件

## 🚀 本地开发流程

```bash
git clone https://github.com/kael-odin/awesome-free-proxy-list.git
cd awesome-free-proxy-list
git checkout -b my-feature

python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements.txt

# 小规模试跑，避免长时间等待
PROXY_MAX_PER_TYPE=50 PROXY_CONCURRENCY=50 python scripts/update.py

# 单代理诊断
python scripts/check.py 1.2.3.4:8080

# 本地预览仪表盘
cd docs && python -m http.server 8088
```

## ✅ 提交前检查

- [ ] `python -m py_compile scripts/*.py` 语法通过
- [ ] 小规模 `update.py` 能跑通且产出 `proxies/json/*.json`、`docs/data/summary.json`
- [ ] 仪表盘本地预览正常（搜索/筛选/主题/语言切换）
- [ ] commit message 简洁（`feat:` / `fix:` / `docs:` / `chore:` 前缀）
- [ ] **不要**提交 `.venv/`、`scripts/data/`（本地 mmdb 缓存）或全量代理数据之外的大文件

## 📝 新增来源的注意事项

- 必须是公开可访问的 raw 文本（`ip:port` 一行一个）
- 标注正确 type；`mixed` 表示可能同时支持 HTTP/HTTPS 的正向代理
- 来源失效会被 `update.py` 容错跳过，不影响主链路
- 不接受来源：付费墙、需登录、明确禁止抓取的站点

## 🧭 PR 流程

1. Fork → 新建分支 → 提交 → 发起 PR 到 `main`
2. CI（`test.yml`）会自动跑 lint + 烟测
3. 等待 review，合并后次日 `update.yml` 运行即生效

---

## English

Thanks for your interest in contributing! The simplest support is ⭐ Starring the repo.

### Ways to contribute

- **Add proxy sources** — append `<raw_url> <type>` to `scripts/sources.txt` (`http|https|socks4|socks5|mixed`)
- **Improve validation** — latency measurement, concurrency, timeouts in `scripts/update.py`
- **Polish the dashboard** — `docs/index.html` / `docs/assets/*` (pure static, no build step)
- **Fix bugs / docs** — anything

### Local dev

```bash
git clone https://github.com/kael-odin/awesome-free-proxy-list.git
cd awesome-free-proxy-list && git checkout -b my-feature
python -m venv .venv && source .venv/bin/activate   # Windows: source .venv/Scripts/activate
pip install -r requirements.txt
PROXY_MAX_PER_TYPE=50 PROXY_CONCURRENCY=50 python scripts/update.py   # small run
python scripts/check.py 1.2.3.4:8080
cd docs && python -m http.server 8088   # preview dashboard
```

### Pre-merge checklist

- [ ] `python -m py_compile scripts/*.py` passes
- [ ] Small `update.py` run produces `proxies/json/*.json` and `docs/data/summary.json`
- [ ] Dashboard previews correctly (search/filter/theme/lang)
- [ ] Concise commit messages (`feat:` / `fix:` / `docs:` / `chore:`)
- [ ] **Do not** commit `.venv/`, `scripts/data/` (local mmdb), or large non-data files

### Source guidelines

- Must be publicly accessible raw text (`ip:port`, one per line)
- Tag the correct type; `mixed` = forward proxy that may also do HTTPS via CONNECT
- Dead sources are skipped gracefully; they won't break the pipeline
- Not accepted: paywalled, login-required, or explicitly scrape-forbidden sites

### PR flow

1. Fork → branch → commit → open a PR against `main`
2. CI (`test.yml`) runs lint + smoke automatically
3. After merge, the next `update.yml` run picks it up
