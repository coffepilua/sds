const grid = document.getElementById("clinics"), pager = document.getElementById("pager");
const fCountry = document.getElementById("f-country"), fSpec = document.getElementById("f-spec");
const limit = +(grid.dataset.limit || 12);

async function load(page = 1) {
  const p = new URLSearchParams({ page, limit });
  if (fCountry?.value) p.set("country", fCountry.value);
  if (fSpec?.value) p.set("specialty_id", fSpec.value);
  grid.setAttribute("aria-busy", "true");
  try {
    const data = await api(`/clinics?${p}`, { auth: false });
    grid.innerHTML = data.items.map(clinicCard).join("") || '<p class="empty">По этим фильтрам клиник нет. Сбросьте страну или направление.</p>';
    const pages = Math.ceil(data.total / limit);
    if (pager) {
      pager.innerHTML = pages > 1 ? Array.from({ length: pages }, (_, i) => `<button class="link" data-p="${i + 1}" ${i + 1 === page ? 'aria-current="page"' : ""}>${i + 1}</button>`).join("") : "";
      pager.onclick = (e) => e.target.dataset.p && load(+e.target.dataset.p);
    }
  } catch (e) { grid.innerHTML = `<p class="flash err">${esc(e.message)}</p>`; }
  grid.removeAttribute("aria-busy");
}

(async () => {
  if (fCountry && fSpec) {
    const [cs, ss] = await Promise.all([api("/countries", { auth: false }), api("/specialties", { auth: false })]);
    fCountry.insertAdjacentHTML("beforeend", cs.map((c) => `<option>${esc(c)}</option>`).join(""));
    fSpec.insertAdjacentHTML("beforeend", ss.map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join(""));
    fCountry.onchange = fSpec.onchange = () => load();
  }
  load();
})();
