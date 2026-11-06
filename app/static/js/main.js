/* Carrossel do prêmio no topo: troca de foto a cada 5 s com transição suave. */
(function () {
  const hero = document.querySelector("[data-hero]");
  const dotsBox = document.querySelector("[data-hero-dots]");
  if (!hero) return;
  let index = 0, timer;

  function slides() { return Array.from(hero.querySelectorAll(".hero-slide")); }

  function show(i) {
    const list = slides();
    if (!list.length) return;
    index = (i + list.length) % list.length;
    list.forEach((img, k) => {
      const active = k === index;
      if (active) {             // reinicia a animação de aproximação
        img.classList.remove("is-active");
        void img.offsetWidth;
      }
      img.classList.toggle("is-active", active);
    });
    dotsBox && Array.from(dotsBox.children).forEach((d, k) => {
      d.classList.toggle("is-active", k === index);
      d.setAttribute("aria-current", k === index ? "true" : "false");
    });
    // pré-carrega a próxima foto
    const next = list[(index + 1) % list.length];
    if (next && next.loading === "lazy") next.loading = "eager";
  }

  function start() {
    clearInterval(timer);
    if (slides().length > 1) timer = setInterval(() => show(index + 1), (parseFloat(hero.dataset.interval) || 5) * 1000);
  }

  function build() {
    const list = slides();
    if (dotsBox) {
      dotsBox.replaceChildren(...list.map((_, k) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "hero-dot";
        b.setAttribute("aria-label", "Ver foto " + (k + 1) + " do prêmio");
        b.addEventListener("click", () => { show(k); start(); });
        return b;
      }));
      dotsBox.hidden = list.length < 2;
    }
    show(Math.min(index, Math.max(0, list.length - 1)));
    start();
  }

  document.addEventListener("visibilitychange", () => (document.hidden ? clearInterval(timer) : start()));
  build();
  window.LP = Object.assign(window.LP || {}, { buildHero: build });
})();
