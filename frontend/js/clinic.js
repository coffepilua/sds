(async () => {
  const box = document.getElementById("clinic");
  try {
    const c = await api(`/clinics/${new URLSearchParams(location.search).get("id")}`, { auth: false });
    document.title = `${c.name} — Medical Navigator`;
    box.innerHTML = `${cover(c.cover, c.name, "cover")}
      <h1>${esc(c.name)}</h1><p class="mute">${esc(c.city)}, ${esc(c.country)} · <span class="st st-verified">Проверена администратором</span></p>
      <p>${c.specialties.map((s) => `<span class="tag">${esc(s.name)}</span>`).join("")}</p>
      <p class="pre">${esc(c.description)}</p>
      ${c.images.length > 1 ? `<div class="gallery">${c.images.slice(1).map((u) => cover(u, c.name, "")).join("")}</div>` : ""}
      <a class="btn" href="/case-new.html">Создать заявку</a>`;
  } catch (e) { box.innerHTML = `<p class="flash err">${esc(e.message)}</p><a href="/clinics.html">Ко всем клиникам</a>`; }
})();
