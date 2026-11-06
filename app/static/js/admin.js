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

  function toast(msg, error) {
    const t = Object.assign(document.createElement("div"), { className: "toast" + (error ? " error" : ""), textContent: msg, role: "status" });
    document.body.append(t);
    setTimeout(() => t.remove(), 3000);
  }
  async function api(url, opts = {}) {
    const res = await fetch(url, { ...opts, credentials: "same-origin", headers: { "X-CSRF-Token": S.csrf, ...(opts.headers || {}) } });
    const data = await res.json().catch(() => ({}));
    if (res.status === 401) { toast("Sessão expirada. Recarregando…", true); setTimeout(() => location.reload(), 1200); }
    if (!res.ok) throw new Error(data.error || "Erro " + res.status);
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
  function pickImage() {
    return new Promise((resolve) => {
      const input = Object.assign(document.createElement("input"), { type: "file", accept: "image/png,image/jpeg,image/webp,image/gif" });
      input.addEventListener("change", async () => {
        if (!input.files[0]) return resolve(null);
        const fd = new FormData();
        fd.append("file", input.files[0]);
        try { toast("Enviando imagem…"); resolve((await api("/api/upload", { method: "POST", body: fd })).url); }
        catch (err) { toast(err.message, true); resolve(null); }
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
