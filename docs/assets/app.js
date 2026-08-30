/* ===== Free Proxy List Dashboard — app.js ===== */
/* Pure vanilla JS. No dependencies. Data is served as static JSON from ./data/. */
(() => {
  "use strict";

  // ----- Config -----
  const DATA_BASE = "data";
  const TYPES = ["http", "https", "socks4", "socks5"];
  const PAGE_SIZE = 50;
  const MAX_LATENCY_FOR_BAR = 3000; // ms — saturates the latency bar at 100%

  // Country code -> flag emoji (covers all ISO 3166-1 alpha-2).
  const flagEmoji = (cc) => {
    if (!cc || cc === "UNKNOWN" || cc.length !== 2) return "🏳️";
    const cp = [...cc.toUpperCase()].map((c) => 0x1f1e6 + (c.charCodeAt(0) - 65));
    return String.fromCodePoint(...cp);
  };

  // ----- i18n -----
  const I18N = {
    zh: {
      skip: "跳到主内容 / Skip to content",
      brand_sub: "每日自动验证 · 免费代理",
      hero_title: "免费代理列表 · 每日自动验证",
      hero_desc: "聚合 10+ 公开来源，自动验证 HTTP / HTTPS / SOCKS4 / SOCKS5 可用性，标注国家归属与延迟分档。一键搜索、筛选、复制、下载。",
      search_ph: "搜索 IP / 国家 / 端口…",
      type: "类型", country: "国家", tier: "延迟档", anonymity: "匿名度", ip_type: "IP品类", sort: "排序",
      all_types: "全部",
      sort_latency: "延迟（快→慢）", sort_type: "类型", sort_country: "国家",
      copy_all: "复制结果", download: "下载结果",
      th_proxy: "代理 (IP:Port)", th_type: "类型", th_country: "国家",
      th_latency: "延迟", th_tier: "档位", th_anon: "匿名度", th_ip_type: "IP品类", th_actions: "操作",
      loading: "加载中…",
      prev: "上一页", next: "下一页",
      sources_title: "来源构成",
      footer_data: "数据由 GitHub Actions 每日自动验证生成",
      disclaimer_short: "免费代理不稳定且可能被滥用，请勿用于敏感流量。",
      stat_all: "全部可用", stat_updated: "最后更新",
      stat_trusted: "🏆 信任锚点",
      volatility_note: "免费代理存活以小时计，数字随每次验证自然波动；信任锚点 = 快 + 高匿 + 连存≥2天",
      result_count: (n, t) => `共 ${n.toLocaleString()} 条结果（总 ${t.toLocaleString()}）`,
      no_results: "没有匹配的代理。试试调整筛选条件。",
      load_failed: "数据加载失败。请稍后刷新或访问 GitHub raw 文件。",
      copied_one: "已复制：", copied_all: (n) => `已复制 ${n} 条到剪贴板`,
      downloaded: (n) => `已下载 ${n} 条`,
      page_of: (a, b) => `${a} / ${b}`,
      subs_title: "一键导入代理软件",
      subs_intro: "复制订阅链接，粘贴到对应客户端即可导入。Clash Verge / V2RayN / Surge 等通用。",
      subs_guide_title: "📌 各客户端导入步骤（点开查看）",
      subs_copy_url: "复制订阅链接",
      subs_open_raw: "查看原始",
      subs_qr: "二维码",
      subs_qr_fail: "二维码生成失败",
      subs_format_clash: "Clash/Mihomo 配置",
      subs_format_v2ray: "V2Ray base64 订阅",
      subs_format_links: "链接列表",
      subs_copied: "已复制订阅链接",
      subs_load_fail: "订阅列表加载失败",
      risk_title: "安全风险提示",
      risk_body: "免费代理可能由恶意方运营，能窥探甚至篡改你的流量。切勿用于登录、支付或任何敏感操作；仅适合爬虫测试、访问公开信息。详见 README 免责声明。",
      freshness_label: "数据更新于",
      freshness_stale: "（数据可能已过期，免费代理存活以分钟/小时计）",
      detail_country: "国家", detail_latency: "延迟", detail_tier: "档位",
      detail_anon: "匿名度", detail_streak: "连续存活", detail_source: "来源",
      detail_check_curl: "复制 cURL 检测命令",
      detail_check_py: "复制 Python 检测命令",
      detail_check_hint: "在本地终端运行，实时验证该代理当下是否可用（浏览器无法直接测代理，须本地执行）。",
      copied_check: "已复制检测命令",
      sources_title: "来源构成",
      chart_anon: "匿名度分布",
      chart_country: "国家 Top 10",
    },
    en: {
      skip: "Skip to content",
      brand_sub: "Daily auto-verified · Free proxies",
      hero_title: "Free Proxy List · Daily Verified",
      hero_desc: "Aggregates 10+ public sources, auto-verifies HTTP / HTTPS / SOCKS4 / SOCKS5 availability, with GeoIP country and latency tiers. Search, filter, copy, download.",
      search_ph: "Search IP / country / port…",
      type: "Type", country: "Country", tier: "Latency", anonymity: "Anonymity", ip_type: "IP type", sort: "Sort",
      all_types: "All",
      sort_latency: "Latency (fast→slow)", sort_type: "Type", sort_country: "Country",
      copy_all: "Copy results", download: "Download",
      th_proxy: "Proxy (IP:Port)", th_type: "Type", th_country: "Country",
      th_latency: "Latency", th_tier: "Tier", th_anon: "Anonymity", th_ip_type: "IP type", th_actions: "Actions",
      loading: "Loading…",
      prev: "Prev", next: "Next",
      sources_title: "Source breakdown",
      footer_data: "Data is auto-verified daily by GitHub Actions",
      disclaimer_short: "Free proxies are unstable and may be abused. Do not use for sensitive traffic.",
      stat_all: "Working", stat_updated: "Last update",
      stat_trusted: "🏆 Top trusted",
      volatility_note: "Free proxies live for hours, so counts fluctuate each verification; top trusted = fast + elite + streak≥2d",
      result_count: (n, t) => `${n.toLocaleString()} of ${t.toLocaleString()} proxies`,
      no_results: "No matching proxies. Try adjusting the filters.",
      load_failed: "Failed to load data. Please refresh later or use the GitHub raw files.",
      copied_one: "Copied: ", copied_all: (n) => `Copied ${n} proxies to clipboard`,
      downloaded: (n) => `Downloaded ${n} proxies`,
      page_of: (a, b) => `${a} / ${b}`,
      subs_title: "Import into proxy clients",
      subs_intro: "Copy a subscription URL and paste it into the matching client. Works with Clash Verge / V2RayN / Surge etc.",
      subs_guide_title: "📌 Import steps per client (click to expand)",
      subs_copy_url: "Copy subscription URL",
      subs_open_raw: "View raw",
      subs_qr: "QR code",
      subs_qr_fail: "QR code generation failed",
      subs_format_clash: "Clash/Mihomo config",
      subs_format_v2ray: "V2Ray base64 subscription",
      subs_format_links: "Link list",
      subs_copied: "Subscription URL copied",
      subs_load_fail: "Failed to load subscription list",
      risk_title: "Security risk warning",
      risk_body: "Free proxies may be operated by malicious parties who can inspect or tamper with your traffic. Never use them for logins, payments, or sensitive operations — only for crawler testing and public info. See the README disclaimer.",
      freshness_label: "Data updated",
      freshness_stale: "(data may be stale; free proxies live for minutes-to-hours)",
      detail_country: "Country", detail_latency: "Latency", detail_tier: "Tier",
      detail_anon: "Anonymity", detail_streak: "Streak", detail_source: "Source",
      detail_check_curl: "Copy cURL check command",
      detail_check_py: "Copy Python check command",
      detail_check_hint: "Run in a local terminal to verify this proxy live (browsers cannot test proxies directly).",
      copied_check: "Check command copied",
      sources_title: "Source breakdown",
      chart_anon: "Anonymity distribution",
      chart_country: "Country Top 10",
    },
  };

  // ----- State -----
  let allProxies = [];
  let filtered = [];
  let summary = null;
  let subsManifest = null;
  let countries = [];
  let page = 1;
  let lang = localStorage.getItem("fpl-lang") || (navigator.language.startsWith("zh") ? "zh" : "en");
  let theme = localStorage.getItem("fpl-theme") || "dark";

  // ----- DOM refs -----
  const $ = (sel) => document.querySelector(sel);
  const el = {
    html: document.documentElement,
    body: document.body,
    search: $("#search"),
    typeFilter: $("#typeFilter"),
    countryFilter: $("#countryFilter"),
    tierFilter: $("#tierFilter"),
    anonFilter: $("#anonFilter"),
    ipTypeFilter: $("#ipTypeFilter"),
    sortBy: $("#sortBy"),
    copyBtn: $("#copyBtn"),
    downloadBtn: $("#downloadBtn"),
    body: $("#proxyBody"),
    loadingCell: $("#loadingCell"),
    resultCount: $("#resultCount"),
    pagination: $("#pagination"),
    prevBtn: $("#prevBtn"),
    nextBtn: $("#nextBtn"),
    pageInfo: $("#pageInfo"),
    heroStats: $("#heroStats"),
    lastUpdate: $("#lastUpdate"),
    sourcesSection: $("#sourcesSection"),
    sourceBars: $("#sourceBars"),
    chartsSection: $("#chartsSection"),
    anonChart: $("#anonChart"),
    countryChart: $("#countryChart"),
    subsSection: $("#subsSection"),
    subsGrid: $("#subsGrid"),
    subsGuideBody: $("#subsGuideBody"),
    riskBanner: $("#riskBanner"),
    riskClose: $("#riskClose"),
    toast: $("#toast"),
    langToggle: $("#langToggle"),
    langLabel: $("#langLabel"),
    themeToggle: $("#themeToggle"),
    themeIcon: $("#themeIcon"),
  };

  // ----- i18n apply -----
  function t(key, ...args) {
    const v = I18N[lang][key];
    return typeof v === "function" ? v(...args) : v;
  }
  function applyI18n() {
    el.html.setAttribute("data-lang", lang);
    el.html.lang = lang === "zh" ? "zh-CN" : "en";
    document.querySelectorAll("[data-i18n]").forEach((node) => {
      const key = node.getAttribute("data-i18n");
      const val = I18N[lang][key];
      if (typeof val === "string") node.textContent = val;
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((node) => {
      const key = node.getAttribute("data-i18n-placeholder");
      const val = I18N[lang][key];
      if (typeof val === "string") node.setAttribute("placeholder", val);
    });
    el.langLabel.textContent = lang === "zh" ? "EN" : "中";
    el.themeIcon.textContent = theme === "dark" ? "☀️" : "🌙";
    // Re-render dynamic text (count etc.)
    renderCount();
    if (summary) renderHero();
  }

  // ----- Theme -----
  function applyTheme() {
    el.html.setAttribute("data-theme", theme);
    el.themeIcon.textContent = theme === "dark" ? "☀️" : "🌙";
    localStorage.setItem("fpl-theme", theme);
  }

  // ----- Toast -----
  let toastTimer;
  function toast(msg) {
    el.toast.textContent = msg;
    el.toast.hidden = false;
    requestAnimationFrame(() => el.toast.classList.add("show"));
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      el.toast.classList.remove("show");
      setTimeout(() => { el.toast.hidden = true; }, 200);
    }, 2200);
  }

  // ----- Data loading -----
  async function fetchJSON(path) {
    const r = await fetch(path, { cache: "no-store" });
    if (!r.ok) throw new Error(`${path} -> ${r.status}`);
    return r.json();
  }

  async function load() {
    try {
      summary = await fetchJSON(`${DATA_BASE}/summary.json`);
      // Load all types + subscriptions in parallel.
      const [data, subsManifestResp] = await Promise.all([
        Promise.all(TYPES.map((tp) => fetchJSON(`${DATA_BASE}/${tp}.json`).catch(() => []))),
        fetchJSON(`${DATA_BASE}/subscriptions.json`).catch(() => null),
      ]);
      allProxies = [];
      TYPES.forEach((tp, i) => {
        (data[i] || []).forEach((p) => allProxies.push({ ...p, type: p.type || tp }));
      });
      // Build country list from loaded data.
      const ccSet = new Set();
      allProxies.forEach((p) => ccSet.add(p.country_code || "UNKNOWN"));
      countries = [...ccSet].sort();
      subsManifest = subsManifestResp;
      renderHero();
      renderCountryFilter();
      renderSources();
      renderCharts();
      renderSubs();
      restoreHash();
      applyFilters();
    } catch (e) {
      console.error(e);
      el.body.innerHTML = `<tr class="empty-row"><td colspan="8">${t("load_failed")}</td></tr>`;
    }
  }

  // ----- Render: hero stats -----
  function renderHero() {
    if (!summary) return;
    const c = summary.counts || {};
    // Freshness: show update time + a stale warning if older than 30 hours.
    const ageHours = (Date.now() - new Date(summary.updated_utc).getTime()) / 3.6e6;
    const stale = !isNaN(ageHours) && ageHours > 30;
    el.lastUpdate.textContent = `${t("freshness_label")}: ${formatDate(summary.updated_utc)}`;
    el.lastUpdate.classList.toggle("chip-warn", stale);
    el.lastUpdate.title = stale ? t("freshness_stale") : "";
    if (stale) {
      el.lastUpdate.textContent += " ⚠";
    }
    const cards = [
      { cls: "is-all", num: (c.all && c.all.working) || 0, lbl: t("stat_all") },
      { cls: "is-trusted", num: (c.all && c.all.top_trusted) || 0, lbl: t("stat_trusted") },
      { cls: "is-http", num: (c.http && c.http.working) || 0, lbl: "HTTP" },
      { cls: "is-https", num: (c.https && c.https.working) || 0, lbl: "HTTPS" },
      { cls: "is-socks4", num: (c.socks4 && c.socks4.working) || 0, lbl: "SOCKS4" },
      { cls: "is-socks5", num: (c.socks5 && c.socks5.working) || 0, lbl: "SOCKS5" },
    ];
    el.heroStats.innerHTML = cards
      .map((s) => `<div class="stat-card ${s.cls}"><div class="num">${s.num.toLocaleString()}</div><span class="lbl">${s.lbl}</span></div>`)
      .join("");
    // Volatility note: tell users counts fluctuate by nature, not because the list is broken.
    let note = el.heroStats.nextElementSibling;
    if (!note || !note.classList.contains("volatility-note")) {
      note = document.createElement("div");
      note.className = "volatility-note";
      el.heroStats.after(note);
    }
    note.textContent = t("volatility_note");
  }

  function renderCountryFilter() {
    const cur = el.countryFilter.value || "all";
    const opts = [`<option value="all">${t("all_types")}</option>`]
      .concat(
        countries
          .filter((cc) => cc !== "UNKNOWN")
          .map((cc) => `<option value="${cc}">${flagEmoji(cc)} ${cc}</option>`)
      )
      .concat(countries.includes("UNKNOWN") ? [`<option value="UNKNOWN">🏳️ ?</option>`] : []);
    el.countryFilter.innerHTML = opts.join("");
    el.countryFilter.value = cur;
  }

  // ----- Render: source breakdown -----
  function renderSources() {
    if (!summary || !summary.sources || !summary.sources.per_source_candidates) {
      el.sourcesSection.hidden = true;
      return;
    }
    const entries = Object.entries(summary.sources.per_source_candidates);
    if (!entries.length) { el.sourcesSection.hidden = true; return; }
    el.sourcesSection.hidden = false;
    const max = Math.max(...entries.map(([, n]) => n), 1);
    el.sourceBars.innerHTML = entries
      .map(([url, n]) => {
        const pct = Math.max(2, Math.round((n / max) * 100));
        const short = url.replace("https://raw.githubusercontent.com/", "");
        return `<div class="source-row">
          <div class="source-bar-track">
            <div class="source-bar-fill" style="width:${pct}%"></div>
            <span class="src-label" title="${url}">${short}</span>
          </div>
          <span class="src-count">${n.toLocaleString()}</span>
        </div>`;
      })
      .join("");
  }

  // ----- Render: distribution charts (anonymity + country) -----
  function renderCharts() {
    if (!summary) { el.chartsSection.hidden = true; return; }
    const anon = (summary.by_anonymity && summary.by_anonymity.all) || {};
    const country = (summary.by_country && summary.by_country.all) || {};

    const anonRows = Object.entries(anon).sort((a, b) => b[1] - a[1]);
    const anonMax = Math.max(...anonRows.map(([, n]) => n), 1);
    const anonMeta = {
      elite: { icon: "🟢", zh: "高匿", en: "elite" },
      anonymous: { icon: "🟡", zh: "匿名", en: "anonymous" },
      transparent: { icon: "🔴", zh: "透明", en: "transparent" },
      unknown: { icon: "⚪", zh: "未测", en: "unknown" },
    };
    if (!anonRows.length) {
      el.anonChart.innerHTML = `<span class="muted">—</span>`;
    } else {
      el.anonChart.innerHTML = anonRows.map(([k, n]) => {
        const m = anonMeta[k] || { icon: "•", zh: k, en: k };
        const lbl = lang === "zh" ? m.zh : m.en;
        const pct = Math.max(2, Math.round((n / anonMax) * 100));
        return `<div class="chart-row">
          <span class="chart-label">${m.icon} ${escapeHtml(lbl)}</span>
          <div class="chart-track"><div class="chart-fill" style="width:${pct}%"></div></div>
          <span class="chart-count">${n.toLocaleString()}</span>
        </div>`;
      }).join("");
    }

    const ccRows = Object.entries(country).filter(([cc]) => cc && cc !== "UNKNOWN").sort((a, b) => b[1] - a[1]).slice(0, 10);
    const ccMax = Math.max(...ccRows.map(([, n]) => n), 1);
    if (!ccRows.length) {
      el.countryChart.innerHTML = `<span class="muted">—</span>`;
    } else {
      el.countryChart.innerHTML = ccRows.map(([cc, n]) => {
        const pct = Math.max(2, Math.round((n / ccMax) * 100));
        return `<div class="chart-row">
          <span class="chart-label">${flagEmoji(cc)} ${escapeHtml(cc)}</span>
          <div class="chart-track"><div class="chart-fill chart-fill-accent" style="width:${pct}%"></div></div>
          <span class="chart-count">${n.toLocaleString()}</span>
        </div>`;
      }).join("");
    }
    el.chartsSection.hidden = false;
  }

  // ----- Render: subscription center -----
  function renderSubs() {
    const manifest = subsManifest;
    if (!manifest || !manifest.subscriptions || !manifest.subscriptions.length) {
      el.subsSection.hidden = true;
      return;
    }
    el.subsSection.hidden = false;

    const formatLabel = (fmt) =>
      fmt === "clash" ? t("subs_format_clash") : fmt === "v2ray" ? t("subs_format_v2ray") : t("subs_format_links");
    const formatIcon = (fmt) => (fmt === "clash" ? "🌀" : fmt === "v2ray" ? "📡" : "🔗");

    // Group subscriptions by category for a cleaner layout.
    const cats = manifest.categories || { all: { zh: "全部", en: "All" } };
    const catOrder = ["all", "by_type", "by_tier", "by_anon", "stable"];
    const byCat = {};
    manifest.subscriptions.forEach((s) => {
      const c = s.category || "all";
      (byCat[c] = byCat[c] || []).push(s);
    });

    const cardHtml = (s) => {
      const name = lang === "zh" ? s.name : (s.name_en || s.name);
      const url = s.pages || s.raw || "";
      const escUrl = escapeAttr(url);
      return `<div class="sub-card" data-format="${s.format}">
        <div class="sub-head">
          <span class="sub-icon">${formatIcon(s.format)}</span>
          <div class="sub-meta">
            <strong>${escapeHtml(name)}</strong>
            <small>${formatLabel(s.format)} · ${s.path}</small>
          </div>
        </div>
        <code class="sub-url" title="${escUrl}">${escUrl}</code>
        <div class="sub-actions">
          <button class="btn btn-primary btn-sm" data-sub-copy="${escUrl}" type="button">
            📋 <span>${t("subs_copy_url")}</span>
          </button>
          <a class="btn btn-ghost btn-sm" href="${escUrl}" target="_blank" rel="noopener">
            ↗ <span>${t("subs_open_raw")}</span>
          </a>
          <button class="btn btn-ghost btn-sm sub-qr-btn" data-sub-qr="${escUrl}" type="button">
            📱 <span>${t("subs_qr")}</span>
          </button>
        </div>
        <div class="sub-qr" hidden></div>
      </div>`;
    };

    el.subsGrid.innerHTML = catOrder
      .filter((c) => byCat[c] && byCat[c].length)
      .map((c) => {
        const label = (cats[c] && cats[c][lang]) || c;
        return `<div class="sub-cat">
          <h3 class="sub-cat-title">${escapeHtml(label)}</h3>
          <div class="sub-cat-grid">${byCat[c].map(cardHtml).join("")}</div>
        </div>`;
      })
      .join("");

    // Import guides.
    if (manifest.import_guides) {
      const g = manifest.import_guides;
      const guides = lang === "zh"
        ? [["Clash Verge", g.clash_verge], ["V2RayN", g.v2rayn], ["Surge", g.surge]]
        : [["Clash Verge", g.clash_verge_en || g.clash_verge], ["V2RayN", g.v2rayn], ["Surge", g.surge]];
      el.subsGuideBody.innerHTML = guides
        .map(([client, text]) => `<p><strong>${client}:</strong> ${escapeHtml(text || "")}</p>`)
        .join("");
    }
  }

  // ----- Filtering / sorting -----
  function applyFilters() {
    const q = el.search.value.trim().toLowerCase();
    const type = el.typeFilter.value;
    const cc = el.countryFilter.value;
    const tier = el.tierFilter.value;
    const anon = el.anonFilter.value;
    const ipType = el.ipTypeFilter.value;
    const sort = el.sortBy.value;

    filtered = allProxies.filter((p) => {
      if (type !== "all" && p.type !== type) return false;
      if (cc !== "all" && (p.country_code || "UNKNOWN") !== cc) return false;
      if (tier !== "all" && tierOf(p) !== tier) return false;
      if (anon !== "all" && (p.anonymity || "unknown") !== anon) return false;
      if (ipType !== "all" && (p.ip_type || "unknown") !== ipType) return false;
      if (q) {
        const hay = `${p.ip}:${p.port} ${p.country || ""} ${p.country_code || ""} ${p.type}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    const tierRank = { fast: 0, medium: 1, slow: 2, unknown: 3 };
    if (sort === "latency") {
      filtered.sort((a, b) => (a.latency_ms ?? 1e9) - (b.latency_ms ?? 1e9));
    } else if (sort === "type") {
      filtered.sort((a, b) => a.type.localeCompare(b.type) || (a.latency_ms ?? 1e9) - (b.latency_ms ?? 1e9));
    } else if (sort === "country") {
      filtered.sort((a, b) => (a.country_code || "ZZ").localeCompare(b.country_code || "ZZ") || (a.latency_ms ?? 1e9) - (b.latency_ms ?? 1e9));
    }
    page = 1;
    renderTable();
    syncHash();
  }

  // ----- URL deep-linking (share filter state via location.hash) -----
  function syncHash() {
    const params = new URLSearchParams();
    if (el.typeFilter.value !== "all") params.set("type", el.typeFilter.value);
    if (el.countryFilter.value !== "all") params.set("cc", el.countryFilter.value);
    if (el.tierFilter.value !== "all") params.set("tier", el.tierFilter.value);
    if (el.anonFilter.value !== "all") params.set("anon", el.anonFilter.value);
    if (el.ipTypeFilter.value !== "all") params.set("iptype", el.ipTypeFilter.value);
    const q = el.search.value.trim();
    if (q) params.set("q", q);
    const hash = params.toString();
    const newHash = hash ? `#${hash}` : "";
    if (location.hash !== newHash) {
      history.replaceState(null, "", newHash || location.pathname);
    }
  }

  function restoreHash() {
    const hash = location.hash.replace(/^#/, "");
    if (!hash) return;
    const params = new URLSearchParams(hash);
    if (params.has("type")) el.typeFilter.value = params.get("type");
    if (params.has("cc")) el.countryFilter.value = params.get("cc");
    if (params.has("tier")) el.tierFilter.value = params.get("tier");
    if (params.has("anon")) el.anonFilter.value = params.get("anon");
    if (params.has("iptype")) el.ipTypeFilter.value = params.get("iptype");
    if (params.has("q")) el.search.value = params.get("q");
  }

  function tierOf(p) {
    if (p.latency_ms == null) return "unknown";
    if (p.latency_ms < 500) return "fast";
    if (p.latency_ms < 2000) return "medium";
    return "slow";
  }

  // Anonymity badge: green=elite (safest), yellow=anonymous, red=transparent (leaks IP).
  function anonBadgeHtml(level) {
    const map = {
      elite: { icon: "🟢", cls: "anon-elite", lbl: "高匿", lbl_en: "elite" },
      anonymous: { icon: "🟡", cls: "anon-anon", lbl: "匿名", lbl_en: "anon" },
      transparent: { icon: "🔴", cls: "anon-trans", lbl: "透明", lbl_en: "transparent" },
      unknown: { icon: "⚪", cls: "anon-unknown", lbl: "未测", lbl_en: "unknown" },
    };
    const m = map[level] || map.unknown;
    const lbl = lang === "zh" ? m.lbl : m.lbl_en;
    return `<span class="anon-badge ${m.cls}" title="${escapeHtml(m.lbl_en)}">${m.icon} ${lbl}</span>`;
  }

  function ipTypeBadgeHtml(ipType) {
    const map = {
      datacenter: { icon: "🏢", cls: "iptype-dc", lbl: "数据中心", lbl_en: "datacenter" },
      residential: { icon: "🏠", cls: "iptype-res", lbl: "住宅", lbl_en: "residential" },
      unknown: { icon: "⚪", cls: "iptype-unknown", lbl: "未知", lbl_en: "unknown" },
    };
    const m = map[ipType] || map.unknown;
    const lbl = lang === "zh" ? m.lbl : m.lbl_en;
    return `<span class="anon-badge ${m.cls}" title="${escapeHtml(m.lbl_en)}">${m.icon} ${lbl}</span>`;
  }

  // Shorten a source URL to something readable (host + path tail).
  function shortSource(src) {
    if (!src) return "—";
    try {
      const u = new URL(src);
      const host = u.hostname.replace(/^raw\./, "").replace(/^(raw\.githubusercontent\.com)$/, "github");
      return host.length > 28 ? host.slice(0, 26) + "…" : host;
    } catch {
      return src.length > 28 ? src.slice(0, 26) + "…" : src;
    }
  }

  // ----- Render: table -----
  function renderTable() {
    renderCount();
    if (!filtered.length) {
      el.body.innerHTML = `<tr class="empty-row"><td colspan="9">${t("no_results")}</td></tr>`;
      el.pagination.hidden = true;
      return;
    }
    const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
    if (page > totalPages) page = totalPages;
    const start = (page - 1) * PAGE_SIZE;
    const slice = filtered.slice(start, start + PAGE_SIZE);

    el.body.innerHTML = slice
      .map((p, i) => {
        const idx = start + i + 1;
        const hp = `${p.ip}:${p.port}`;
        const tier = tierOf(p);
        const lat = p.latency_ms != null ? `${Math.round(p.latency_ms)}ms` : "—";
        const barPct = p.latency_ms != null ? Math.min(100, (p.latency_ms / MAX_LATENCY_FOR_BAR) * 100) : 0;
        const barColor = tier === "fast" ? "var(--fast)" : tier === "medium" ? "var(--medium)" : tier === "slow" ? "var(--slow)" : "var(--unknown)";
        const cc = p.country_code || "UNKNOWN";
        const cname = p.country || (cc === "UNKNOWN" ? "?" : cc);
        const copyStr = escapeAttr(hp);
        const anon = p.anonymity || "unknown";
        const anonBadge = anonBadgeHtml(anon);
        const ipTypeBadge = ipTypeBadgeHtml(p.ip_type || "unknown");
        const proxyUrl = p.type === "socks5" ? `socks5://${hp}` : (p.type === "socks4" ? `socks4://${hp}` : `http://${hp}`);
        const curlCmd = `curl -x ${proxyUrl} -s --max-time 10 https://httpbin.org/ip`;
        const pyCmd = `python scripts/check.py ${hp}`;
        const dataIdx = start + i;
        return `<tr class="proxy-row" data-idx="${dataIdx}">
          <td class="idx">${idx}</td>
          <td class="hp">${hp}</td>
          <td><span class="badge badge-${p.type}">${p.type.toUpperCase()}</span></td>
          <td><span class="country"><span class="flag">${flagEmoji(cc)}</span>${escapeHtml(cname)}</span></td>
          <td><span class="latency">${lat}<span class="latency-bar"><i style="width:${barPct}%;background:${barColor}"></i></span></span></td>
          <td><span class="tier-dot tier-${tier}">${tier}</span></td>
          <td>${anonBadge}</td>
          <td>${ipTypeBadge}</td>
          <td class="row-actions">
            <button class="copy-one" data-copy="${copyStr}" type="button" title="${t("copy_all")}">📋</button>
            <button class="detail-toggle" data-detail="${dataIdx}" type="button" title="…">ℹ️</button>
          </td>
        </tr>
        <tr class="detail-row" data-detail-for="${dataIdx}" hidden>
          <td colspan="9">
            <div class="detail-grid">
              <div><span class="muted">${t("detail_country")}</span><strong>${flagEmoji(cc)} ${escapeHtml(cname)} (${escapeHtml(cc)})</strong></div>
              <div><span class="muted">${t("detail_latency")}</span><strong>${lat}</strong></div>
              <div><span class="muted">${t("detail_tier")}</span><strong>${tier}</strong></div>
              <div><span class="muted">${t("detail_anon")}</span><strong>${anonBadge}</strong></div>
              <div><span class="muted">${t("detail_streak")}</span><strong>${p.streak || 0} day(s)</strong></div>
              <div><span class="muted">${t("detail_source")}</span><strong class="detail-src" title="${escapeHtml(p.source || "")}">${escapeHtml(shortSource(p.source))}</strong></div>
            </div>
            <p class="detail-hint muted">💡 ${t("detail_check_hint")}</p>
            <div class="detail-cmds">
              <code class="detail-code">curl: ${escapeHtml(curlCmd)}</code>
              <div class="detail-cmd-actions">
                <button class="btn btn-ghost btn-sm" data-copy-cmd="${escapeAttr(curlCmd)}" type="button">📋 ${t("detail_check_curl")}</button>
                <button class="btn btn-ghost btn-sm" data-copy-cmd="${escapeAttr(pyCmd)}" type="button">📋 ${t("detail_check_py")}</button>
              </div>
            </div>
          </td>
        </tr>`;
      })
      .join("");

    // Pagination state
    el.pagination.hidden = totalPages <= 1;
    el.pageInfo.textContent = t("page_of", page, totalPages);
    el.prevBtn.disabled = page <= 1;
    el.nextBtn.disabled = page >= totalPages;
  }

  function renderCount() {
    el.resultCount.textContent = t("result_count", filtered.length, allProxies.length);
  }

  // ----- Helpers -----
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function escapeAttr(s) { return escapeHtml(s); }
  function formatDate(iso) {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      return d.toLocaleString(lang === "zh" ? "zh-CN" : "en-US", { dateStyle: "medium", timeStyle: "short" });
    } catch { return iso; }
  }

  // ----- Actions -----
  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); return true; }
    catch {
      // Fallback for non-secure contexts
      const ta = document.createElement("textarea");
      ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); } catch {}
      document.body.removeChild(ta);
      return true;
    }
  }

  function filteredHostports() {
    return filtered.map((p) => `${p.ip}:${p.port}`).join("\n");
  }

  async function onCopyAll() {
    if (!filtered.length) return;
    const ok = await copyText(filteredHostports());
    if (ok) toast(t("copied_all", filtered.length));
  }

  function onDownload() {
    if (!filtered.length) return;
    const lines = filteredHostports();
    const blob = new Blob([lines + "\n"], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `proxies-${Date.now()}.txt`;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
    toast(t("downloaded", filtered.length));
  }

  async function onCopyOne(e) {
    const btn = e.target.closest("[data-copy]");
    if (!btn) return;
    const val = btn.getAttribute("data-copy");
    const ok = await copyText(val);
    if (ok) toast(t("copied_one") + val);
  }

  function onToggleDetail(e) {
    const btn = e.target.closest("[data-detail]");
    if (!btn) return;
    const idx = btn.getAttribute("data-detail");
    const row = btn.closest("tr").nextElementSibling;
    if (!row || row.getAttribute("data-detail-for") !== idx) return;
    const open = !row.hidden;
    // Close all other open detail rows (single-open policy).
    el.body.querySelectorAll("tr.detail-row:not([hidden])").forEach((r) => { r.hidden = true; });
    if (!open) row.hidden = false;
  }

  async function onCopyCmd(e) {
    const btn = e.target.closest("[data-copy-cmd]");
    if (!btn) return;
    const val = btn.getAttribute("data-copy-cmd");
    const ok = await copyText(val);
    if (ok) toast(t("copied_check"));
  }

  async function onCopySub(e) {
    const btn = e.target.closest("[data-sub-copy]");
    if (!btn) return;
    const val = btn.getAttribute("data-sub-copy");
    const ok = await copyText(val);
    if (ok) toast(t("subs_copied"));
  }

  async function onToggleQR(e) {
    const btn = e.target.closest("[data-sub-qr]");
    if (!btn || !globalThis.QR) return;
    const url = btn.getAttribute("data-sub-qr");
    const card = btn.closest(".sub-card");
    const box = card && card.querySelector(".sub-qr");
    if (!box) return;
    if (!box.hidden && box.dataset.rendered === "1") {
      box.hidden = true; box.innerHTML = "";
      box.dataset.rendered = "";
      return;
    }
    box.innerHTML = `<span class="muted">…</span>`;
    box.hidden = false;
    const svg = await globalThis.QR.render(url, { scale: 5, margin: 2 });
    if (!svg) {
      box.innerHTML = `<span class="muted">${t("subs_qr_fail")}</span>`;
      box.dataset.rendered = "0";
      return;
    }
    box.innerHTML = svg;
    box.dataset.rendered = "1";
  }

  // ----- Event wiring -----
  function bind() {
    // Risk banner: dismissible, remembered per-browser.
    if (localStorage.getItem("fpl-risk-dismissed") === "1") {
      el.riskBanner.hidden = true;
    }
    el.riskClose.addEventListener("click", () => {
      el.riskBanner.hidden = true;
      localStorage.setItem("fpl-risk-dismissed", "1");
    });
    el.search.addEventListener("input", debounce(applyFilters, 150));
    el.typeFilter.addEventListener("change", applyFilters);
    el.countryFilter.addEventListener("change", applyFilters);
    el.tierFilter.addEventListener("change", applyFilters);
    el.anonFilter.addEventListener("change", applyFilters);
    el.ipTypeFilter.addEventListener("change", applyFilters);
    el.sortBy.addEventListener("change", applyFilters);
    el.copyBtn.addEventListener("click", onCopyAll);
    el.downloadBtn.addEventListener("click", onDownload);
    el.body.addEventListener("click", onCopyOne);
    el.body.addEventListener("click", onToggleDetail);
    el.body.addEventListener("click", onCopyCmd);
    el.subsGrid.addEventListener("click", onCopySub);
    el.subsGrid.addEventListener("click", onToggleQR);
    el.prevBtn.addEventListener("click", () => { if (page > 1) { page--; renderTable(); } });
    el.nextBtn.addEventListener("click", () => {
      const total = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
      if (page < total) { page++; renderTable(); }
    });
    el.langToggle.addEventListener("click", () => {
      lang = lang === "zh" ? "en" : "zh";
      localStorage.setItem("fpl-lang", lang);
      applyI18n();
      renderCountryFilter();
      renderCharts();
      renderSubs();
    });
    el.themeToggle.addEventListener("click", () => {
      theme = theme === "dark" ? "light" : "dark";
      applyTheme();
    });
    // Keyboard: "/" focuses search, "Esc" clears it.
    document.addEventListener("keydown", (e) => {
      if (e.key === "/" && document.activeElement !== el.search) {
        e.preventDefault(); el.search.focus();
      } else if (e.key === "Escape" && document.activeElement === el.search) {
        el.search.value = ""; applyFilters(); el.search.blur();
      }
    });
  }

  function debounce(fn, ms) {
    let id;
    return (...args) => { clearTimeout(id); id = setTimeout(() => fn(...args), ms); };
  }

  // ----- Init -----
  function init() {
    applyTheme();
    applyI18n();
    bind();
    load();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
