/* Só carrega dentro da prévia do painel: aplica as alterações sem salvar. */
document.addEventListener("click", (e) => { if (e.target.closest("a")) e.preventDefault(); });

window.addEventListener("message", (e) => {
  if (e.origin !== location.origin || !e.data || e.data.type !== "lp-preview") return;
  const c = e.data.content;
  const $$ = (s) => document.querySelectorAll(s);
  const one = (s) => document.querySelector(s);
  const root = document.documentElement.style;
  for (const k of ["black", "green", "white", "neon"]) root.setProperty("--" + k, c["color_" + k]);

  $$("[data-text]").forEach((n) => (n.textContent = c[n.dataset.text]));
  $$("[data-img]").forEach((n) => { if (c[n.dataset.img]) n.src = c[n.dataset.img]; });
  $$("[data-alt]").forEach((n) => (n.alt = c[n.dataset.alt]));
  $$("[data-show]").forEach((n) => (n.hidden = c[n.dataset.show] !== "1"));
  one(".hero-title-accent-img").hidden = !c.hero_accent_image;
  one(".hero-title-accent").hidden = !!c.hero_accent_image;
  one(".hero-note").hidden = !c.final_text;

  $$("[data-cta]").forEach((a) => {
    a.href = c.cta_link;
    if (c.cta_new_tab === "1") a.target = "_blank"; else a.removeAttribute("target");
  });
  const fl = one("[data-footer-link]");
  fl.textContent = c.footer_link_text;
  fl.href = c.footer_link || "#";
  fl.hidden = !(c.footer_link && c.footer_link_text);
  document.title = c.page_title;

  const hero = one("[data-hero]");
  hero.dataset.interval = c.slide_interval;
  const key = JSON.stringify(e.data.slides);
  if (hero.dataset.key !== key) {
    hero.dataset.key = key;
    hero.replaceChildren(...e.data.slides.map((s, i) =>
      Object.assign(document.createElement("img"), { className: "hero-slide", src: s.image, alt: "Foto " + (i + 1) + " do prêmio" })));
    window.LP && window.LP.buildHero();
  }
});
