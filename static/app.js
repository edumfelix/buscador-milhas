(() => {
  const cards = Array.from(document.querySelectorAll("#cards .card"));
  if (!cards.length) return;

  const els = {
    dest: document.getElementById("filter-dest"),
    program: document.getElementById("filter-program"),
    cabin: document.getElementById("filter-cabin"),
    max: document.getElementById("filter-max"),
    deals: document.getElementById("filter-deals"),
    sort: document.getElementById("filter-sort"),
    reset: document.getElementById("filter-reset"),
    count: document.getElementById("count"),
    empty: document.getElementById("empty"),
    cards: document.getElementById("cards"),
  };

  const params = new URLSearchParams(window.location.search);
  if (params.get("dest")) els.dest.value = params.get("dest");
  if (params.get("program")) els.program.value = params.get("program");
  if (params.get("cabin")) els.cabin.value = params.get("cabin");
  if (params.get("max")) els.max.value = params.get("max");
  if (params.get("deals") === "1") els.deals.checked = true;
  if (params.get("sort")) els.sort.value = params.get("sort");

  function apply() {
    const dest = els.dest.value;
    const program = els.program.value;
    const cabin = els.cabin.value;
    const rawMax = Number(els.max.value);
    const max = Number.isFinite(rawMax) && rawMax > 0 ? rawMax : Infinity;
    const onlyDeals = els.deals.checked;
    let visible = 0;

    cards.forEach((card) => {
      const badges = card.dataset.badges || "";
      const show =
        (!dest || card.dataset.destination === dest) &&
        (!program || card.dataset.program === program) &&
        (!cabin || card.dataset.cabin === cabin) &&
        Number(card.dataset.miles) <= max &&
        (!onlyDeals || /(^| )(new|drop)( |$)/.test(badges));
      card.hidden = !show;
      if (show) visible += 1;
    });

    els.count.textContent = `${visible} oportunidade(s)`;
    if (els.empty) els.empty.hidden = visible > 0;

    const sort = els.sort.value;
    const sorted = [...cards].sort((a, b) => {
      if (sort === "miles") {
        return Number(a.dataset.miles) - Number(b.dataset.miles);
      }
      if (sort === "date") {
        return (a.dataset.date || "").localeCompare(b.dataset.date || "");
      }
      return (b.dataset.firstSeen || "").localeCompare(a.dataset.firstSeen || "");
    });
    sorted.forEach((card) => els.cards.appendChild(card));

    const next = new URLSearchParams();
    if (dest) next.set("dest", dest);
    if (program) next.set("program", program);
    if (cabin) next.set("cabin", cabin);
    if (els.max.value) next.set("max", els.max.value);
    if (onlyDeals) next.set("deals", "1");
    if (sort !== "miles") next.set("sort", sort);
    const query = next.toString();
    history.replaceState(null, "", query ? `?${query}` : window.location.pathname);
  }

  [els.dest, els.program, els.cabin, els.max, els.deals, els.sort].forEach((el) => {
    el.addEventListener("input", apply);
    el.addEventListener("change", apply);
  });

  els.reset.addEventListener("click", () => {
    els.dest.value = "";
    els.program.value = "";
    els.cabin.value = "";
    els.max.value = "";
    els.deals.checked = false;
    els.sort.value = "miles";
    apply();
  });

  apply();
})();
