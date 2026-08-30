/*
 * QR code generation wrapper.
 *
 * Loads the battle-tested `qrcode-generator` (Kazuhiko Arase, MIT) from CDN at
 * first use, then renders subscription URLs as inline SVG. If the CDN is
 * unreachable (offline / blocked), QR rendering gracefully no-ops and the
 * copy-URL button remains the primary path — QR is a convenience, not a
 * dependency.
 *
 * Usage:  QR.render("https://example.com/sub.yaml").then(svg => el.innerHTML = svg)
 */
(function (global) {
  "use strict";

  const CDN = "https://cdn.jsdelivr.net/npm/qrcode-generator@1.4.4/qrcode.min.js";
  let loader = null;

  function loadLib() {
    if (global.qrcode) return Promise.resolve(global.qrcode);
    if (loader) return loader;
    loader = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = CDN;
      s.onload = () => (global.qrcode ? resolve(global.qrcode) : reject(new Error("qrcode not found")));
      s.onerror = () => reject(new Error("CDN load failed"));
      document.head.appendChild(s);
    });
    return loader;
  }

  function toSvg(qr, opts) {
    const scale = opts.scale || 5;
    const margin = opts.margin == null ? 4 : opts.margin;
    const size = qr.getModuleCount();
    const dim = (size + margin * 2) * scale;
    const dark = opts.dark || "#0f172a";
    const light = opts.light || "#ffffff";
    let rects = "";
    for (let r = 0; r < size; r++) {
      for (let c = 0; c < size; c++) {
        if (qr.isDark(r, c)) {
          rects += `<rect x="${(c + margin) * scale}" y="${(r + margin) * scale}" width="${scale}" height="${scale}" fill="${dark}"/>`;
        }
      }
    }
    return `<svg xmlns="http://www.w3.org/2000/svg" width="${dim}" height="${dim}" viewBox="0 0 ${dim} ${dim}" role="img" aria-label="QR code"><rect width="${dim}" height="${dim}" fill="${light}"/>${rects}</svg>`;
  }

  global.QR = {
    available: false,
    async ensureLoaded() {
      try {
        await loadLib();
        this.available = true;
        return true;
      } catch (e) {
        this.available = false;
        return false;
      }
    },
    async render(text, opts) {
      const ok = await this.ensureLoaded();
      if (!ok) return "";
      // typeNumber 0 = auto-detect; errorCorrectionLevel 'M'.
      const qr = global.qrcode(0, "M");
      qr.addData(text);
      qr.make();
      return toSvg(qr, opts || {});
    },
  };
})(window);
