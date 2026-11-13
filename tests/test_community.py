# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
"""New Catacumba behaviour, tested against a Community copy (no plugin folder): guided first run, project folders,
"Continue where you left off" (persist / clear / export / pause / privacy), About data, plugin absent or broken =
clean start, no dead UI, no external requests, no private references. Everything runs in temporary folders."""
import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

ROOT = support.ROOT


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PORT = free_port()
TMP = tempfile.TemporaryDirectory()
FAKE_HOME = Path(TMP.name) / "home"
(FAKE_HOME / "Projects").mkdir(parents=True)
(FAKE_HOME / "Documents").mkdir()
os.environ["CATACUMBA_PORT"] = str(PORT)
os.environ["CATACUMBA_CONFIG"] = str(Path(TMP.name) / "cfg" / "catacumba.json")
os.environ.pop("CATACUMBA_DATA_DIR", None)
servidor = support.load_servidor(Path(TMP.name) / "tree", "servidor_community")
servidor.HOME = FAKE_HOME            # the whole test world lives in a throwaway home

GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="T",
               GIT_COMMITTER_EMAIL="t@e", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)


def repo(ruta):
    ruta.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(ruta)], check=True, env=GIT_ENV)
    (ruta / "a.txt").write_text("x")
    subprocess.run(["git", "-C", str(ruta), "add", "-A"], check=True, env=GIT_ENV)
    subprocess.run(["git", "-C", str(ruta), "commit", "-q", "-m", "First"], check=True, env=GIT_ENV)
    return ruta


def reset_state():
    """Fresh config and history for each test."""
    shutil.rmtree(servidor.CONFIG.parent, ignore_errors=True)
    shutil.rmtree(FAKE_HOME, ignore_errors=True)
    (FAKE_HOME / "Projects").mkdir(parents=True)
    (FAKE_HOME / "Documents").mkdir()
    servidor._cache.update(t=0, repos=[])


class Base(unittest.TestCase):
    def setUp(self):
        reset_state()
        self.addCleanup(reset_state)


# ------------------------------------------------------------------ first run
class TestOnboarding(Base):
    def state(self):
        c = servidor.leer_config()
        return servidor.onboarding_state(c, servidor.todos_los_repos(True))

    def test_fresh_install_starts_empty_and_offers_a_guided_start(self):
        st = self.state()
        self.assertTrue(st["vacio"])
        self.assertEqual(st["carpetas_buscadas"], [])
        self.assertEqual(sorted(os.path.basename(p) for p in st["sugerencias"]), ["Documents", "Projects"])
        self.assertEqual(servidor.leer_config()["extras"], [])

    def test_only_existing_folders_are_suggested_and_none_after_they_are_used(self):
        repo(FAKE_HOME / "Projects" / "app")
        servidor.scan_folder({"donde": str(FAKE_HOME / "Projects")})
        st = self.state()
        self.assertFalse(st["vacio"])
        self.assertEqual(st["sugerencias"], [])            # no suggestions once there is something to show
        self.assertEqual(st["carpetas_buscadas"], [str(FAKE_HOME / "Projects")])

    def test_scanning_a_folder_without_git_projects_changes_nothing(self):
        (FAKE_HOME / "Documents" / "recipes").mkdir()
        with self.assertRaises(ValueError) as e:
            servidor.scan_folder({"donde": str(FAKE_HOME / "Documents")})
        self.assertIn("No git repositories", str(e.exception))
        self.assertEqual(servidor.leer_config()["buscar_en"], [])

    def test_scan_finds_repos_refuses_duplicates_and_can_be_undone(self):
        repo(FAKE_HOME / "Projects" / "one")
        repo(FAKE_HOME / "Projects" / "two")
        r = servidor.scan_folder({"donde": str(FAKE_HOME / "Projects")})
        self.assertEqual(r["encontrados"], 2)
        self.assertEqual(sorted(x["nombre"] for x in servidor.todos_los_repos(True)), ["one", "two"])
        with self.assertRaises(ValueError):
            servidor.scan_folder({"donde": str(FAKE_HOME / "Projects")})
        servidor.unscan_folder({"donde": str(FAKE_HOME / "Projects")})
        self.assertEqual(servidor.todos_los_repos(True), [])
        with self.assertRaises(ValueError):
            servidor.unscan_folder({"donde": str(FAKE_HOME / "Projects")})

    def test_scan_only_accepts_folders_of_the_user(self):
        for malo in ("/etc", "/nonexistent-folder-xyz", str(FAKE_HOME / "Projects" / ".." / ".." / "..")):
            with self.assertRaises(ValueError):
                servidor.scan_folder({"donde": malo})

    def test_adding_one_project_folder_ends_the_first_run_state(self):
        carpeta = FAKE_HOME / "Documents" / "novel"
        carpeta.mkdir()
        servidor.leer_config()
        nuevo = servidor.validar_nuevo({"nombre": "novel", "tipo": "proyecto", "donde": str(carpeta)})
        c = servidor.leer_config()
        c["extras"].append(nuevo)
        servidor.guardar_config(c)
        self.assertFalse(self.state()["vacio"])

    def test_first_run_makes_no_network_call(self):
        def prohibido(*a, **k):
            raise AssertionError("network call during first run")
        with mock.patch.object(urllib.request, "urlopen", prohibido), \
                mock.patch.object(socket, "create_connection", prohibido):
            self.state()
            repo(FAKE_HOME / "Projects" / "app")
            servidor.scan_folder({"donde": str(FAKE_HOME / "Projects")})
            servidor.about()
            servidor.continue_summary()


class TestNoOwnerPages(Base):
    def test_a_fresh_community_install_never_offers_the_owners_pages(self):
        self.assertFalse(hasattr(servidor, "escucha"), "the Community server probes no local ports")
        for _ in range(2):
            reset_state()
            with mock.patch.object(servidor, "HOME", FAKE_HOME):
                cfg = servidor.lista_inicial()
                self.assertEqual(cfg["extras"], [])
                self.assertEqual(cfg["buscar_en"], [])
                self.assertEqual(servidor.todos_los_repos(True), [])
        self.assertEqual([e for e in servidor.leer_config()["extras"] if e["tipo"] == "pagina"], [])


# ------------------------------------------------------------------ continue where you left off
class TestContinue(Base):
    def item(self, nombre="proj", ident="x-0000abcd"):
        carpeta = FAKE_HOME / "Documents" / nombre
        carpeta.mkdir(exist_ok=True)
        return {"id": ident, "nombre": nombre, "tipo": "proyecto", "donde": str(carpeta)}

    def test_visit_remembers_last_opened_and_the_latest_files_without_reading_contents(self):
        it = self.item()
        base = Path(it["donde"])
        (base / "sub").mkdir()
        (base / "node_modules").mkdir()
        (base / ".hidden").write_text("secret-hidden")
        (base / "node_modules" / "skip.js").write_text("x")
        for nombre, edad in (("old.txt", 3000), ("sub/mid.txt", 2000), ("new.txt", 10)):
            f = base / nombre
            f.write_text("TOP-SECRET-CONTENT")
            t = time.time() - edad
            os.utime(f, (t, t))
        r = servidor.record_visit(it)
        self.assertIsNone(r["previous"])
        self.assertEqual([f["path"] for f in r["entry"]["files"]], ["new.txt", os.path.join("sub", "mid.txt"), "old.txt"])
        raw = servidor.continue_path().read_text(encoding="utf-8")
        self.assertNotIn("TOP-SECRET-CONTENT", raw)       # names and times only
        self.assertNotIn("secret-hidden", raw)
        self.assertNotIn("skip.js", raw)
        r2 = servidor.record_visit(it)
        self.assertEqual((r2["previous"]["visits"], r2["entry"]["visits"]), (1, 2))

    def test_history_survives_a_restart(self):
        it = self.item()
        servidor.record_visit(it)
        servidor.save_note(it, "Next: fix chapter 3")
        # a brand-new copy of the server (as after a reboot) reads the same file
        with mock.patch.dict(os.environ, {"CATACUMBA_CONFIG": str(servidor.CONFIG), "CATACUMBA_PORT": str(PORT)}):
            otra = support.load_servidor(Path(TMP.name) / "tree2", "servidor_community_2")
        otra.HOME = FAKE_HOME
        fila = otra.continue_summary()["projects"][0]
        self.assertEqual((fila["id"], fila["note"], fila["visits"]), (it["id"], "Next: fix chapter 3", 1))

    def test_notes_are_trimmed_capped_and_kept_across_visits(self):
        it = self.item()
        self.assertEqual(servidor.save_note(it, "  hello  ")["note"], "hello")
        self.assertEqual(len(servidor.save_note(it, "x" * 5000)["note"]), servidor.NOTE_MAX)
        servidor.save_note(it, "keep me")
        self.assertEqual(servidor.record_visit(it)["entry"]["note"], "keep me")
        servidor.save_note(it, "")
        self.assertEqual(servidor.continue_summary()["projects"][0]["note"], "")

    def test_forget_one_and_clear_all(self):
        a, b = self.item("a", "x-aaaa1111"), self.item("b", "x-bbbb2222")
        servidor.record_visit(a)
        servidor.record_visit(b)
        servidor.forget("x-aaaa1111")
        self.assertEqual([p["id"] for p in servidor.continue_summary()["projects"]], ["x-bbbb2222"])
        for malo in ("../../etc/passwd", "", None, 5, "x-nothere1"):
            with self.assertRaises(ValueError):
                servidor.forget(malo)
        servidor.clear_continue()
        self.assertFalse(servidor.continue_path().exists())
        self.assertEqual(servidor.continue_summary()["projects"], [])
        servidor.clear_continue()                               # clearing twice is harmless

    def test_pause_stops_all_recording(self):
        it = self.item()
        c = servidor.leer_config()
        c["preferencias"] = servidor.validar_preferencias({"recordar": False}, c["preferencias"])
        servidor.guardar_config(c)
        r = servidor.record_visit(it)
        self.assertEqual((r["enabled"], r["entry"]), (False, None))
        self.assertFalse(servidor.continue_path().exists())
        self.assertFalse(servidor.continue_summary()["enabled"])

    def test_a_damaged_file_does_not_break_anything(self):
        servidor.continue_path().parent.mkdir(parents=True, exist_ok=True)
        servidor.continue_path().write_text("{ not json", encoding="utf-8")
        self.assertEqual(servidor.continue_summary()["projects"], [])
        servidor.record_visit(self.item())                        # the next write replaces it with valid data
        self.assertEqual(len(servidor.continue_summary()["projects"]), 1)

    def test_the_history_is_pruned_to_the_most_recent(self):
        with mock.patch.object(servidor, "CONTINUE_MAX_PROJECTS", 3):
            for n in range(5):
                servidor.record_visit(self.item(f"p{n}", f"x-0000000{n}"))
                time.sleep(1.05)                                  # timestamps have one-second resolution
        self.assertEqual(sorted(p["id"] for p in servidor.continue_summary()["projects"]), ["x-00000002", "x-00000003", "x-00000004"])

    def test_the_data_folder_can_be_moved_by_the_user(self):
        with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ, {"CATACUMBA_DATA_DIR": t}):
            servidor.record_visit(self.item())
            self.assertEqual(servidor.continue_path(), Path(t) / "continue.json")
            self.assertTrue((Path(t) / "continue.json").is_file())

    def test_pages_are_remembered_without_touching_the_disk(self):
        pagina = {"id": "x-0000ffff", "nombre": "Docs", "tipo": "pagina", "donde": "https://example.com/"}
        r = servidor.record_visit(pagina)
        self.assertEqual(r["entry"]["files"], [])


class TestContinueHttp(Base):
    @classmethod
    def setUpClass(cls):
        cls.srv = servidor.ThreadingHTTPServer(("127.0.0.1", PORT), servidor.Manejador)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def call(self, metodo, ruta, cuerpo=None, origen="default"):
        c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
        cab = {"Host": f"127.0.0.1:{PORT}"}
        if metodo == "POST":
            cab["Content-Type"] = "application/json"
            if origen == "default":
                cab["Origin"] = f"http://127.0.0.1:{PORT}"
            elif origen:
                cab["Origin"] = origen
        c.request(metodo, ruta, json.dumps(cuerpo or {}) if metodo == "POST" else None, cab)
        r = c.getresponse()
        datos = r.read()
        cuerpo = json.loads(datos) if r.getheader("Content-Type", "").startswith("application/json") else datos
        return r.status, cuerpo, r

    def test_full_flow_over_http_with_export_and_clear(self):
        carpeta = FAKE_HOME / "Documents" / "flow"
        carpeta.mkdir()
        (carpeta / "main.py").write_text("print(1)")
        st, r, _ = self.call("POST", "/api/agregar", {"nombre": "flow", "tipo": "proyecto", "donde": str(carpeta)})
        ident = r["item"]["id"]
        self.assertEqual(self.call("POST", "/api/continue/visit", {"id": ident})[0], 200)
        self.assertEqual(self.call("POST", "/api/continue/note", {"id": ident, "note": "resume here"})[0], 200)
        st, resumen, _ = self.call("GET", "/api/continue")
        self.assertEqual((st, resumen["projects"][0]["note"], resumen["projects"][0]["files"][0]["path"]), (200, "resume here", "main.py"))
        self.assertTrue(resumen["path"].endswith("continue.json"))
        st, export, resp = self.call("GET", "/api/continue/export")
        self.assertEqual(st, 200)
        self.assertIn("attachment", resp.getheader("Content-Disposition"))
        datos = export
        self.assertEqual((datos["projects"][0]["note"], datos["source"].split()[0]), ("resume here", "Catacumba"))
        # clearing needs an explicit confirmation
        self.assertEqual(self.call("POST", "/api/continue/clear", {})[0], 400)
        self.assertTrue(servidor.continue_path().exists())
        self.assertEqual(self.call("POST", "/api/continue/clear", {"confirm": True})[0], 200)
        self.assertEqual(self.call("GET", "/api/continue")[1]["projects"], [])
        # removing an item from the list also drops its saved history
        self.call("POST", "/api/continue/visit", {"id": ident})
        self.call("POST", "/api/quitar", {"id": ident})
        self.assertEqual(self.call("GET", "/api/continue")[1]["projects"], [])

    def test_only_this_screen_can_write_and_only_known_items_are_recorded(self):
        for ruta in ("/api/continue/visit", "/api/continue/note", "/api/continue/forget", "/api/continue/clear", "/api/scan"):
            self.assertEqual(self.call("POST", ruta, {"id": "x-0000abcd", "confirm": True}, origen=None)[0], 403, ruta)
            self.assertEqual(self.call("POST", ruta, {"id": "x-0000abcd", "confirm": True}, origen="https://evil.example")[0], 403, ruta)
        st, r, _ = self.call("POST", "/api/continue/visit", {"id": "x-0000abcd"})
        self.assertEqual((st, r["error"]), (400, "It is not in the list"))
        self.assertEqual(self.call("GET", "/api/continue")[1]["projects"], [])

    def test_todo_reports_the_first_run_state_and_about_reports_where_data_lives(self):
        st, d, _ = self.call("GET", "/api/todo")
        self.assertEqual(st, 200)
        self.assertTrue(d["onboarding"]["vacio"])
        st, a, _ = self.call("GET", "/api/about")
        self.assertEqual((a["edition"], a["version"]), ("Community", servidor.VERSION))
        self.assertTrue(a["config_path"].endswith("catacumba.json") and a["continue_path"].endswith("continue.json"))
        self.assertEqual(self.call("GET", "/api/plugin")[1], {"loaded": False})

    def test_preferences_accept_only_real_booleans_for_the_new_switches(self):
        for k in ("recordar", "show_maker_links"):
            self.assertEqual(self.call("POST", "/api/preferencias", {k: False})[1]["preferencias"][k], False)
            self.assertEqual(self.call("POST", "/api/preferencias", {k: "no"})[0], 400)
            self.assertEqual(self.call("POST", "/api/preferencias", {k: 0})[0], 400)


# ------------------------------------------------------------------ plugin absent / broken, and no dead UI
def run_server(tree, config, extra_env=None):
    port = free_port()
    env = dict(os.environ, CATACUMBA_PORT=str(port), CATACUMBA_CONFIG=str(config), **(extra_env or {}))
    proc = subprocess.Popen([sys.executable, "-B", str(Path(tree) / "servidor.py")], cwd=str(tree), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for _ in range(80):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/salud", timeout=1):
                return proc, port
        except OSError:
            time.sleep(0.1)
    proc.kill()
    raise AssertionError("server did not start: " + proc.communicate()[1])


def stop(proc):
    proc.terminate()
    try:
        return proc.communicate(timeout=5)[1]
    except subprocess.TimeoutExpired:
        proc.kill()
        return proc.communicate()[1]


def fetch(port, ruta):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{ruta}", timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read()
        finally:
            e.close()


class TestPluginAbsentOrBroken(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.tree = support.community_copy(Path(self.t.name) / "tree")
        self.config = Path(self.t.name) / "cfg" / "catacumba.json"

    def test_community_starts_clean_with_no_plugin_and_no_dead_entries(self):
        proc, port = run_server(self.tree, self.config)
        try:
            st, page = fetch(port, "/")
            self.assertEqual(st, 200)
            self.assertIn(b"<h1>Catacumba</h1>", page)
            self.assertNotIn(b"monitor", page.lower())
            self.assertEqual(json.loads(fetch(port, "/api/plugin")[1]), {"loaded": False})
            self.assertEqual(json.loads(fetch(port, "/api/about")[1])["edition"], "Community")
            todo = json.loads(fetch(port, "/api/todo")[1])
            self.assertTrue(todo["onboarding"]["vacio"])
            self.assertEqual((todo["repos"], todo["extras"]), ([], []))
            for ruta in ("/api/monitor/fuentes", "/api/monitor/datos?fuente=x", "/plugin/monitor.js", "/plugin/monitor.html"):
                self.assertEqual(fetch(port, ruta)[0], 404, ruta)
            for ruta in ("/estatico/app.js", "/estatico/estilo.css", "/estatico/ascii.js"):
                self.assertEqual(fetch(port, ruta)[0], 200, ruta)
            # the first-run section is part of the served page
            self.assertIn(b'id="bienvenida"', page)
            self.assertIn(b"Welcome to Catacumba", page)
        finally:
            err = stop(proc)
        self.assertNotIn("Traceback", err)
        self.assertNotIn("plugin not loaded", err)

    def test_the_folder_checker_style_hygiene_server_has_no_import_of_the_plugin_package(self):
        codigo = (ROOT / "servidor.py").read_text(encoding="utf-8")
        self.assertNotRegex(codigo, r"^\s*(import|from)\s+personal\b", "no static import of the plugin package")

    def test_a_broken_plugin_never_stops_the_app(self):
        (self.tree / "personal").mkdir()
        (self.tree / "personal" / "plugin.py").write_text("raise RuntimeError('boom')\n")
        proc, port = run_server(self.tree, self.config)
        try:
            self.assertEqual(json.loads(fetch(port, "/api/plugin")[1]), {"loaded": False})
            self.assertEqual(fetch(port, "/")[0], 200)
            self.assertIn("plugin_error", json.loads(fetch(port, "/api/about")[1]))
            self.assertIn("boom", json.loads(fetch(port, "/api/about")[1])["plugin_error"])
        finally:
            err = stop(proc)
        self.assertIn("plugin not loaded", err)

    def test_a_plugin_of_another_api_version_is_refused_cleanly(self):
        (self.tree / "personal").mkdir()
        (self.tree / "personal" / "plugin.py").write_text("API_VERSION = 2\ndef register(host):\n    return {'name': 'X'}\n")
        proc, port = run_server(self.tree, self.config)
        try:
            self.assertEqual(json.loads(fetch(port, "/api/plugin")[1]), {"loaded": False})
            self.assertIn("API version", json.loads(fetch(port, "/api/about")[1])["plugin_error"])
        finally:
            stop(proc)

    def test_a_plugin_without_a_name_is_refused_cleanly(self):
        (self.tree / "personal").mkdir()
        (self.tree / "personal" / "plugin.py").write_text("def register(host):\n    return {}\n")
        proc, port = run_server(self.tree, self.config)
        try:
            self.assertEqual(json.loads(fetch(port, "/api/plugin")[1]), {"loaded": False})
        finally:
            stop(proc)

    def test_a_minimal_plugin_adds_a_route_a_chip_and_a_detail_section(self):
        (self.tree / "personal").mkdir()
        (self.tree / "personal" / "static").mkdir()
        (self.tree / "personal" / "static" / "x.js").write_text("window.__x=1;")
        (self.tree / "personal" / "plugin.py").write_text(
            "def register(host):\n"
            "    return {'name': 'Demo', 'routes_get': {'/api/demo': lambda q: (200, {'hi': 1})},\n"
            "            'repo_extra': lambda info: info.setdefault('chips', []).append('demo-chip'),\n"
            "            'detail': lambda path: [{'titulo': 'T', 'texto': 'body'}],\n"
            "            'ui': {'scripts': ['x.js']}}\n")
        repo(Path(self.t.name) / "work" / "r1")
        self.config.parent.mkdir(parents=True)
        self.config.write_text(json.dumps({"buscar_en": [str(Path(self.t.name) / "work")], "profundidad": 2, "ignorar": [], "extras": []}))
        proc, port = run_server(self.tree, self.config)
        try:
            self.assertEqual(json.loads(fetch(port, "/api/plugin")[1])["name"], "Demo")
            self.assertEqual(json.loads(fetch(port, "/api/demo")[1]), {"hi": 1})
            self.assertEqual(fetch(port, "/plugin/x.js")[0], 200)
            self.assertEqual(fetch(port, "/plugin/../plugin.py")[0], 404)
            todo = json.loads(fetch(port, "/api/todo")[1])
            self.assertEqual(todo["repos"][0]["chips"], ["demo-chip"])
            self.assertFalse(todo["onboarding"]["vacio"])
        finally:
            stop(proc)


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def parse_index():
    p = Page()
    p.feed((ROOT / "estatico" / "index.html").read_text(encoding="utf-8"))
    return p.tags


class TestInterface(unittest.TestCase):
    def test_every_id_the_script_uses_exists_in_the_page(self):
        ids = {a["id"] for _, a in parse_index() if "id" in a}
        js = (ROOT / "estatico" / "app.js").read_text(encoding="utf-8")
        usados = set(re.findall(r'\$\("#([\w-]+)"\)', js))
        usados |= set(re.findall(r'querySelector\("#([\w-]+)"\)', (ROOT / "estatico" / "ascii.js").read_text(encoding="utf-8")))
        self.assertEqual(sorted(usados - ids), [], "the script refers to elements that do not exist (dead UI)")

    def test_every_tab_has_a_view(self):
        tabs = {a["data-tipo"] for t, a in parse_index() if t == "button" and "data-tipo" in a}
        self.assertEqual(tabs, {"todo", "repo", "proyecto", "carpeta", "pagina", "favoritos", "ascii"})

    def test_basic_accessibility_of_the_page(self):
        tags = parse_index()
        attrs = [a for _, a in tags]
        self.assertTrue(any(t == "meta" and a.get("name") == "viewport" for t, a in tags))
        self.assertTrue(any(a.get("class") == "saltar" and a.get("href") == "#principal" for a in attrs))
        self.assertTrue(any(t == "main" and a.get("id") == "principal" for t, a in tags))
        for t, a in tags:
            if t == "dialog":
                self.assertIn("aria-labelledby", a, a.get("id"))
        # every form control has a label (wrapping label, label[for] or aria-label)
        html = (ROOT / "estatico" / "index.html").read_text(encoding="utf-8")
        para = set(re.findall(r'<label[^>]*\bfor="([^"]+)"', html))
        for t, a in tags:
            if t in ("input", "select", "textarea") and a.get("type") not in ("hidden",):
                ident = a.get("id")
                envuelto = ident is None or re.search(r"<label[^>]*>(?:(?!</label>).)*\bid=\"%s\"" % re.escape(ident), html, re.S)
                self.assertTrue(a.get("aria-label") or ident in para or envuelto, f"unlabelled control: {a}")

    def test_the_stylesheet_supports_manual_light_and_dark_phone_width_and_keyboard_focus(self):
        css = (ROOT / "estatico" / "estilo.css").read_text(encoding="utf-8")
        for marca in ("[data-theme=dark]", "[data-theme=light]", "prefers-color-scheme:dark", "max-width:600px", ":focus-visible",
                      "prefers-reduced-motion"):
            self.assertIn(marca, css)

    def test_javascript_parses(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        for f in sorted((ROOT / "estatico").glob("*.js")):
            r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"{f.name}: {r.stderr}")

    def test_the_page_makes_no_external_requests(self):
        ext = re.compile(r"""(?:src|href|url\()\s*=?\s*["']?(https?:)?//""")
        for f in list((ROOT / "estatico").iterdir()):
            if f.suffix not in (".html", ".js", ".css"):
                continue
            txt = f.read_text(encoding="utf-8")
            if f.name == "index.html":
                hallados = re.findall(r"""(?:src|href)=["'](https?://[^"']+)""", txt)
                self.assertEqual(hallados, ["https://templogicsystems.com/"], "only the optional About link may point outside")
            elif f.suffix != ".js":
                self.assertIsNone(ext.search(txt), f.name)
        js = (ROOT / "estatico" / "app.js").read_text(encoding="utf-8")
        for llamada in re.findall(r"fetch\(([^)]*)\)", js):
            self.assertTrue(llamada.strip().startswith(("ruta", "base")), llamada)
        # the only outbound navigation is the web-search box the user types into
        self.assertEqual(sorted(re.findall(r'"(https://[^"]+)"', js)), ["https://duckduckgo.com/?q=", "https://www.google.com/search?q="])


# Structural checks only: they name no private person, machine, network or folder. They look for the SHAPE of private data.
PLACEHOLDER_USERS = {"you", "user", "username", "yourname", "name", "example"}
HOME_PATH = re.compile(r"/(?:home|Users)/([\w.-]+)")
TAILNET_HOST = re.compile(r"\.ts\.net\b")
PRIVATE_IP = re.compile(r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
                        r"|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3})\b")
SECRET_SHAPE = re.compile(r"(?i)\b(?:api[_-]?key|secret|token|passw(?:or)?d)\b\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{16,}|BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY")
PERSONAL_IMPORT = re.compile(r"(?m)^\s*(?:import|from)\s+personal\b")


def private_findings(txt):
    """Shapes of private data in a text: a real home path, a tailnet host, a private IP, a secret, an import of the private plugin."""
    out = [("home path", m.group(0)) for m in HOME_PATH.finditer(txt) if m.group(1).lower() not in PLACEHOLDER_USERS]
    out += [("tailnet host", m.group(0)) for m in TAILNET_HOST.finditer(txt)]
    out += [("private IP", m.group(0)) for m in PRIVATE_IP.finditer(txt)]
    out += [("secret", m.group(0)[:20]) for m in SECRET_SHAPE.finditer(txt)]
    out += [("plugin import", m.group(0).strip()) for m in PERSONAL_IMPORT.finditer(txt)]
    return out


class TestNoPrivateReferences(unittest.TestCase):
    """Community files carry no private data, detected by shape (no private name is listed anywhere in this tree)."""

    def shipped(self, root=None):
        """The text files a user gets. Version-control metadata (a clone has .git with binary objects) and caches are not shipped files."""
        root = Path(root) if root else ROOT
        files = [p for p in sorted(root.rglob("*")) if p.is_file() and "personal" not in p.relative_to(root).parts
                 and not ({".git", "__pycache__"} & set(p.relative_to(root).parts))
                 and p.suffix in (".py", ".js", ".css", ".html", ".sh", ".md", ".svg", ".json", ".txt", "")]
        return [f for f in files if f.name not in ("INTEGRATION.md", "requests_to_lead.md")]

    def test_a_clone_with_git_metadata_and_binary_files_is_scanned_without_crashing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".git" / "objects" / "ab").mkdir(parents=True)
            (root / ".git" / "objects" / "ab" / "cdef").write_bytes(b"\x78\x01\xf6\xff\x00binary object")   # no suffix, not UTF-8
            (root / "README.md").write_text("plain text\n", encoding="utf-8")
            (root / "logo.png").write_bytes(b"\x89PNG\xf6\xff")
            self.assertEqual([f.name for f in self.shipped(root)], ["README.md"])

    def test_community_files_are_clean(self):
        archivos = self.shipped()
        self.assertGreater(len(archivos), 10)
        malos = [(f.name, k, v) for f in archivos for k, v in private_findings(f.read_text(encoding="utf-8", errors="replace"))]
        self.assertEqual(malos, [])

    def test_there_is_no_key_or_environment_file_in_the_tree(self):
        nombres = [p.name for p in ROOT.rglob("*") if p.is_file() and "personal" not in p.relative_to(ROOT).parts
                   and ".git" not in p.relative_to(ROOT).parts]
        self.assertEqual([n for n in nombres if n.startswith(".env") or n.endswith((".pem", ".key", ".env"))], [])

    def test_the_detectors_catch_each_shape_and_accept_placeholders(self):
        casos = {
            "home path": "/home/" + "alice/projects",
            "home path ": "/Users/" + "bob/Documents",
            "tailnet host": "https://box." + "tailnet" + ".ts" + ".net/app",
            "private IP": "http://" + "10.0." + "0.5:8000/",
            "private IP ": "http://" + "192.168." + "1.20/",
            "private IP  ": "http://" + "172.20." + "0.1/",
            "private IP   ": "http://" + "100.100." + "1.2/",
            "secret": "token = " + "abcd1234abcd1234abcd",
            "plugin import": "import " + "personal",
        }
        for esperado, texto in casos.items():
            self.assertTrue(private_findings(texto), f"not detected: {esperado.strip()}")
            self.assertEqual(private_findings(texto)[0][0], esperado.strip())
        for ok in ("/home/you/projects", "/home/\u2026 or https://", "http://127.0.0.1:8310/", "see https://mozilla.org/MPL/2.0/",
                   "public 203.0.113.9", "token = short"):
            self.assertEqual(private_findings(ok), [], ok)


if __name__ == "__main__":
    unittest.main()
