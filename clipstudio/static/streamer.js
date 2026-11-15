/* Streamer profile + facecam picker (drag a rectangle; stored as fractions x, y, w, h). */
(function () {
  const S = window.STREAMER;
  const $ = (id) => document.getElementById(id);
  let box = S.facecam ? { ...S.facecam } : null;

  $("save").onclick = async () => {
    try {
      await CS.api("PUT", `/api/streamers/${S.id}`, {
        name: $("name").value, layout: $("layout").value, default_tags: $("default_tags").value,
        hype_words: $("hype_words").value, channels: $("channels").value,
      });
      CS.toast("Saved", "ok");
      drawPreview();
    } catch (e) { CS.toast(e.message, "error"); }
  };
  $("delete").onclick = async () => {
    if (!confirm(`Delete ${S.name}? Their clips stay.`)) return;
    await CS.api("DELETE", `/api/streamers/${S.id}`); location.href = "/streamers";
  };
  $("layout").onchange = drawPreview;

  function showFrame(s) {
    $("frame").src = s.frame_url; $("frame").classList.remove("hidden"); $("noframe").classList.add("hidden");
  }
  $("grab").onclick = async () => {
    $("grab").disabled = true; $("grab-msg").textContent = "Grabbing… (can take ~20 s)";
    try { showFrame(await CS.api("POST", `/api/streamers/${S.id}/frame`, { url: $("frame-url").value, t: $("frame-t").value })); $("grab-msg").textContent = ""; }
    catch (e) { $("grab-msg").textContent = ""; CS.toast(e.message, "error", 9000); }
    $("grab").disabled = false;
  };
  $("upload").onchange = async () => {
    const fd = new FormData(); fd.append("file", $("upload").files[0]);
    try { showFrame(await CS.api("POST", `/api/streamers/${S.id}/frame-upload`, fd)); } catch (e) { CS.toast(e.message, "error"); }
  };

  // ---- drag a rectangle
  const wrap = $("wrap"), img = $("frame"), el = $("box");
  let drag = null;
  function rel(e) {
    const r = img.getBoundingClientRect();
    return { x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)) };
  }
  wrap.addEventListener("pointerdown", (e) => {
    if (img.classList.contains("hidden")) return;
    wrap.setPointerCapture(e.pointerId);
    const p = rel(e);
    if (box && p.x > box.x && p.x < box.x + box.w && p.y > box.y && p.y < box.y + box.h && !e.shiftKey)
      drag = { mode: "move", ox: p.x - box.x, oy: p.y - box.y };
    else drag = { mode: "new", sx: p.x, sy: p.y };
  });
  wrap.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const p = rel(e);
    if (drag.mode === "new") box = { x: Math.min(drag.sx, p.x), y: Math.min(drag.sy, p.y), w: Math.abs(p.x - drag.sx), h: Math.abs(p.y - drag.sy) };
    else box = { ...box, x: Math.min(1 - box.w, Math.max(0, p.x - drag.ox)), y: Math.min(1 - box.h, Math.max(0, p.y - drag.oy)) };
    drawBox(); drawPreview();
  });
  wrap.addEventListener("pointerup", () => { drag = null; });

  function drawBox() {
    if (!box || box.w < 0.005) { el.classList.add("hidden"); $("box-txt").textContent = "Drag over the facecam."; return; }
    el.classList.remove("hidden");
    Object.assign(el.style, { left: box.x * 100 + "%", top: box.y * 100 + "%", width: box.w * 100 + "%", height: box.h * 100 + "%" });
    $("box-txt").textContent = `x ${box.x.toFixed(3)} · y ${box.y.toFixed(3)} · w ${box.w.toFixed(3)} · h ${box.h.toFixed(3)} (drag inside to move, shift-drag for a new box)`;
  }
  // draw `sx,sy,sw,sh` of the image to fill dx,dy,dw,dh by cropping (never letterboxing)
  function cover(ctx, sx, sy, sw, sh, dx, dy, dw, dh) {
    const sa = sw / sh, da = dw / dh;
    if (sa > da) { const nw = sh * da; sx += (sw - nw) / 2; sw = nw; } else { const nh = sw / da; sy += (sh - nh) / 2; sh = nh; }
    ctx.drawImage(img, sx, sy, sw, sh, dx, dy, dw, dh);
  }
  function drawPreview() {
    const c = $("preview"), ctx = c.getContext("2d");
    ctx.fillStyle = "#000"; ctx.fillRect(0, 0, c.width, c.height);
    if (img.classList.contains("hidden") || !img.naturalWidth) return;
    const W = c.width, H = c.height, iw = img.naturalWidth, ih = img.naturalHeight;
    const layout = $("layout").value;
    const topH = Math.round(H * 730 / 1920);
    if (layout === "split" && box && box.w > 0.01) {
      cover(ctx, box.x * iw, box.y * ih, box.w * iw, box.h * ih, 0, 0, W, topH);
      cover(ctx, 0, 0, iw, ih, 0, topH, W, H - topH);
      ctx.fillStyle = "#fff"; ctx.font = "bold 15px system-ui"; ctx.textAlign = "center"; ctx.strokeStyle = "#000"; ctx.lineWidth = 4;
      ctx.strokeText("CAPTIONS HERE", W / 2, topH + 5); ctx.fillText("CAPTIONS HERE", W / 2, topH + 5);
    } else if (layout === "center") {
      cover(ctx, 0, 0, iw, ih, 0, 0, W, H);
    } else {
      ctx.filter = "blur(6px) brightness(0.7)"; cover(ctx, 0, 0, iw, ih, 0, 0, W, H); ctx.filter = "none";
      const h = W * ih / iw; ctx.drawImage(img, 0, (H - h) / 2, W, h);
      if (layout === "split") { ctx.fillStyle = "#ffb020"; ctx.font = "12px system-ui"; ctx.textAlign = "center"; ctx.fillText("Draw a facecam box for split", W / 2, 20); }
    }
  }
  img.addEventListener("load", () => { drawBox(); drawPreview(); });
  $("clear-box").onclick = () => { box = null; drawBox(); drawPreview(); };
  $("save-box").onclick = async () => {
    try { await CS.api("PUT", `/api/streamers/${S.id}`, { facecam: box && box.w > 0.01 ? box : null }); CS.toast("Facecam saved — new clips will use it.", "ok"); }
    catch (e) { CS.toast(e.message, "error"); }
  };
  if (img.complete && img.naturalWidth) { drawBox(); drawPreview(); }
})();
