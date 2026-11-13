# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
"""Catacumba: all your projects, repositories, folders and pages on one local screen.

    python3 servidor.py            opens at http://127.0.0.1:8310 (this machine only)

It only looks and opens. It never deletes, moves or changes your projects. The only things it writes are its own
files in your user config folder: your list (catacumba.json) and the optional "Continue where you left off" notes
(continue.json). Nothing is sent anywhere: no account, no telemetry, no network call on its own. The only network
traffic is what you ask for (checking whether a web page you added answers).

Optional plugin: if a folder named `personal` sits next to this file, it is loaded as a plugin (see
plugin_api in the README). Without it the app is complete and starts with nothing extra.
"""
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import types
from types import SimpleNamespace

VERSION = "0.1.0-dev"
PUERTO = int(os.environ.get("CATACUMBA_PORT", "8310"))
AQUI = Path(__file__).resolve().parent
ESTATICO = AQUI / "estatico"
PLUGIN_DIR = AQUI / "personal"
HOME = Path.home()
CONFIG = Path(os.environ.get("CATACUMBA_CONFIG") or HOME / ".config" / "catacumba" / "catacumba.json")
CACHE_SEG = 30
NO_ENTRAR = {".git", "node_modules", ".venv", "venv", "__pycache__", "snap", ".cache", ".local", ".runtime",
             "target", "dist", "build", ".npm", ".cargo", ".rustup"}
TIPOS = {"repo": "Repository", "proyecto": "Project", "carpeta": "Folder", "pagina": "Page"}
TEMAS = {"liso", "noche", "blueprint", "compass", "frio", "atardecer", "bosque", "foto"}
BUSCADORES = {"duckduckgo", "google"}
PREFERENCIAS = {"fondo": "noche", "foto": "", "buscador": "duckduckgo", "favoritos": [],
                "recordar": True, "show_maker_links": True}
FOTOS_RAICES = [HOME / "Pictures", HOME / "Imágenes", HOME / "Desktop", Path("/usr/share/backgrounds")]
EXT_FOTO = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
FOTO_MAX = 15 * 1024 * 1024
# photos are served shrunk (one at a time, with ImageMagick) to save memory
TAMANOS_FOTO = {"mini": "320x200", "fondo": "1920x1080"}
CACHE_FOTOS = Path(os.environ.get("XDG_CACHE_HOME", HOME / ".cache")) / "catacumba" / "fotos"
NO_SON_FONDOS = ("snapshot", "screenshot", "captura")   # screenshots are not offered as backgrounds
_candado_fotos = threading.Lock()
CANDIDATE_FOLDERS = ("Projects", "projects", "Code", "code", "dev", "Dev", "src", "repos", "git", "workspace",
                     "Documents", "Desktop")


# ------------------------------------------------------------------ plugin boundary
def load_plugin():
    """Load the optional plugin next to this file (<app dir>/personal/plugin.py), by path, never by a static import.
    Returns its registration dict or None. A broken plugin never stops the app: the error is kept in PLUGIN_ERROR."""
    global PLUGIN_ERROR
    entrada = PLUGIN_DIR / "plugin.py"
    if not entrada.is_file():
        return None
    try:
        paquete = types.ModuleType("catacumba_plugin")          # a package whose folder is the plugin folder
        paquete.__path__ = [str(PLUGIN_DIR)]
        sys.modules["catacumba_plugin"] = paquete
        modulo = importlib.import_module("catacumba_plugin.plugin")
        if getattr(modulo, "API_VERSION", 1) != 1:
            raise ValueError(f"plugin API version {modulo.API_VERSION} is not supported (this app speaks 1)")
        host = SimpleNamespace(home=HOME, git=git, hostname=os.uname().nodename, port=PUERTO, version=VERSION)
        reg = modulo.register(host)
        if not isinstance(reg, dict) or not reg.get("name"):
            raise ValueError("register() must return a dict with a name")
        return reg
    except Exception as e:                     # a plugin that fails must not take the app down
        PLUGIN_ERROR = f"{type(e).__name__}: {e}"
        print(f"Catacumba: plugin not loaded ({PLUGIN_ERROR})", file=sys.stderr, flush=True)
        for nombre in [n for n in sys.modules if n == "catacumba_plugin" or n.startswith("catacumba_plugin.")]:
            sys.modules.pop(nombre, None)
        return None


PLUGIN_ERROR = None
PLUGIN = None   # filled in at the end of the module, once git() exists


def plugin_part(clave, defecto=None):
    return (PLUGIN or {}).get(clave, defecto)


# ------------------------------------------------------------------ the list (configuration)
def lista_inicial():
    """What a brand-new install starts with: nothing. The user adds a folder (or the plugin seeds a list)."""
    sembrar = plugin_part("initial_config")
    if sembrar:
        cfg = sembrar(HOME)
        if cfg:
            return cfg
    return {"buscar_en": [], "profundidad": 3, "ignorar": [], "extras": []}


_candado = threading.Lock()


_memoria = {"config": None, "problema": ""}      # used only while the settings folder cannot be written


def problema_de_guardado(carpeta, e):
    return (f"Catacumba cannot save its settings in {carpeta} ({e.strerror or e}). Make that folder writable, "
            "or start Catacumba with CATACUMBA_CONFIG pointing to a file in a folder you can write to.")


def leer_config():
    if not CONFIG.exists():
        inicial = _memoria["config"] or lista_inicial()
        try:
            guardar_config(inicial)
            _memoria.update(config=None, problema="")
        except ValueError as e:                  # unwritable folder: keep working for this session, say why
            _memoria.update(config=inicial, problema=str(e))
            c = json.loads(json.dumps(inicial))
        else:
            c = inicial
    else:
        _memoria.update(config=None, problema="")
        with open(CONFIG, encoding="utf-8") as f:
            c = json.load(f)
    c.setdefault("buscar_en", [str(HOME)])
    c.setdefault("profundidad", 3)
    c.setdefault("ignorar", [])
    c.setdefault("extras", [])
    c["preferencias"] = {**PREFERENCIAS, **c.get("preferencias", {})}
    if c["preferencias"]["fondo"] not in TEMAS:        # a background that no longer exists falls back to the default
        c["preferencias"]["fondo"] = PREFERENCIAS["fondo"]
    return c


def carpeta_privada(carpeta):
    """Create the user-data folder readable only by its owner (0700). A folder that already existed is tightened only
    when it is Catacumba's own default folder; a folder the user chose with CATACUMBA_CONFIG or CATACUMBA_DATA_DIR keeps its mode."""
    existia = carpeta.is_dir()
    carpeta.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not existia or carpeta.name == "catacumba":
        os.chmod(carpeta, 0o700)


def guardar_config(c):
    tmp = CONFIG.with_suffix(".tmp")
    try:
        carpeta_privada(CONFIG.parent)
        with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=1)
        os.replace(tmp, CONFIG)       # a half-written file is never left behind
    except OSError as e:
        raise ValueError(problema_de_guardado(CONFIG.parent, e)) from None


# ------------------------------------------------------------------ git (read-only)
def git(ruta, *args, timeout=10):
    try:
        r = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(ruta), *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def buscar_repos(config):
    """Folders with .git, without entering network mounts or program folders."""
    ignorar = {os.path.realpath(os.path.expanduser(p)) for p in config["ignorar"]}
    hallados = {}
    for raiz in config["buscar_en"]:
        raiz = os.path.realpath(os.path.expanduser(raiz))
        if not os.path.isdir(raiz):
            continue
        base = raiz.count(os.sep)
        for actual, dirs, _ in os.walk(raiz):
            if actual in ignorar or (actual != raiz and os.path.ismount(actual)):
                dirs[:] = []
                continue
            if ".git" in dirs and os.path.isdir(os.path.join(actual, ".git")):
                hallados[os.path.realpath(actual)] = True
                dirs[:] = []                       # a repo inside another one is not searched
                continue
            if actual.count(os.sep) - base >= config["profundidad"]:
                dirs[:] = []
                continue
            dirs[:] = [x for x in dirs if not x.startswith(".") and x not in NO_ENTRAR
                       and os.path.join(actual, x) not in ignorar]
    return sorted(hallados)


def info_repo(ruta):
    ultimo = git(ruta, "log", "-1", "--format=%h%x1f%cI%x1f%s") or ""
    partes = ultimo.strip().split("\x1f")
    estado = git(ruta, "status", "--porcelain")
    return {"id": "r-" + hashlib.sha1(ruta.encode()).hexdigest()[:10], "nombre": os.path.basename(ruta), "tipo": "repo", "donde": ruta,
            "rama": (git(ruta, "rev-parse", "--abbrev-ref", "HEAD") or "").strip(),
            "commit": partes[0] if len(partes) == 3 else "", "fecha": partes[1] if len(partes) == 3 else "",
            "mensaje": partes[2] if len(partes) == 3 else "(sin commits)",
            "sin_guardar": len([x for x in (estado or "").splitlines() if x.strip()]) if estado is not None else None}


def info_repo_completo(ruta):
    """info_repo plus whatever the optional plugin adds to a repository card (chips, buttons)."""
    info = info_repo(ruta)
    extra = plugin_part("repo_extra")
    if extra:
        try:
            extra(info)
        except Exception:                       # a plugin hiccup must not hide the repository
            pass
    return info


_cache = {"t": 0, "repos": []}


def todos_los_repos(forzar=False):
    with _candado:
        if not forzar and time.time() - _cache["t"] < CACHE_SEG:
            return _cache["repos"]
    rutas = buscar_repos(leer_config())
    with ThreadPoolExecutor(max_workers=6) as ex:
        repos = list(ex.map(info_repo_completo, rutas))
    repos.sort(key=lambda r: r["fecha"], reverse=True)
    with _candado:
        _cache.update(t=time.time(), repos=repos)
    return repos


def detalle_repo(ruta):
    log = git(ruta, "log", "-15", "--format=%h%x1f%cs%x1f%s") or ""
    commits = [dict(zip(("commit", "fecha", "mensaje"), ln.split("\x1f"))) for ln in log.splitlines() if ln.count("\x1f") == 2]
    cambios = [ln[3:] for ln in (git(ruta, "status", "--porcelain") or "").splitlines() if ln.strip()][:30]
    d = {"commits": commits, "sin_guardar": cambios, "secciones": []}
    extra = plugin_part("detail")
    if extra:
        try:
            d["secciones"] = list(extra(ruta) or [])
        except Exception:
            pass
    return d


# ------------------------------------------------------------------ fondo y buscador
def foto_permitida(ruta):
    """An image from your picture folders or the system backgrounds; nothing else is served."""
    real = os.path.realpath(str(ruta))
    if os.path.splitext(real)[1].lower() not in EXT_FOTO or not os.path.isfile(real):
        return None
    if os.path.getsize(real) > FOTO_MAX:
        return None
    for raiz in FOTOS_RAICES:
        r = os.path.realpath(raiz)
        if real.startswith(r + os.sep):
            return real
    return None


def listar_fotos(limite=80):
    fotos = []
    for raiz in FOTOS_RAICES:
        if not raiz.is_dir():
            continue
        for actual, dirs, archivos in os.walk(raiz):
            if actual.count(os.sep) - str(raiz).count(os.sep) >= 2:
                dirs[:] = []
            for a in sorted(archivos):
                if a.lower().startswith(NO_SON_FONDOS):
                    continue
                ruta = foto_permitida(os.path.join(actual, a))
                if ruta:
                    fotos.append(ruta)
                if len(fotos) >= limite:
                    return fotos
    return fotos


def foto_achicada(real, tam):
    """Small copy of the photo (kept in ~/.cache). If it cannot be shrunk, the original."""
    medida = TAMANOS_FOTO[tam]
    st = os.stat(real)
    clave = hashlib.sha1(f"{real}|{st.st_mtime_ns}|{st.st_size}|{medida}".encode()).hexdigest()
    destino = CACHE_FOTOS / f"{clave}.jpg"
    with _candado_fotos:
        if not destino.is_file():
            CACHE_FOTOS.mkdir(parents=True, exist_ok=True)
            ancho, alto = (int(n) for n in medida.split("x"))
            temporal = destino.with_suffix(".tmp.jpg")
            try:
                subprocess.run(["convert", "-define", f"jpeg:size={ancho * 2}x{alto * 2}", EXT_FOTO[os.path.splitext(real)[1].lower()].split("/")[1] + ":" + real + "[0]", "-auto-orient",
                                "-thumbnail", medida + ">", "-strip", "-quality", "82", str(temporal)],
                               check=True, timeout=30, capture_output=True)
                temporal.replace(destino)
            except (OSError, subprocess.SubprocessError):
                temporal.unlink(missing_ok=True)
                return real, EXT_FOTO[os.path.splitext(real)[1].lower()]
    return str(destino), "image/jpeg"


def validar_preferencias(datos, actuales):
    nuevas = dict(actuales)
    if "fondo" in datos:
        if datos["fondo"] not in TEMAS:
            raise ValueError("That background does not exist")
        nuevas["fondo"] = datos["fondo"]
    if "foto" in datos:
        foto = foto_permitida(datos["foto"]) if datos["foto"] else ""
        if datos["foto"] and not foto:
            raise ValueError("That photo cannot be used (it must be a jpg, png or webp inside your pictures folders)")
        nuevas["foto"] = foto
    if "buscador" in datos:
        if datos["buscador"] not in BUSCADORES:
            raise ValueError("That search engine is not available")
        nuevas["buscador"] = datos["buscador"]
    if "favoritos" in datos:
        favoritos = datos["favoritos"]
        patron_id = re.compile(r"(?:r-[a-f0-9]{10}|x-[a-f0-9]{8})")
        if not isinstance(favoritos, list) or len(favoritos) > 500 or any(
            not isinstance(ident, str) or not patron_id.fullmatch(ident) for ident in favoritos
        ) or len(set(favoritos)) != len(favoritos):
            raise ValueError("The favorites list is not valid")
        nuevas["favoritos"] = favoritos
    for clave in ("recordar", "show_maker_links"):
        if clave in datos:
            if not isinstance(datos[clave], bool):
                raise ValueError(f"{clave} must be true or false")
            nuevas[clave] = datos[clave]
    if nuevas["fondo"] == "foto" and not nuevas["foto"]:
        raise ValueError("Pick a photo first")
    return nuevas


# ------------------------------------------------------------------ things that are not repos
def con_estado(extra):
    e = dict(extra)
    if e["tipo"] == "pagina":
        e["existe"] = None
    else:
        e["existe"] = os.path.exists(e["donde"])
    return e


def pagina_responde(url):
    # catacumba-optional-network: only when the user presses "Does it answer?" on a web page they added themselves
    try:
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "catacumba"})
        with urllib.request.urlopen(req, timeout=4) as r:
            return r.status < 500
    except urllib.error.HTTPError as err:
        return err.code < 500           # a 401 or 404 also means something answers
    except (OSError, ValueError):
        return False


def carpeta_permitida(donde):
    donde = os.path.realpath(os.path.expanduser(str(donde).strip()))
    if not os.path.isdir(donde):
        raise ValueError("That folder does not exist on this computer")
    home = os.path.realpath(HOME)
    if not (donde == home or donde.startswith(home + os.sep) or donde.startswith("/run/media/")):
        raise ValueError("Only folders in your home folder or on a connected disk are allowed")
    return donde


def validar_nuevo(datos):
    nombre = str(datos.get("nombre", "")).strip()[:80]
    tipo = datos.get("tipo")
    donde = str(datos.get("donde", "")).strip()
    if not nombre:
        raise ValueError("The name is missing")
    if tipo == "pagina":
        if not re.match(r"^https?://[^\s]{1,300}$", donde):
            raise ValueError("The address must start with http:// or https://")
    elif tipo in ("carpeta", "proyecto"):
        donde = carpeta_permitida(donde)
    else:
        raise ValueError("Unknown type")
    return {"id": "x-" + uuid.uuid4().hex[:8], "nombre": nombre, "tipo": tipo, "donde": donde,
            "nota": str(datos.get("nota", "")).strip()[:120]}


def buscar(id_):
    for r in todos_los_repos():
        if r["id"] == id_:
            return r
    for e in leer_config()["extras"]:
        if e["id"] == id_:
            return e
    return None


def abrir(item):
    """Opens the folder in the file manager or the page in the browser. Never a command that comes from the browser."""
    destino = item["donde"]
    if item["tipo"] != "pagina" and not os.path.exists(destino):
        raise ValueError("It no longer exists on this computer")
    subprocess.Popen(["xdg-open", destino if item["tipo"] == "pagina" else os.path.abspath(destino)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def abrir_en_code(item):
    code = next((c for c in ("code", "/snap/bin/code") if subprocess.run(["sh", "-c", f"command -v {c}"],
                 capture_output=True).returncode == 0), None)
    if not code:
        raise ValueError("VS Code was not found on this computer")
    if item["tipo"] == "pagina" or not os.path.isdir(item["donde"]):
        raise ValueError("Only folders can be opened in VS Code")
    subprocess.Popen([code, os.path.abspath(item["donde"])], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


# ------------------------------------------------------------------ onboarding
def folder_suggestions(config):
    """Folders in the user's home that commonly hold projects, so a first-time user can click instead of typing.
    Only names of folders that exist are listed (nothing is read inside them)."""
    ya = {os.path.realpath(p) for p in config["buscar_en"]} | {e["donde"] for e in config["extras"]}
    out = []
    for nombre in CANDIDATE_FOLDERS:
        ruta = HOME / nombre
        if ruta.is_dir() and os.path.realpath(ruta) not in ya:
            out.append(str(ruta))
    return out


def onboarding_state(config, repos):
    """First run = nothing to show yet. The screen then offers a guided start instead of an empty page."""
    vacio = not repos and not config["extras"]
    return {"vacio": vacio, "sugerencias": folder_suggestions(config) if vacio else [],
            "carpetas_buscadas": list(config["buscar_en"])}


def scan_folder(datos):
    """Add a folder to the places searched for git repositories. Refuses (and changes nothing) if it has none."""
    raiz = carpeta_permitida(datos.get("donde", ""))
    with _candado:
        c = leer_config()
        if raiz in {os.path.realpath(p) for p in c["buscar_en"]}:
            raise ValueError("That folder is already being searched.")
    hallados = buscar_repos({"buscar_en": [raiz], "profundidad": c["profundidad"], "ignorar": c["ignorar"]})
    if not hallados:
        raise ValueError("No git repositories were found in that folder (looked %d levels deep). "
                         "You can add it as a project folder instead." % c["profundidad"])
    with _candado:
        c = leer_config()
        c["buscar_en"].append(raiz)
        guardar_config(c)
    todos_los_repos(forzar=True)
    return {"ok": True, "encontrados": len(hallados), "donde": raiz}


def unscan_folder(datos):
    donde = str(datos.get("donde", ""))
    with _candado:
        c = leer_config()
        if donde not in c["buscar_en"]:
            raise ValueError("That folder is not in the search list.")
        c["buscar_en"].remove(donde)
        guardar_config(c)
    todos_los_repos(forzar=True)
    return {"ok": True}


# ------------------------------------------------------------------ Continue where you left off (local only)
CONTINUE_MAX_PROJECTS = 500
NOTE_MAX = 500
FILES_SHOWN = 5
FILES_SCANNED = 3000
ID_PATTERN = re.compile(r"(?:r-[a-f0-9]{10}|x-[a-f0-9]{8})")
_candado_continuar = threading.Lock()


def continue_path():
    base = os.environ.get("CATACUMBA_DATA_DIR")
    return (Path(base) if base else CONFIG.parent) / "continue.json"


def utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def read_continue():
    """The saved history, or an empty one. A damaged file is treated as empty and is never silently overwritten
    by a read (the next write replaces it)."""
    try:
        with open(continue_path(), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("projects"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"version": 1, "projects": {}}


def write_continue(data):
    ruta = continue_path()
    tmp = ruta.with_suffix(".tmp")
    try:
        carpeta_privada(ruta.parent)
        with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, ruta)
    except OSError as e:
        raise ValueError(problema_de_guardado(ruta.parent, e)) from None


def recent_files(raiz, limite=FILES_SHOWN):
    """The most recently modified files under a folder (names and times only; contents are never read)."""
    vistos = []
    base = str(raiz).count(os.sep)
    n = 0
    for actual, dirs, archivos in os.walk(raiz):
        if actual.count(os.sep) - base >= 3:
            dirs[:] = []
        else:
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in NO_ENTRAR]
        for nombre in archivos:
            if nombre.startswith("."):
                continue
            n += 1
            if n > FILES_SCANNED:
                break
            completa = os.path.join(actual, nombre)
            try:
                if os.path.islink(completa):
                    continue
                vistos.append((os.stat(completa).st_mtime, os.path.relpath(completa, raiz)))
            except OSError:
                continue
        if n > FILES_SCANNED:
            break
    vistos.sort(reverse=True)
    return [{"path": rel, "modified": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))} for t, rel in vistos[:limite]]


def record_visit(item):
    """Remember that the user opened this item, and which files in it changed most recently.
    Returns {"previous": the entry as it was before this visit or None, "entry": the new one or None}."""
    if not leer_config()["preferencias"].get("recordar", True):
        return {"previous": None, "entry": None, "enabled": False}
    archivos = recent_files(item["donde"]) if item["tipo"] != "pagina" and os.path.isdir(item["donde"]) else []
    with _candado_continuar:
        datos = read_continue()
        anterior = datos["projects"].get(item["id"])
        nuevo = {"name": item["nombre"], "kind": item["tipo"], "where": item["donde"], "last_opened": utc_now(),
                 "visits": (anterior or {}).get("visits", 0) + 1, "note": (anterior or {}).get("note", ""),
                 "note_at": (anterior or {}).get("note_at", ""), "files": archivos}
        datos["projects"][item["id"]] = nuevo
        if len(datos["projects"]) > CONTINUE_MAX_PROJECTS:     # keep the most recent ones
            ordenados = sorted(datos["projects"].items(), key=lambda kv: kv[1].get("last_opened", ""), reverse=True)
            datos["projects"] = dict(ordenados[:CONTINUE_MAX_PROJECTS])
        write_continue(datos)
    return {"previous": anterior, "entry": nuevo, "enabled": True}


def save_note(item, texto):
    texto = str(texto or "").strip()[:NOTE_MAX]
    with _candado_continuar:
        datos = read_continue()
        e = datos["projects"].setdefault(item["id"], {"name": item["nombre"], "kind": item["tipo"], "where": item["donde"],
                                                      "last_opened": "", "visits": 0, "note": "", "note_at": "", "files": []})
        e["note"], e["note_at"] = texto, (utc_now() if texto else "")
        write_continue(datos)
    return {"ok": True, "note": texto}


def forget(ident):
    if not isinstance(ident, str) or not ID_PATTERN.fullmatch(ident):
        raise ValueError("Not a valid item id.")
    with _candado_continuar:
        datos = read_continue()
        if datos["projects"].pop(ident, None) is None:
            raise ValueError("Nothing is saved for that item.")
        write_continue(datos)
    return {"ok": True}


def clear_continue():
    with _candado_continuar:
        try:
            continue_path().unlink()
        except FileNotFoundError:
            pass
    return {"ok": True}


def continue_summary():
    datos = read_continue()
    filas = [dict(v, id=k) for k, v in datos["projects"].items()]
    filas.sort(key=lambda r: (r.get("last_opened", ""), r.get("note_at", "")), reverse=True)
    return {"path": str(continue_path()), "enabled": leer_config()["preferencias"].get("recordar", True), "projects": filas}


def about():
    return {"version": VERSION, "config_path": str(CONFIG), "continue_path": str(continue_path()),
            "edition": PLUGIN["name"] if PLUGIN else "Community", "plugin_error": PLUGIN_ERROR}


def plugin_info():
    if not PLUGIN:
        return {"loaded": False}
    ui = PLUGIN.get("ui", {})
    return {"loaded": True, "name": PLUGIN["name"], "styles": list(ui.get("styles", [])),
            "scripts": list(ui.get("scripts", [])), "fragment": ui.get("fragment", "")}


# ------------------------------------------------------------------ the server
PERMITIDOS = {f"127.0.0.1:{PUERTO}", f"localhost:{PUERTO}"}
TIPOS_ARCHIVO = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"}


class Manejador(BaseHTTPRequestHandler):
    server_version = "Catacumba"

    def log_message(self, *a):
        pass

    def _responder(self, codigo, cuerpo, tipo="application/json; charset=utf-8", cabeceras=None):
        datos = cuerpo if isinstance(cuerpo, bytes) else json.dumps(cuerpo, ensure_ascii=False).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(datos)))
        self.send_header("Cache-Control", "no-store" if not tipo.startswith("image/") else "max-age=3600")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (cabeceras or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(datos)

    def _host_ok(self):
        # another web page cannot talk to this one (not even through a domain-name trick)
        return self.headers.get("Host", "") in PERMITIDOS

    def do_GET(self):
        if not self._host_ok():
            return self._responder(403, {"error": "this computer only"})
        ruta = self.path.split("?", 1)[0]
        if ruta == "/api/salud":
            return self._responder(200, {"ok": True})
        if ruta == "/api/todo":
            forzar = "fresco=1" in self.path
            config = leer_config()
            repos = todos_los_repos(forzar)
            extras = [con_estado(e) for e in config["extras"]]
            return self._responder(200, {"repos": repos, "extras": extras, "tipos": TIPOS,
                                         "maquina": os.uname().nodename, "preferencias": config["preferencias"],
                                         "onboarding": onboarding_state(config, repos),
                                         "almacenamiento": {"ok": not _memoria["problema"], "mensaje": _memoria["problema"]}})
        if ruta == "/api/about":
            return self._responder(200, about())
        if ruta == "/api/plugin":
            return self._responder(200, plugin_info())
        if ruta == "/api/continue":
            return self._responder(200, continue_summary())
        if ruta == "/api/continue/export":
            cuerpo = json.dumps({"exported_at": utc_now(), "source": "Catacumba " + VERSION, **continue_summary()},
                                ensure_ascii=False, indent=1).encode()
            return self._responder(200, cuerpo, cabeceras={"Content-Disposition": 'attachment; filename="catacumba-continue.json"'})
        if ruta == "/api/fotos":
            return self._responder(200, {"fotos": listar_fotos()})
        if ruta == "/api/foto":
            pide = urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
            real = foto_permitida(pide.get("ruta", [""])[0])
            tam = pide.get("tam", ["fondo"])[0]
            if not real or tam not in TAMANOS_FOTO:
                return self._responder(404, {"error": "not found"})
            archivo, tipo = foto_achicada(real, tam)
            with open(archivo, "rb") as f:
                return self._responder(200, f.read(), tipo)
        if ruta in plugin_part("routes_get", {}):
            pide = urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
            codigo, cuerpo = plugin_part("routes_get")[ruta](pide)
            return self._responder(codigo, cuerpo)
        if ruta == "/" or ruta.startswith("/estatico/") or (PLUGIN and ruta.startswith("/plugin/")):
            raiz = ESTATICO if not ruta.startswith("/plugin/") else PLUGIN_DIR / "static"
            nombre = "index.html" if ruta == "/" else ruta.split("/", 2)[2]
            archivo = (raiz / urllib.parse.unquote(nombre)).resolve()
            if raiz.resolve() not in archivo.parents or not archivo.is_file():
                return self._responder(404, {"error": "not found"})
            return self._responder(200, archivo.read_bytes(), TIPOS_ARCHIVO.get(archivo.suffix, "application/octet-stream"))
        return self._responder(404, {"error": "not found"})

    def do_POST(self):
        origen = self.headers.get("Origin", "")
        if not self._host_ok() or origen not in {"http://" + h for h in PERMITIDOS}:
            return self._responder(403, {"error": "this screen only"})
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            return self._responder(415, {"error": "JSON expected"})
        try:
            largo = max(0, min(int(self.headers.get("Content-Length", "0")), 8192))
            datos = json.loads(self.rfile.read(largo) or b"{}")
        except (ValueError, TypeError):
            return self._responder(400, {"error": "invalid data"})
        try:
            return self._accion(self.path.split("?", 1)[0], datos)
        except ValueError as e:
            return self._responder(400, {"error": str(e)})

    def _accion(self, ruta, datos):
        if ruta == "/api/agregar":
            nuevo = validar_nuevo(datos)
            with _candado:
                c = leer_config()
                c["extras"].append(nuevo)
                guardar_config(c)
            return self._responder(200, {"ok": True, "item": con_estado(nuevo)})
        if ruta == "/api/preferencias":
            with _candado:
                c = leer_config()
                c["preferencias"] = validar_preferencias(datos, c["preferencias"])
                guardar_config(c)
            return self._responder(200, {"ok": True, "preferencias": c["preferencias"]})
        if ruta == "/api/scan":
            return self._responder(200, scan_folder(datos))
        if ruta == "/api/unscan":
            return self._responder(200, unscan_folder(datos))
        if ruta == "/api/continue/forget":
            return self._responder(200, forget(datos.get("id")))
        if ruta == "/api/continue/clear":
            if datos.get("confirm") is not True:
                raise ValueError("Send confirm: true to clear everything.")
            return self._responder(200, clear_continue())
        if ruta == "/api/quitar":
            with _candado:
                c = leer_config()
                antes = len(c["extras"])
                c["extras"] = [e for e in c["extras"] if e["id"] != datos.get("id")]
                if len(c["extras"]) == antes:
                    raise ValueError("It is not in the list")
                guardar_config(c)
            try:
                forget(str(datos.get("id", "")))        # its saved "where I left off" goes with it
            except ValueError:
                pass
            return self._responder(200, {"ok": True})
        item = buscar(str(datos.get("id", "")))
        if not item:
            raise ValueError("It is not in the list")
        if ruta == "/api/continue/visit":
            return self._responder(200, record_visit(item))
        if ruta == "/api/continue/note":
            return self._responder(200, save_note(item, datos.get("note")))
        if ruta == "/api/abrir":
            abrir(item)
            return self._responder(200, {"ok": True})
        if ruta == "/api/code":
            abrir_en_code(item)
            return self._responder(200, {"ok": True})
        if ruta == "/api/detalle" and item["tipo"] == "repo":
            return self._responder(200, detalle_repo(item["donde"]))
        if ruta in plugin_part("routes_post", {}):
            return self._responder(200, plugin_part("routes_post")[ruta](item, datos))
        if ruta == "/api/responde" and item["tipo"] == "pagina":
            return self._responder(200, {"responde": pagina_responde(item["donde"])})
        raise ValueError("Unknown action")


PLUGIN = load_plugin()
if PLUGIN and PLUGIN.get("config_path") and not os.environ.get("CATACUMBA_CONFIG"):
    CONFIG = Path(PLUGIN["config_path"])


def main():
    servidor = ThreadingHTTPServer(("127.0.0.1", PUERTO), Manejador)
    print(f"Catacumba ({PLUGIN['name'] if PLUGIN else 'Community'}) at http://127.0.0.1:{PUERTO}/", flush=True)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    servidor.server_close()


if __name__ == "__main__":
    sys.exit(main())
