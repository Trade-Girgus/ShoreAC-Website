(() => {
  const panel = document.querySelector("[data-results-filter]");
  if (!panel) return;

  const cards = Array.from(document.querySelectorAll("[data-result-card]"));
  const count = document.querySelector("[data-result-count]");
  const selects = Array.from(panel.querySelectorAll("select"));

  const matches = (card, name, value) => {
    if (value === "all") return true;
    return (card.dataset[name] || "").split(" ").includes(value);
  };

  const applyFilters = () => {
    const filters = Object.fromEntries(selects.map((select) => [select.name, select.value]));
    let visible = 0;

    cards.forEach((card) => {
      const show = matches(card, "year", filters.year)
        && matches(card, "type", filters.type)
        && matches(card, "platform", filters.platform);
      card.hidden = !show;
      if (show) visible += 1;
    });

    if (count) count.textContent = `${visible} ${visible === 1 ? "item" : "items"} shown`;
  };

  selects.forEach((select) => select.addEventListener("change", applyFilters));
  applyFilters();
})();
