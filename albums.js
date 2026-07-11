(() => {
  const albums = window.SHORE_EXTERNAL_ALBUMS || [];
  const search = document.getElementById("albumSearch");
  const provider = document.getElementById("albumProvider");
  const count = document.getElementById("albumCount");
  const list = document.getElementById("albumList");
  const loadMore = document.getElementById("albumLoadMore");
  if (!search || !provider || !count || !list || !loadMore) return;

  let visible = 24;
  [...new Set(albums.map((album) => album.provider))].sort().forEach((name) => {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    provider.appendChild(option);
  });

  function matches() {
    const term = search.value.trim().toLowerCase();
    return albums.filter((album) => {
      const textMatch = !term || `${album.title} ${album.provider} ${album.year}`.toLowerCase().includes(term);
      const providerMatch = provider.value === "all" || album.provider === provider.value;
      return textMatch && providerMatch;
    });
  }

  function albumRow(album) {
    const article = document.createElement("article");
    article.className = "album-row";
    const copy = document.createElement("div");
    const meta = document.createElement("div");
    meta.className = "album-meta";
    meta.textContent = `${album.provider}${album.year ? ` · ${album.year}` : ""}`;
    const title = document.createElement("h3");
    title.textContent = album.title;
    copy.append(meta, title);
    if (album.label) {
      const label = document.createElement("p");
      label.className = "album-label";
      label.textContent = album.label;
      copy.append(label);
    }
    const actions = document.createElement("div");
    actions.className = "button-row";
    const context = document.createElement("a");
    context.className = "button light";
    context.href = album.context;
    context.textContent = "Event context";
    const open = document.createElement("a");
    open.className = "button secondary";
    open.href = album.url;
    open.target = "_blank";
    open.rel = "noopener noreferrer";
    open.textContent = "View hosted media";
    actions.append(context, open);
    article.append(copy, actions);
    return article;
  }

  function render() {
    const filtered = matches();
    list.replaceChildren(...filtered.slice(0, visible).map(albumRow));
    count.textContent = `${filtered.length.toLocaleString()} hosted media links`;
    loadMore.hidden = visible >= filtered.length;
  }

  search.addEventListener("input", () => { visible = 24; render(); });
  provider.addEventListener("change", () => { visible = 24; render(); });
  loadMore.addEventListener("click", () => { visible += 24; render(); });
  render();
})();
