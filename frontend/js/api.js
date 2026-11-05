const API = "/api/v1";
const ROLE_HOME = { patient: "/dashboard", coordinator: "/coordinator", clinic: "/clinic", admin: "/admin" };
let access = null;

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function refresh() {
  const r = await fetch(`${API}/auth/refresh`, { method: "POST", credentials: "include" });
  access = r.ok ? (await r.json()).access_token : null;
  return access;
}

// api("/path", {method, json, body, auth:false}) -> данные или бросает Error с текстом из {"error":{"message"}}
async function api(path, { method = "GET", json, body, auth = true } = {}) {
  const send = () => {
    const h = { Accept: "application/json" };
    if (auth && access) h.Authorization = `Bearer ${access}`;
    if (json !== undefined) h["Content-Type"] = "application/json";
    return fetch(API + path, { method, headers: h, credentials: "include", body: json !== undefined ? JSON.stringify(json) : body });
  };
  if (auth && !access) await refresh();
  let r = await send();
  if (r.status === 401 && auth && (await refresh())) r = await send();
  if (r.status === 204) return null;
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data?.error?.message || `Ошибка ${r.status}`);
  return data;
}

// Картинки клиник приходят из облака; если файл недоступен - показываем заглушку с буквой
const ph = (name) => `<div class="ph" aria-hidden="true">${esc((name || "?")[0])}</div>`;
const cover = (url, name, cls = "cover") => (url ? `<img class="${cls}" src="${esc(url)}" alt="${esc(name)}" loading="lazy" data-ph="${esc(name)}">` : ph(name));
document.addEventListener("error", (e) => { const i = e.target; if (i.tagName === "IMG" && i.dataset.ph !== undefined) i.outerHTML = ph(i.dataset.ph); }, true);

const clinicCard = (c) => `<a class="card" href="/clinic.html?id=${c.id}">${cover(c.cover, c.name)}
  <div class="body"><h3>${esc(c.name)}</h3><p class="mute">${esc(c.city)}, ${esc(c.country)}</p>
  <p>${c.specialties.map((s) => `<span class="tag">${esc(s.name)}</span>`).join("")}</p></div></a>`;

async function initNav() {
  const nav = document.getElementById("nav");
  let me = null;
  try { me = await api("/me"); } catch { /* гость */ }
  if (nav) {
    nav.innerHTML = '<a href="/clinics.html">Клиники</a>' + (me
      ? `<a href="${ROLE_HOME[me.role]}">Кабинет</a><button class="link" id="out">Выйти</button>`
      : '<a href="/login.html">Войти</a><a class="btn sm" href="/register.html">Регистрация</a>');
    document.getElementById("out")?.addEventListener("click", async () => { await api("/auth/logout", { method: "POST" }); location.href = "/"; });
  }
  return me;
}
const meReady = document.getElementById("nav") || document.body.dataset.needAuth ? initNav() : Promise.resolve(null);
