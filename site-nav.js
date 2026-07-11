(() => {
  const header = document.querySelector(".site-header");
  const nav = document.querySelector(".site-header .nav");
  if (!header || !nav || document.getElementById("menu-panel")) return;

  nav.innerHTML = `
    <a class="button light" href="index.html">Home</a>
    <a class="button secondary" href="events.html">Races</a>
    <a class="button" href="membership.html">Membership</a>
    <a class="button primary" href="https://runsignup.com/Club/NJ/SpringLake/ShoreAthleticClub">Join</a>
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
          <a href="membership.html">Membership benefits</a>
          <a href="https://runsignup.com/Club/NJ/SpringLake/ShoreAthleticClub">Join or renew</a>
          <a href="support.html#donate">Donate</a>
          <a href="support.html#partner">Sponsor</a>
          <a href="support.html#volunteer">Volunteer</a>
        </div>
        <div class="menu-group">
          <h3>Race calendar</h3>
          <a href="events.html">All races</a>
          <a href="events.html#road">Road races</a>
          <a href="events.html#track">Track and field</a>
          <a href="events.html#youth-xc">Youth cross country</a>
          <a href="results.html">Results archive</a>
        </div>
        <div class="menu-group">
          <h3>Programs</h3>
          <a href="programs.html#youth">Youth programs</a>
          <a href="programs.html#workouts">Workout Wednesday</a>
          <a href="programs.html#gone-running">Gone Running</a>
          <a href="programs.html#coaching">Coaching</a>
          <a href="programs.html#compete">USATF teams</a>
        </div>
        <div class="menu-group">
          <h3>Club</h3>
          <a href="club.html">Board and history</a>
          <a href="news.html">News</a>
          <a href="media.html">Photos and video</a>
          <a href="records.html">Club records</a>
          <a href="contact.html">Contact</a>
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
  };

  menuButton.addEventListener("click", () => setOpen(!panel.classList.contains("open")));
  closeButton.addEventListener("click", () => setOpen(false));
  panel.addEventListener("click", (event) => {
    if (event.target === panel || event.target.closest("a")) setOpen(false);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") setOpen(false);
  });
})();
