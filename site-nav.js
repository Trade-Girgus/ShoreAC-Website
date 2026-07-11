(() => {
  const scriptUrl = document.currentScript?.src || window.location.href;
  const siteUrl = (path) => new URL(path, scriptUrl).href;
  const header = document.querySelector(".site-header");
  const nav = document.querySelector(".site-header .nav");
  if (!header || !nav || document.getElementById("menu-panel")) return;

  nav.innerHTML = `
    <a class="button light" href="${siteUrl("index.html")}">Home</a>
    <a class="button secondary" href="${siteUrl("events.html")}">Races</a>
    <a class="button" href="${siteUrl("membership.html")}">Membership</a>
    <a class="button primary" href="https://runsignup.com/MemberOrg/ShoreAthleticClub/Register">Join</a>
    <button class="button menu-button" type="button" aria-expanded="false" aria-controls="menu-panel">
      <span class="menu-icon" aria-hidden="true"><span></span><span></span><span></span></span>
      Menu
    </button>
  `;

  const panel = document.createElement("div");
  panel.className = "menu-panel";
  panel.id = "menu-panel";
  panel.setAttribute("aria-hidden", "true");
  panel.innerHTML = `
    <div class="menu-sheet" role="dialog" aria-modal="true" aria-labelledby="site-menu-title">
      <div class="menu-head">
        <h2 id="site-menu-title">Shore A.C. menu</h2>
        <button class="button light menu-close" type="button">Close</button>
      </div>
      <div class="menu-grid">
        <div class="menu-group">
          <h3>Join and give</h3>
          <a href="${siteUrl("membership.html")}">Membership benefits</a>
          <a href="https://runsignup.com/MemberOrg/ShoreAthleticClub/Register">Join or renew</a>
          <a href="${siteUrl("support.html#donate")}">Donate</a>
          <a href="${siteUrl("support.html#partner")}">Sponsor</a>
          <a href="${siteUrl("support.html#volunteer")}">Volunteer</a>
        </div>
        <div class="menu-group">
          <h3>Race calendar</h3>
          <a href="${siteUrl("events.html")}">All races</a>
          <a href="${siteUrl("events.html#road")}">Road races</a>
          <a href="${siteUrl("events.html#track")}">Track and field</a>
          <a href="${siteUrl("events.html#youth-xc")}">Youth cross country</a>
          <a href="${siteUrl("results.html")}">Results archive</a>
        </div>
        <div class="menu-group">
          <h3>Programs</h3>
          <a href="${siteUrl("programs.html#youth")}">Youth programs</a>
          <a href="${siteUrl("archive/workout-wednesday.html")}">Workout Wednesday</a>
          <a href="${siteUrl("programs.html#gone-running")}">Gone Running</a>
          <a href="${siteUrl("programs.html#coaching")}">Coaching</a>
          <a href="${siteUrl("programs.html#compete")}">USATF teams</a>
        </div>
        <div class="menu-group">
          <h3>Club and archive</h3>
          <a href="${siteUrl("club.html")}">Board and history</a>
          <a href="${siteUrl("news.html")}">News and blog</a>
          <a href="${siteUrl("media.html")}">Photos and video</a>
          <a href="${siteUrl("records.html")}">Club records</a>
          <a href="${siteUrl("archive.html")}">Full searchable archive</a>
          <a href="${siteUrl("contact.html")}">Contact</a>
        </div>
      </div>
    </div>
  `;
  document.body.append(panel);

  const menuButton = nav.querySelector(".menu-button");
  const closeButton = panel.querySelector(".menu-close");
  const setOpen = (open) => {
    panel.classList.toggle("open", open);
    panel.setAttribute("aria-hidden", String(!open));
    menuButton.setAttribute("aria-expanded", String(open));
    document.body.classList.toggle("menu-open", open);
    if (open) closeButton.focus();
  };

  menuButton.addEventListener("click", () => setOpen(!panel.classList.contains("open")));
  closeButton.addEventListener("click", () => {
    setOpen(false);
    menuButton.focus();
  });
  panel.addEventListener("click", (event) => {
    if (event.target === panel || event.target.closest("a")) setOpen(false);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") setOpen(false);
  });
})();
