const form = document.querySelector("form[data-auth]"), msg = document.getElementById("msg");
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  msg.textContent = "";
  const f = Object.fromEntries(new FormData(form));
  try {
    if (form.dataset.auth === "register") await api("/auth/register", { method: "POST", json: f, auth: false });
    const r = await api("/auth/login", { method: "POST", json: { email: f.email, password: f.password }, auth: false });
    location.href = ROLE_HOME[r.role] || "/";
  } catch (err) { msg.textContent = err.message; }
});
