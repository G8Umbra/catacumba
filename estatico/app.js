// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
// SPDX-License-Identifier: MPL-2.0
// Catacumba: the screen. All text goes in as text (textContent), never as HTML.
"use strict";

const estado = { datos: null, tipo: "todo", busca: "", abierto: null, prefs: null, continuar: null,
  orden: "recent", soloSinGuardar: false, abrio: null };
const CLAVE_VISTA = "catacumba_view";      // per-browser convenience only (sort order and filter)
const CLAVE_TEMA = "catacumba_theme";
const CLAVE_PREFS = "catacumba_prefs";
const TEMAS = [["liso", "Plain"], ["noche", "Night"], ["blueprint", "Blueprint"], ["compass", "Compass"],
  ["frio", "Frost"], ["atardecer", "Sunset"], ["bosque", "Forest"]];
const BUSCAR_WEB = { duckduckgo: "https://duckduckgo.com/?q=", google: "https://www.google.com/search?q=" };
const urlFoto = (ruta, tam) => `/api/foto?tam=${tam}&ruta=${encodeURIComponent(ruta)}`;
const $ = (sel) => document.querySelector(sel);

function nuevo(etiqueta, props = {}, hijos = []) {
  const el = document.createElement(etiqueta);
  for (const [k, v] of Object.entries(props)) {
    if (k === "texto") el.textContent = v;
    else if (k === "clase") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  for (const h of hijos) if (h) el.append(h);
  return el;
}

async function api(ruta, cuerpo) {
  const opciones = cuerpo === undefined ? {} :
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo) };
  const r = await fetch(ruta, opciones);
  const datos = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(datos.error || "That did not work");
  return datos;
}

function ago(iso) {
  if (!iso) return "";
  const seg = (Date.now() - new Date(iso).getTime()) / 1000;
  if (seg < 90) return "just now";
  const min = seg / 60, h = min / 60, d = h / 24;
  if (min < 60) return `${Math.round(min)} min ago`;
  if (h < 24) return `${Math.round(h)} h ago`;
  if (d < 2) return "yesterday";
  if (d < 31) return `${Math.round(d)} days ago`;
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

// ------------------------------------------------------------------ theme (auto / light / dark)
const TEMAS_UI = ["auto", "light", "dark"];
function aplicarTema(t) {
  const el = document.documentElement;
  if (t === "light" || t === "dark") el.dataset.theme = t; else delete el.dataset.theme;
  const boton = document.querySelector("#tema");
  if (boton) boton.textContent = "Theme: " + (TEMAS_UI.includes(t) ? t : "auto");
}
function temaGuardado() {
  try { const t = localStorage.getItem(CLAVE_TEMA); return TEMAS_UI.includes(t) ? t : "auto"; } catch { return "auto"; }
}
function alternarTema() {
  const siguiente = TEMAS_UI[(TEMAS_UI.indexOf(temaGuardado()) + 1) % TEMAS_UI.length];
  try { localStorage.setItem(CLAVE_TEMA, siguiente); } catch { /* private window: the choice lasts until reload */ }
  aplicarTema(siguiente);
}
aplicarTema(temaGuardado());

// ------------------------------------------------------------------ cargar y pintar
async function cargar(fresco = false) {
  $("#aviso").textContent = fresco ? "Reading everything again…" : (estado.datos ? "" : "Reading your repositories…");
  try {
    estado.datos = await api("/api/todo" + (fresco ? "?fresco=1" : ""));
    $("#maquina").textContent = "The living archive · " + estado.datos.maquina;
    aplicarFondo(estado.datos.preferencias);
    await cargarContinuar();
    const alm = estado.datos.almacenamiento;
    $("#almacenamiento").hidden = !alm || alm.ok;
    $("#almacenamiento").textContent = alm && !alm.ok ? alm.mensaje : "";
    pintar();
    $("#aviso").textContent = "";
  } catch (e) {
    $("#aviso").textContent = "Could not read: " + e.message;
  }
}

function todos() {
  if (!estado.datos) return [];
  return [...estado.datos.repos, ...estado.datos.extras];
}

async function cargarContinuar() {
  try { estado.continuar = await api("/api/continue"); } catch { estado.continuar = null; }
}

function ordenar(lista) {
  const comparar = {
    name: (x, y) => x.nombre.localeCompare(y.nombre, undefined, { sensitivity: "base" }),
    "name-desc": (x, y) => y.nombre.localeCompare(x.nombre, undefined, { sensitivity: "base" }),
    unsaved: (x, y) => (y.sin_guardar || 0) - (x.sin_guardar || 0),
    opened: (x, y) => (abierto(y.id) || "").localeCompare(abierto(x.id) || ""),
  }[estado.orden];
  return comparar ? [...lista].sort(comparar) : lista;      // "recent" keeps the server's order (latest change first)
}

function abierto(id) {
  const e = (estado.continuar?.projects || []).find((p) => p.id === id);
  return e ? e.last_opened : "";
}

function pintar() {
  const verFavoritos = estado.tipo === "favoritos";
  const verAscii = estado.tipo === "ascii";
  const verTarjetas = !verAscii;
  const vacio = Boolean(estado.datos?.onboarding?.vacio);
  $("#ascii-studio").hidden = !verAscii;
  $("#bienvenida").hidden = !(verTarjetas && vacio);
  $("#barra-vista").hidden = !(verTarjetas && !vacio);
  $("#continuar").hidden = true;
  $("#tarjetas").hidden = !verTarjetas || vacio;
  for (const b of document.querySelectorAll("#pestanas button")) b.setAttribute("aria-pressed", String(b.dataset.tipo === estado.tipo));
  if (verAscii) return;
  if (vacio) {
    pintarBienvenida();
    return;
  }
  const caja = $("#tarjetas");
  caja.replaceChildren();
  const q = estado.busca.toLowerCase();
  const favoritos = new Set(estado.prefs?.favoritos || []);
  const notas = new Map((estado.continuar?.projects || []).map((p) => [p.id, p.note || ""]));
  const base = todos().filter((i) => (estado.tipo === "todo" || verFavoritos || i.tipo === estado.tipo) &&
    (!verFavoritos || favoritos.has(i.id)));
  const lista = ordenar(base.filter((i) =>
    (!estado.soloSinGuardar || i.sin_guardar > 0) &&
    (!q || [i.nombre, i.donde, i.nota, i.mensaje, notas.get(i.id)].some((t) => (t || "").toLowerCase().includes(q)))));
  $("#conteo").textContent = lista.length === base.length ? `${base.length} items` : `${lista.length} of ${base.length} items`;
  pintarContinuar(!q && estado.tipo === "todo" && !estado.soloSinGuardar);
  if (!lista.length) {
    const mensaje = q ? "Nothing matches that search." : estado.soloSinGuardar ? "Nothing has unsaved changes right now." :
      verFavoritos ? "No favorites yet. Click the star on a card to pin it here." : "There is nothing in this section yet.";
    caja.append(nuevo("p", { clase: "linea", texto: mensaje }));
    return;
  }
  for (const item of lista) caja.append(tarjeta(item));
}

// "Continue where you left off": the most recently opened items that are still in the list
function pintarContinuar(mostrar) {
  const caja = $("#continuar-lista");
  caja.replaceChildren();
  const porId = new Map(todos().map((i) => [i.id, i]));
  const filas = (estado.continuar?.projects || []).filter((p) => porId.has(p.id) && (p.last_opened || p.note)).slice(0, 4);
  $("#continuar").hidden = !(mostrar && filas.length);
  for (const f of filas) {
    const item = porId.get(f.id);
    caja.append(nuevo("button", { type: "button", clase: "continuar-tarjeta", onclick: () => abrirPanel(item) }, [
      nuevo("strong", { texto: item.nombre }),
      nuevo("span", { clase: "nota", texto: f.last_opened ? "Last opened " + ago(f.last_opened) : "Note saved " + ago(f.note_at) }),
      f.note ? nuevo("span", { clase: "continuar-nota", texto: f.note }) : null,
      f.files && f.files.length ? nuevo("span", { clase: "nota", texto: "Latest file: " + f.files[0].path }) : null,
    ]));
  }
}

// ------------------------------------------------------------------ first run
function pintarBienvenida() {
  const o = estado.datos.onboarding;
  if (!estado.bienvenidaVista) {            // first time only: put the reader at the start of the guide
    estado.bienvenidaVista = true;
    $("#bv-titulo").focus();
  }
  $("#bv-sugerencias").replaceChildren(...o.sugerencias.map((ruta) => nuevo("button", {
    type: "button", clase: "sugerencia", texto: ruta, title: "Look for git projects in " + ruta,
    onclick: () => escanear(ruta),
  })));
  $("#bv-lista").replaceChildren(...o.sugerencias.map((ruta) => nuevo("option", { value: ruta })));
  if (!o.sugerencias.length) $("#bv-sugerencias").append(nuevo("p", { clase: "nota", texto: "No usual project folders were found in your home folder. Type the path below." }));
}

async function escanear(ruta) {
  $("#bv-error").textContent = "";
  if (!ruta) { $("#bv-error").textContent = "Type or pick a folder first."; return; }
  try {
    await api("/api/scan", { donde: ruta });
    await cargar(true);
  } catch (e) {
    $("#bv-error").textContent = e.message;
  }
}

async function agregarComoProyecto() {
  const ruta = $("#bv-ruta").value.trim();
  $("#bv-error").textContent = "";
  if (!ruta) { $("#bv-error").textContent = "Type or pick a folder first."; return; }
  try {
    await api("/api/agregar", { nombre: ruta.replace(/\/+$/, "").split("/").pop() || ruta, tipo: "proyecto", donde: ruta });
    await cargar(true);
  } catch (e) {
    $("#bv-error").textContent = e.message;
  }
}

function tarjeta(item) {
  const chips = nuevo("div", { clase: "chips" });
  let linea = item.nota || item.donde;
  if (item.tipo === "repo") {
    linea = item.mensaje;
    if (item.fecha) chips.append(nuevo("span", { clase: "chip", texto: ago(item.fecha) }));
    if (item.sin_guardar) chips.append(nuevo("span", { clase: "chip ojo", texto: `${item.sin_guardar} unsaved` }));
    else if (item.sin_guardar === 0) chips.append(nuevo("span", { clase: "chip ok", texto: "all saved" }));
    for (const c of item.chips || []) chips.append(nuevo("span", { clase: "chip", texto: c }));   // added by an optional plugin
  } else if (item.existe === false) {
    chips.append(nuevo("span", { clase: "chip mal", texto: "no longer here" }));
  }
  const guardado = (estado.continuar?.projects || []).find((p) => p.id === item.id);
  if (guardado?.last_opened) chips.append(nuevo("span", { clase: "chip", texto: "opened " + ago(guardado.last_opened) }));
  const abrir = nuevo("button", { clase: "tarjeta-abrir", type: "button", onclick: () => abrirPanel(item) }, [
    nuevo("span", { clase: "tipo", texto: estado.datos.tipos[item.tipo] || item.tipo }),
    nuevo("h3", { texto: item.nombre }),
    nuevo("p", { clase: "linea", texto: linea || "" }),
    guardado?.note ? nuevo("p", { clase: "linea tarjeta-nota", texto: "Note: " + guardado.note }) : null,
    chips,
  ]);
  const esFavorito = (estado.prefs?.favoritos || []).includes(item.id);
  const favorito = nuevo("button", {
    clase: "tarjeta-favorito",
    type: "button",
    title: esFavorito ? "Remove from Favorites" : "Add to Favorites",
    "aria-label": esFavorito ? "Remove from Favorites" : "Add to Favorites",
    "aria-pressed": String(esFavorito),
    texto: esFavorito ? "★" : "☆",
    onclick: () => alternarFavorito(item.id),
  });
  return nuevo("article", { clase: "tarjeta" }, [abrir, favorito]);
}

async function alternarFavorito(id) {
  const favoritos = new Set(estado.prefs?.favoritos || []);
  const quitar = favoritos.has(id);
  if (quitar) favoritos.delete(id);
  else favoritos.add(id);
  if (await guardarPrefs({ favoritos: [...favoritos] }, "#aviso")) {
    $("#aviso").textContent = quitar ? "Removed from Favorites." : "Added to Favorites.";
    pintar();
  }
}

// ------------------------------------------------------------------ the detail panel
function resultado(texto, clase = "") {
  const r = $("#p-resultado");
  r.textContent = texto;
  r.className = "resultado " + clase;
}

async function accion(ruta, item, bien) {
  resultado("…");
  try {
    const r = await api(ruta, { id: item.id });
    resultado(bien(r), "ok");
    return r;
  } catch (e) {
    resultado(e.message, "mal");
  }
}

function abrirPanel(item) {
  estado.abierto = item.id;
  if (!estado.abrio) estado.abrio = document.activeElement;      // so focus can go back when the panel closes
  $("#panel").hidden = false;
  $("#p-nombre").textContent = item.nombre;
  $("#p-donde").textContent = item.donde;
  resultado("");
  const datos = $("#p-datos");
  datos.replaceChildren();
  const fila = (k, v) => { if (v !== undefined && v !== null && v !== "") datos.append(nuevo("dt", { texto: k }), nuevo("dd", { texto: String(v) })); };
  fila("Kind", estado.datos.tipos[item.tipo]);
  if (item.tipo === "repo") {
    fila("Branch", item.rama);
    fila("Latest change", `${item.mensaje} (${ago(item.fecha)})`);
    fila("Unsaved", item.sin_guardar === null ? "could not be read" : item.sin_guardar);
  }
  fila("Note", item.nota);

  const b = $("#p-botones");
  b.replaceChildren();
  const boton = (texto, fn, clase) => b.append(nuevo("button", { type: "button", clase: clase || "", texto, onclick: fn }));
  if (item.tipo === "pagina") {
    boton("Open the page", () => accion("/api/abrir", item, () => "Opened in the browser"), "primario");
    boton("Does it answer?", () => accion("/api/responde", item, (r) => r.responde ? "Yes, it answers" : "No answer"));
  } else {
    boton("Open the folder", () => accion("/api/abrir", item, () => "Opened"), "primario");
    boton("Open in VS Code", () => accion("/api/code", item, () => "Opening in VS Code"));
    boton("Copy the path", async () => {
      try { await navigator.clipboard.writeText(item.donde); resultado("Path copied", "ok"); }
      catch { resultado("Could not copy; select the path above", "ojo"); }
    });
  }
  for (const a of item.acciones || []) {     // extra buttons that an optional plugin put on this item
    boton(a.etiqueta, async () => {
      resultado(a.pendiente || "…");
      try {
        const r = await api(a.ruta, { id: item.id });
        resultado(r.texto || "Done", r.clase || "ok");
      } catch (e) { resultado(e.message, "mal"); }
    });
  }
  if (item.tipo !== "repo") {
    boton("Remove from the list", () => confirmarQuitar(item));
  }

  const cuerpo = $("#p-cuerpo");
  cuerpo.replaceChildren();
  if (item.tipo === "repo") cargarDetalle(item);
  visitar(item);
  $("#cerrar").focus();
}

// ------------------------------------------------------------------ where I left off (panel)
async function visitar(item) {
  const nota = $("#pc-nota");
  $("#pc-estado").textContent = "";
  nota.value = "";
  $("#pc-archivos").replaceChildren();
  try {
    const r = await api("/api/continue/visit", { id: item.id });
    if (estado.abierto !== item.id) return;
    if (!r.enabled) {
      $("#pc-previo").textContent = "Remembering is paused. You can turn it back on in About.";
      $("#pc-guardar").disabled = false;
      return;
    }
    $("#pc-previo").textContent = r.previous && r.previous.last_opened
      ? `You last opened this ${ago(r.previous.last_opened)} (${r.entry.visits} visits). Stored only on this computer.`
      : "First time you open this here. From now on Catacumba remembers it, on this computer only.";
    nota.value = r.entry.note || "";
    $("#pc-archivos").replaceChildren(...(r.entry.files.length
      ? [nuevo("li", { clase: "nota", texto: "Most recently changed files:" }), ...r.entry.files.map((f) => nuevo("li", {}, [nuevo("code", { texto: f.path }), nuevo("span", { clase: "fecha", texto: " " + ago(f.modified) })]))]
      : []));
    await cargarContinuar();
    if (estado.tipo === "todo") pintar();
  } catch (e) {
    $("#pc-previo").textContent = "Could not read the saved history: " + e.message;
  }
}

async function guardarNota() {
  if (!estado.abierto) return;
  try {
    await api("/api/continue/note", { id: estado.abierto, note: $("#pc-nota").value });
    $("#pc-estado").textContent = "Saved on this computer.";
    await cargarContinuar();
    pintar();
  } catch (e) { $("#pc-estado").textContent = e.message; }
}

async function olvidarItem() {
  if (!estado.abierto) return;
  try {
    await api("/api/continue/forget", { id: estado.abierto });
    $("#pc-nota").value = "";
    $("#pc-archivos").replaceChildren();
    $("#pc-previo").textContent = "History for this item was deleted.";
    $("#pc-estado").textContent = "";
    await cargarContinuar();
    pintar();
  } catch (e) { $("#pc-estado").textContent = e.message; }
}

function confirmarQuitar(item) {
  const cuerpo = $("#p-cuerpo");
  cuerpo.replaceChildren(nuevo("div", { clase: "confirmar" }, [
    nuevo("span", { texto: "This only removes it from the list; the folder or page is not touched." }),
    nuevo("button", { type: "button", texto: "Yes, remove from the list", onclick: async () => {
      try {
        await api("/api/quitar", { id: item.id });
        cerrarPanel();
        await cargar();
      } catch (e) { resultado(e.message, "mal"); }
    } }),
    nuevo("button", { type: "button", texto: "No", onclick: () => cuerpo.replaceChildren() }),
  ]));
}

async function cargarDetalle(item) {
  const cuerpo = $("#p-cuerpo");
  cuerpo.append(nuevo("p", { clase: "linea", texto: "Reading your changes…" }));
  try {
    const d = await api("/api/detalle", { id: item.id });
    if (estado.abierto !== item.id) return;
    cuerpo.replaceChildren();
    if (d.sin_guardar.length) {
      cuerpo.append(nuevo("h3", { texto: "Unsaved in git" }),
        nuevo("ol", {}, d.sin_guardar.map((f) => nuevo("li", { texto: f }))));
    }
    cuerpo.append(nuevo("h3", { texto: "Latest changes" }),
      nuevo("ol", {}, d.commits.map((c) => nuevo("li", {}, [nuevo("span", { clase: "fecha", texto: c.fecha }), c.mensaje]))));
    for (const sec of d.secciones || []) {    // extra sections from an optional plugin
      cuerpo.append(nuevo("h3", { texto: sec.titulo }), nuevo("pre", { texto: sec.texto }));
    }
  } catch (e) {
    cuerpo.replaceChildren(nuevo("p", { clase: "linea", texto: "Could not read your changes: " + e.message }));
  }
}

function cerrarPanel() {
  estado.abierto = null;
  $("#panel").hidden = true;
  const volver = estado.abrio;
  estado.abrio = null;
  if (volver && volver.isConnected) volver.focus();
}

// ------------------------------------------------------------------ agregar
function abrirDialogo() {
  $("#form-agregar").reset();
  $("#d-error").textContent = "";
  $("#dialogo").showModal();
}

async function agregar(ev) {
  ev.preventDefault();
  const f = new FormData(ev.target);
  try {
    await api("/api/agregar", Object.fromEntries(f.entries()));
    $("#dialogo").close();
    await cargar();
  } catch (e) {
    $("#d-error").textContent = e.message;
  }
}

// ------------------------------------------------------------------ fondo y buscador
function aplicarFondo(p) {
  if (!p) return;
  estado.prefs = p;
  try { localStorage.setItem(CLAVE_PREFS, JSON.stringify(p)); } catch { /* sin almacenamiento: no pasa nada */ }
  const b = document.body;
  b.classList.remove(...[...b.classList].filter((c) => c.startsWith("fondo-")));
  const foto = p.fondo === "foto" && p.foto;
  b.style.backgroundImage = foto ? `linear-gradient(rgba(0,0,0,.2),rgba(0,0,0,.2)),url("${urlFoto(p.foto, "fondo")}")` : "";
  if (!foto && p.fondo !== "liso") b.classList.add("fondo-" + p.fondo);
  b.classList.toggle("con-fondo", p.fondo !== "liso");
}

async function guardarPrefs(cambio, selectorError = "#f-error") {
  $(selectorError).textContent = "";
  try {
    const r = await api("/api/preferencias", cambio);
    aplicarFondo(r.preferencias);
    marcarElegidos();
    return true;
  } catch (e) {
    $(selectorError).textContent = e.message;
    return false;
  }
}

function marcarElegidos() {
  const p = estado.prefs || {};
  for (const el of document.querySelectorAll("#temas .tema")) el.classList.toggle("elegido", p.fondo === el.dataset.tema);
  for (const el of document.querySelectorAll("#fotos .foto")) el.classList.toggle("elegido", p.fondo === "foto" && p.foto === el.dataset.ruta);
  $("#buscador").value = p.buscador || "duckduckgo";
}

async function abrirFondo() {
  const temas = $("#temas");
  temas.replaceChildren(...TEMAS.map(([id, nombre]) => nuevo("button", {
    type: "button", clase: "tema " + (id === "liso" ? "liso" : "fondo-" + id), "data-tema": id, texto: nombre,
    onclick: () => guardarPrefs({ fondo: id }),
  })));
  $("#f-error").textContent = "";
  marcarElegidos();
  $("#dialogo-fondo").showModal();
  const fotos = $("#fotos");
  try {
    const r = await api("/api/fotos");
    fotos.replaceChildren(...(r.fotos.length ? r.fotos.map((ruta) => nuevo("button", {
      type: "button", clase: "foto", "data-ruta": ruta, title: ruta.split("/").pop(),
      onclick: () => guardarPrefs({ fondo: "foto", foto: ruta }),
    }, [nuevo("img", { src: urlFoto(ruta, "mini"), alt: "", loading: "lazy" })]))
      : [nuevo("p", { clase: "nota", texto: "No photos were found in Pictures, Desktop or the system backgrounds." })]));
    marcarElegidos();
  } catch (e) {
    fotos.replaceChildren(nuevo("p", { clase: "nota", texto: "Could not read the photos: " + e.message }));
  }
}

function buscarWeb(ev) {
  ev.preventDefault();
  const q = $("#web").value.trim();
  if (!q) return;
  const base = BUSCAR_WEB[(estado.prefs || {}).buscador] || BUSCAR_WEB.duckduckgo;
  window.open(base + encodeURIComponent(q), "_blank", "noopener");
  $("#web").value = "";
}

// ------------------------------------------------------------------ About, your data, privacy
async function abrirAcerca() {
  $("#ac-error").textContent = "";
  $("#dialogo-acerca").showModal();
  try {
    const [acerca, cont] = await Promise.all([api("/api/about"), api("/api/continue")]);
    estado.continuar = cont;
    $("#ac-edicion").textContent = acerca.edition;
    $("#ac-version").textContent = acerca.version;
    $("#ac-config").textContent = acerca.config_path;
    $("#ac-continue").textContent = acerca.continue_path;
    pintarAcerca();
  } catch (e) { $("#ac-error").textContent = e.message; }
}

function pintarAcerca() {
  const p = estado.prefs || {};
  const cont = estado.continuar || { projects: [] };
  const notas = cont.projects.filter((x) => x.note).length;
  $("#ac-recordar").checked = p.recordar !== false;
  $("#ac-mostrar-tl").checked = p.show_maker_links !== false;
  $("#ac-maker").hidden = p.show_maker_links === false;
  $("#ac-cuenta").textContent = cont.projects.length
    ? `Saved for ${cont.projects.length} item(s), ${notas} with a note.` : "Nothing is saved yet.";
  $("#ac-borrar").disabled = !cont.projects.length;
  $("#ac-borrar").textContent = "Clear all of it";
  $("#ac-buscadas").replaceChildren(...((estado.datos?.onboarding?.carpetas_buscadas || []).length
    ? estado.datos.onboarding.carpetas_buscadas.map((ruta) => nuevo("li", {}, [nuevo("code", { texto: ruta }),
      nuevo("button", { type: "button", texto: "Stop searching", onclick: () => dejarDeBuscar(ruta) })]))
    : [nuevo("li", { clase: "nota", texto: "None. Use the first-run guide or add folders as projects." })]));
}

async function dejarDeBuscar(ruta) {
  try {
    await api("/api/unscan", { donde: ruta });
    await cargar(true);
    pintarAcerca();
  } catch (e) { $("#ac-error").textContent = e.message; }
}

async function borrarTodoContinuar() {
  const b = $("#ac-borrar");
  if (b.dataset.seguro !== "1") {            // two clicks: the first one only asks
    b.dataset.seguro = "1";
    b.textContent = "Click again to delete it all";
    setTimeout(() => { b.dataset.seguro = ""; if (b.textContent.startsWith("Click")) b.textContent = "Clear all of it"; }, 5000);
    return;
  }
  b.dataset.seguro = "";
  try {
    await api("/api/continue/clear", { confirm: true });
    await cargarContinuar();
    pintarAcerca();
    pintar();
  } catch (e) { $("#ac-error").textContent = e.message; }
}

// ------------------------------------------------------------------ optional plugin (only present in some builds)
async function cargarPlugin() {
  let info;
  try { info = await api("/api/plugin"); } catch { return; }
  if (!info.loaded) return;                  // Community build: nothing to add
  const base = "/plugin/";
  for (const css of info.styles) document.head.append(nuevo("link", { rel: "stylesheet", href: base + css }));
  if (info.fragment) {
    try {
      const r = await fetch(base + info.fragment);
      const doc = new DOMParser().parseFromString(await r.text(), "text/html");
      for (const el of [...doc.body.children]) {
        const slot = el.dataset.slot;
        if (slot === "header-actions") document.querySelector(".acciones").prepend(el);
        else if (slot === "main-top") document.querySelector("main").prepend(el);
      }
    } catch { /* a broken plugin fragment must not break the app */ }
  }
  for (const js of info.scripts) {
    await new Promise((listo) => {
      const tag = document.createElement("script");
      tag.src = base + js;
      tag.onload = tag.onerror = listo;
      document.body.append(tag);
    });
  }
}

// ------------------------------------------------------------------ arranque
document.addEventListener("DOMContentLoaded", () => {
  try { aplicarFondo(JSON.parse(localStorage.getItem(CLAVE_PREFS))); } catch { /* la primera vez no hay nada */ }
  $("#form-web").addEventListener("submit", buscarWeb);
  $("#fondo").addEventListener("click", abrirFondo);
  $("#f-cerrar").addEventListener("click", () => $("#dialogo-fondo").close());
  $("#buscador").addEventListener("change", (e) => guardarPrefs({ buscador: e.target.value }));
  $("#buscar").addEventListener("input", (e) => { estado.busca = e.target.value; pintar(); });
  $("#refrescar").addEventListener("click", () => cargar(true));
  $("#agregar").addEventListener("click", abrirDialogo);
  $("#d-cancelar").addEventListener("click", () => $("#dialogo").close());
  $("#form-agregar").addEventListener("submit", agregar);
  $("#cerrar").addEventListener("click", cerrarPanel);
  const hayDialogo = () => document.querySelector("dialog[open]") !== null;
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !hayDialogo()) cerrarPanel();
    const escribiendo = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "");
    if (e.key === "/" && !escribiendo && !hayDialogo()) { e.preventDefault(); $("#buscar").focus(); }
  });
  $("#tema").addEventListener("click", alternarTema);
  $("#acerca").addEventListener("click", abrirAcerca);
  $("#ac-cerrar").addEventListener("click", () => $("#dialogo-acerca").close());
  $("#ac-borrar").addEventListener("click", borrarTodoContinuar);
  $("#ac-recordar").addEventListener("change", async (e) => { if (!(await guardarPrefs({ recordar: e.target.checked }, "#ac-error"))) e.target.checked = !e.target.checked; });
  $("#ac-mostrar-tl").addEventListener("change", async (e) => { if (await guardarPrefs({ show_maker_links: e.target.checked }, "#ac-error")) pintarAcerca(); else e.target.checked = !e.target.checked; });
  $("#pc-guardar").addEventListener("click", guardarNota);
  $("#pc-olvidar").addEventListener("click", olvidarItem);
  $("#bv-form").addEventListener("submit", (e) => { e.preventDefault(); escanear($("#bv-ruta").value.trim()); });
  $("#bv-uno").addEventListener("click", agregarComoProyecto);
  try { Object.assign(estado, JSON.parse(localStorage.getItem(CLAVE_VISTA)) || {}); } catch { /* first visit */ }
  if (!["recent", "opened", "name", "name-desc", "unsaved"].includes(estado.orden)) estado.orden = "recent";
  estado.soloSinGuardar = estado.soloSinGuardar === true;
  $("#orden").value = estado.orden;
  $("#solo-sin-guardar").checked = estado.soloSinGuardar;
  const guardarVista = () => { try { localStorage.setItem(CLAVE_VISTA, JSON.stringify({ orden: estado.orden, soloSinGuardar: estado.soloSinGuardar })); } catch { /* ignore */ } };
  $("#orden").addEventListener("change", (e) => { estado.orden = e.target.value; guardarVista(); pintar(); });
  $("#solo-sin-guardar").addEventListener("change", (e) => { estado.soloSinGuardar = e.target.checked; guardarVista(); pintar(); });
  for (const b of document.querySelectorAll("#pestanas button")) {
    b.addEventListener("click", () => {
      document.querySelectorAll("#pestanas button").forEach((x) => x.classList.toggle("activa", x === b));
      estado.tipo = b.dataset.tipo;
      pintar();
    });
  }
  cargarPlugin();
  cargar();
  setInterval(() => { if (!document.hidden) cargar(); }, 120000);   // always open: it refreshes itself
});
