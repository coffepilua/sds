(async () => {
  const me = await meReady, form = document.getElementById("case"), msg = document.getElementById("msg");
  if (!me) return (location.href = "/login.html");
  if (me.role !== "patient") { form.hidden = true; msg.textContent = "Заявки создают пациенты. Войдите как пациент."; return; }
  const ss = await api("/specialties", { auth: false });
  form.elements.specialty_id.insertAdjacentHTML("beforeend", ss.map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join(""));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    msg.textContent = "";
    const f = new FormData(form);
    let id = null;
    try {
      const c = await api("/cases", { method: "POST", json: {
        specialty_id: +f.get("specialty_id"), description: f.get("description"),
        target_country: f.get("target_country") || null, budget_usd: f.get("budget_usd") ? +f.get("budget_usd") : null } });
      id = c.id;
      for (const file of form.elements.docs.files) { const fd = new FormData(); fd.append("file", file); await api(`/cases/${id}/documents`, { method: "POST", body: fd }); }
      if (f.get("send")) await api(`/cases/${id}/submit`, { method: "POST" });
      location.href = `/cases/${id}`;
    } catch (err) {
      msg.innerHTML = id ? `Черновик №${id} сохранён, но шаг не выполнен: ${esc(err.message)}. <a href="/cases/${id}">Открыть заявку</a>` : esc(err.message);
    }
  });
})();
