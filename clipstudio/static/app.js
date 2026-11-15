/* Shared helpers: API calls, SSE events, toasts, notification sound. */
(function () {
  const listeners = {};
  const CS = (window.CS = {
    on(evt, fn) { (listeners[evt] = listeners[evt] || []).push(fn); },
    async api(method, url, body) {
      const opts = { method, headers: {} };
      if (body instanceof FormData) opts.body = body;
      else if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
      const r = await fetch(url, opts);
      const text = await r.text();
      let data; try { data = text ? JSON.parse(text) : {}; } catch (e) { data = { raw: text }; }
      if (!r.ok) throw new Error((data && (data.error || data.detail)) || `Request failed (${r.status})`);
      return data;
    },
    toast(msg, kind = "info", ms = 5000, href) {
      const box = document.getElementById("toasts");
      const el = document.createElement(href ? "a" : "div");
      el.className = "toast " + kind;
      if (href) el.href = href;
      el.textContent = msg;
      box.appendChild(el);
      setTimeout(() => el.classList.add("out"), ms);
      setTimeout(() => el.remove(), ms + 400);
    },
    beep() {
      try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        [0, 0.12, 0.24].forEach((t, i) => {
          const o = ctx.createOscillator(), g = ctx.createGain();
          o.type = "sine"; o.frequency.value = [880, 1175, 1568][i];
          g.gain.setValueAtTime(0.0001, ctx.currentTime + t);
          g.gain.exponentialRampToValueAtTime(0.25, ctx.currentTime + t + 0.02);
          g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + t + 0.18);
          o.connect(g).connect(ctx.destination); o.start(ctx.currentTime + t); o.stop(ctx.currentTime + t + 0.2);
        });
      } catch (e) { /* audio blocked until the page is clicked once */ }
    },
    esc(s) { return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); },
    fmtDur(sec) {
      sec = Math.max(0, Math.round(sec || 0));
      const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
      return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
    },
  });

  function connect() {
    const es = new EventSource("/api/events");
    ["job", "log", "clip", "clip_ready", "live_score", "job_deleted", "notice"].forEach((evt) =>
      es.addEventListener(evt, (e) => {
        let data; try { data = JSON.parse(e.data); } catch (err) { return; }
        (listeners[evt] || []).forEach((fn) => fn(data));
      })
    );
    es.onerror = () => { /* EventSource reconnects by itself */ };
  }
  connect();

  // A new clip on a live stream: sound + toast on every page.
  CS.on("clip_ready", (d) => {
    CS.beep();
    CS.toast(`🔥 New clip: ${d.title || "untitled"}`, "hot", 9000, `/review?clip=${d.id}`);
    updatePending();
  });
  CS.on("notice", (d) => CS.toast(d.message, d.kind || "info", 8000));

  async function updatePending() {
    try {
      const d = await CS.api("GET", "/api/clips/counts");
      const b = document.getElementById("pending-badge");
      if (!b) return;
      b.textContent = d.pending || "";
      b.classList.toggle("hidden", !d.pending);
    } catch (e) { /* not critical */ }
  }
  CS.updatePending = updatePending;
  updatePending();
})();
