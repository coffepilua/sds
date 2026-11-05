document.querySelectorAll(".chat").forEach((box) => {
  const url = `/cases/${box.dataset.case}/conversations/${box.dataset.conv}/messages`;
  const list = box.querySelector(".msgs"), form = box.querySelector("form");
  const draw = async () => {
    try {
      const d = await api(`${url}?limit=100`);
      list.innerHTML = d.items.map((m) => `<li class="${m.mine ? "mine" : ""}"><b>${esc(m.sender_name)}</b> <time>${esc(new Date(m.created_at).toLocaleString("ru"))}</time><p>${esc(m.body)}</p></li>`).join("") || '<li class="mute">Сообщений пока нет. Напишите первым.</li>';
      list.scrollTop = list.scrollHeight;
    } catch (e) { list.innerHTML = `<li class="flash err">${esc(e.message)}</li>`; }
  };
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = form.elements.body.value.trim();
    if (!body) return;
    try { await api(url, { method: "POST", json: { body } }); form.reset(); draw(); } catch (err) { alert(err.message); }
  });
  draw();
  setInterval(draw, 10000);
});
