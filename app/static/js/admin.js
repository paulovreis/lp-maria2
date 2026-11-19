/* Painel: lê todos os campos [data-key], mostra a prévia ao vivo no iframe
   e salva tudo de uma vez em /api/save. */
(function () {
  const S = window.LP_STATE;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  let slides = S.slides.map((s) => ({ image: s.image }));
  let dirty = false;
  const status = $("#status"), frame = $("#frame");

  const val = (i) => (i.type === "checkbox" ? (i.checked ? "1" : "0") : i.value);
  const collect = () => Object.fromEntries($$("[data-key]").map((i) => [i.dataset.key, val(i)]));

  function toast(msg, error, sticky) {
    const t = Object.assign(document.createElement("div"), { className: "toast" + (error ? " error" : ""), textContent: msg, role: "status" });
    document.body.append(t);
    if (!sticky) setTimeout(() => t.remove(), error ? 6000 : 3000);
    return t;
  }
  async function api(url, opts = {}) {
    const res = await fetch(url, { ...opts, credentials: "same-origin", headers: { "X-CSRF-Token": S.csrf, ...(opts.headers || {}) } });
    const data = await res.json().catch(() => ({}));
    if (res.status === 401) { toast("Sessão expirada. Recarregando…", true); setTimeout(() => location.reload(), 1200); }
    if (!res.ok) throw new Error(data.error || httpMessage(res.status));
    return data;
  }
  function push() {
    if (frame.contentWindow) frame.contentWindow.postMessage({ type: "lp-preview", content: collect(), slides }, location.origin);
  }
  function change() {
    dirty = true;
    status.textContent = "Alterações não salvas";
    status.dataset.state = "dirty";
    push();
  }
  frame.addEventListener("load", push);

  // abas
  $$("[data-tab]").forEach((b) => b.addEventListener("click", () => {
    $$("[data-tab]").forEach((x) => x.classList.toggle("is-active", x === b));
    $$("[data-pane]").forEach((p) => (p.hidden = p.dataset.pane !== b.dataset.tab));
  }));
  // prévia: computador / celular
  $$("[data-device]").forEach((b) => b.addEventListener("click", () => {
    $$("[data-device].btn").forEach((x) => x.classList.toggle("is-active", x === b));
    $("#frame-wrap").dataset.device = b.dataset.device;
  }));

  // campos
  document.addEventListener("input", (e) => {
    if (!e.target.matches("[data-key]")) return;
    const box = e.target.closest("[data-image]");
    if (box) syncImage(box);
    change();
  });

  // imagens
  function syncImage(box) {
    const v = $("[data-key]", box).value.trim();
    const img = $("img", box), em = $("em", box);
    img.hidden = !v; em.hidden = !!v;
    if (v) img.src = v;
  }
  /* Fotos JPEG muito grandes (>2 MB) são reduzidas aqui, no navegador, para subirem rápido:
     só passam de 2560 px para baixo e com qualidade 92 (visualmente igual). PNG, WEBP e GIF
     vão como estão: o servidor converte sem perda. Se o resultado não ficar menor, envia o original. */
  const MAX_SIDE = 2560;
  async function shrink(file) {
    if (file.type !== "image/jpeg" || file.size < 2 * 1024 * 1024) return file;
    try {
      const bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
      const k = Math.min(1, MAX_SIDE / Math.max(bmp.width, bmp.height));
      const c = document.createElement("canvas");
      c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k);
      const ctx = c.getContext("2d");
      ctx.imageSmoothingQuality = "high";
      ctx.drawImage(bmp, 0, 0, c.width, c.height);
      bmp.close();
      const blob = await new Promise((r) => c.toBlob(r, "image/webp", 0.92));
      return blob && blob.type === "image/webp" && blob.size < file.size * 0.9 ? new File([blob], "foto.webp", { type: "image/webp" }) : file;
    } catch (_) { return file; }
  }

  function httpMessage(status) {
    if (status === 413) return "Arquivo grande demais para o servidor (máximo 40 MB).";
    if (status === 502 || status === 503 || status === 504) return "O servidor está ocupado ou demorou para responder. Tente novamente em instantes.";
    if (status === 401) return "Sessão expirada. Recarregue a página e entre de novo.";
    return "Erro " + status + " ao enviar. Tente novamente.";
  }

  function upload(file, onProgress) {
    return new Promise((resolve, reject) => {
      const x = new XMLHttpRequest();
      x.open("POST", "/api/upload");
      x.setRequestHeader("X-CSRF-Token", S.csrf);
      x.timeout = 180000;
      x.upload.onprogress = (e) => e.lengthComputable && onProgress(Math.round((e.loaded / e.total) * 100));
      x.onload = () => {
        let d = {};
        try { d = JSON.parse(x.responseText); } catch (_) { /* resposta do proxy, não do app */ }
        x.status >= 200 && x.status < 300 && d.url ? resolve(d.url) : reject(new Error(d.error || httpMessage(x.status)));
      };
      x.onerror = () => reject(new Error("Falha de conexão durante o envio. Verifique a internet e tente de novo."));
      x.ontimeout = () => reject(new Error("O envio demorou demais. Tente de novo (ou use uma imagem menor)."));
      const fd = new FormData();
      fd.append("file", file);
      x.send(fd);
    });
  }

  function pickImage() {
    return new Promise((resolve) => {
      const input = Object.assign(document.createElement("input"), { type: "file", accept: "image/*,.heic,.heif,.avif" });
      input.addEventListener("change", async () => {
        const original = input.files[0];
        if (!original) return resolve(null);
        const t = toast("Preparando imagem…", false, true);
        try {
          const file = await shrink(original);
          t.textContent = "Enviando imagem… 0%";
          resolve(await upload(file, (p) => (t.textContent = "Enviando imagem… " + p + "%")));
          toast("Imagem enviada");
        } catch (err) { toast(err.message, true); resolve(null); }
        finally { t.remove(); }
      });
      input.click();
    });
  }
  $$("[data-image]").forEach((box) => {
    $("[data-upload]", box).addEventListener("click", async () => {
      const url = await pickImage();
      if (!url) return;
      $("[data-key]", box).value = url; syncImage(box); change();
    });
    const clear = $("[data-clear]", box);
    if (clear) clear.addEventListener("click", () => { $("[data-key]", box).value = ""; syncImage(box); change(); });
  });

  // carrossel
  const list = $("#slides");
  function renderSlides() {
    list.replaceChildren(...slides.map((s, i) => {
      const li = document.createElement("li");
      li.className = "slide";
      const img = Object.assign(document.createElement("img"), { src: s.image, alt: "" });
      const info = document.createElement("div");
      const b = document.createElement("b"), sm = document.createElement("small");
      b.textContent = "Foto " + (i + 1);
      sm.textContent = i === 0 ? "Abre primeiro" : "";
      info.append(b, sm);
      const btn = (txt, title, fn, cls = "") => Object.assign(document.createElement("button"), { type: "button", className: "btn " + cls, textContent: txt, title, onclick: fn });
      const move = (d) => () => { const j = i + d; if (j < 0 || j >= slides.length) return; [slides[i], slides[j]] = [slides[j], slides[i]]; renderSlides(); change(); };
      const acts = document.createElement("div");
      acts.className = "acts";
      acts.append(
        btn("↑", "Mover para cima", move(-1)), btn("↓", "Mover para baixo", move(1)),
        btn("Trocar", "Trocar foto", async () => { const u = await pickImage(); if (u) { s.image = u; renderSlides(); change(); } }),
        btn("✕", "Remover foto", () => { if (confirm("Remover esta foto do carrossel?")) { slides.splice(i, 1); renderSlides(); change(); } }, "btn-danger"),
      );
      li.append(img, info, acts);
      return li;
    }));
    $("#add-slide").disabled = slides.length >= S.maxSlides;
  }
  $("#add-slide").addEventListener("click", async () => {
    const u = await pickImage();
    if (u) { slides.push({ image: u }); renderSlides(); change(); }
  });

  // salvar
  const saveBtn = $("#save");
  async function save() {
    saveBtn.disabled = true; saveBtn.textContent = "Salvando…";
    try {
      await api("/api/save", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content: collect(), slides }) });
      dirty = false; status.textContent = "Tudo salvo"; status.dataset.state = "clean";
      toast("Salvo e publicado!");
      frame.contentWindow.location.reload();
    } catch (err) { toast(err.message, true); }
    finally { saveBtn.disabled = false; saveBtn.textContent = "Salvar e publicar"; }
  }
  saveBtn.addEventListener("click", save);
  document.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); save(); } });
  window.addEventListener("beforeunload", (e) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } });

  renderSlides();
})();
