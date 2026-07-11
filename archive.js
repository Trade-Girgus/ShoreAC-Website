(() => {
  const entries = window.SHORE_ARCHIVE || [];
  const search = document.getElementById("archiveSearch");
  const category = document.getElementById("archiveCategory");
  const year = document.getElementById("archiveYear");
  const results = document.getElementById("archiveResults");
  const summary = document.getElementById("archiveSummary");
  const loadMore = document.getElementById("archiveLoadMore");
  if (!search || !category || !year || !results || !summary || !loadMore) return;

  let visible = 60;

  function addOptions(select, values, label) {
    const all = document.createElement("option");
    all.value = "all";
    all.textContent = label;
    select.appendChild(all);
    values.forEach((value) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      select.appendChild(option);
    });
  }

  const categories = [...new Set(entries.map((entry) => entry.categoryLabel))].sort();
  const years = [...new Set(entries.map((entry) => entry.year).filter(Boolean))].sort().reverse();
  addOptions(category, categories, "All categories");
  addOptions(year, years, "All years");

  const query = new URLSearchParams(window.location.search).get("q");
  if (query) search.value = query;
  const categoryQuery = new URLSearchParams(window.location.search).get("category");
  if (categoryQuery && categories.includes(categoryQuery)) category.value = categoryQuery;

  function filteredEntries() {
    const term = search.value.trim().toLowerCase();
    return entries.filter((entry) => {
      const haystack = `${entry.title} ${entry.excerpt} ${entry.categoryLabel}`.toLowerCase();
      const categoryMatch = category.value === "all" || entry.categoryLabel === category.value;
      const yearMatch = year.value === "all" || entry.year === year.value;
      return (!term || haystack.includes(term)) && categoryMatch && yearMatch;
    });
  }

  function makeResult(entry) {
    const article = document.createElement("article");
    article.className = "archive-result";
    const copy = document.createElement("div");
    const meta = document.createElement("div");
    meta.className = "archive-result-meta";
    meta.textContent = `${entry.categoryLabel}${entry.year ? ` · ${entry.year}` : ""}`;
    const heading = document.createElement("h2");
    const link = document.createElement("a");
    link.href = entry.url;
    link.textContent = entry.title;
    heading.appendChild(link);
    const excerpt = document.createElement("p");
    excerpt.textContent = entry.excerpt;
    copy.append(meta, heading, excerpt);
    const open = document.createElement("a");
    open.className = "button secondary";
    open.href = entry.url;
    open.textContent = "Open";
    article.append(copy, open);
    return article;
  }

  function render() {
    const matches = filteredEntries();
    const shown = matches.slice(0, visible);
    results.replaceChildren(...shown.map(makeResult));
    if (!matches.length) {
      const empty = document.createElement("p");
      empty.className = "archive-empty";
      empty.textContent = "No archive entries match these filters.";
      results.appendChild(empty);
    }
    summary.textContent = `${matches.length.toLocaleString()} archive entries`;
    loadMore.hidden = shown.length >= matches.length;
  }

  [search, category, year].forEach((control) => {
    control.addEventListener(control === search ? "input" : "change", () => {
      visible = 60;
      render();
    });
  });
  loadMore.addEventListener("click", () => {
    visible += 60;
    render();
  });
  render();
})();
