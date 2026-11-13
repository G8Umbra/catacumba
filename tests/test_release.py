# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
"""Release hardening of the Community tree: English-only user-visible text, neutral names, MPL-2.0 headers,
local-only data (no non-loopback network access while the app is used), and a safe first run with no config
or an unwritable settings folder. Everything runs in temporary folders."""
import ast
import http.client
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

ROOT = support.ROOT
STATIC = ROOT / "estatico"


def community_files(suffixes):
    """Every Community source file (never anything under personal/)."""
    out = [p for p in sorted(ROOT.rglob("*")) if p.is_file() and p.suffix in suffixes
           and "personal" not in p.relative_to(ROOT).parts and not ({".git", "__pycache__"} & set(p.relative_to(ROOT).parts))]
    return out


# ------------------------------------------------------------------ 1. English only
SPANISH_WORDS = set("""el la los las del para con sin una sus aquí todavía también ahora hay está esta esa ese ruta carpeta carpetas
página páginas repositorio repositorios agregar buscar guardar cancelar quitar abrir eliminar copiar leyendo nuevo nada solo
máquina usuario nombre descanso enfoque iniciar actualizar favoritos fondo cambios sesión resultado texto
escriba escoja marque tarjeta lista pantalla dónde qué cómo porque puede pude encontré encuentra existe tiene debe escoja
sí hace días momento ayer último últimos""".split())
ACCENT = re.compile(r"[áéíóúñ¿¡ÁÉÍÓÚÑ]")


def spanish_hits(texts):
    """Strings that look Spanish: an accented letter / inverted mark, or a word from the Spanish list."""
    hits = []
    for t in texts:
        palabras = re.findall(r"[^\W\d_]+", t.lower())
        if ACCENT.search(t) or any(p in SPANISH_WORDS for p in palabras):
            hits.append(t)
    return hits


class TextOf(HTMLParser):
    def __init__(self):
        super().__init__()
        self.texts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        for k, v in attrs:
            if k in ("placeholder", "aria-label", "title", "alt") and v:
                self.texts.append(v)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.texts.append(data.strip())


def html_texts(html):
    p = TextOf()
    p.feed(html)
    return p.texts


def js_texts(code):
    """String literals that are sentences or labels: they contain a space or start with a capital letter. Selectors and
    class names (internal identifiers) are not user-visible text and are skipped."""
    out = []
    for m in re.finditer(r'"((?:[^"\\\n]|\\.)*)"|`((?:[^`\\]|\\.)*)`', code):
        s = m.group(1) if m.group(1) is not None else m.group(2)
        if re.search(r"(clase:\s*|className\s*=\s*)$", code[:m.start()]):       # CSS class names are identifiers
            continue
        if s and not s.startswith(("#", ".", "/", "data-", "aria-")) and (" " in s or s[0].isupper() or ACCENT.search(s)):
            out.append(re.sub(r"\$\{[^}]*\}", " ", s))
    return out


def py_texts(code):
    """User-visible text of the server: messages of ValueError, {"error": ...} replies and the type labels."""
    out = []
    for nodo in ast.walk(ast.parse(code)):
        if isinstance(nodo, ast.Call) and getattr(nodo.func, "id", "") == "ValueError":
            for a in nodo.args:
                out += [c.value for c in ast.walk(a) if isinstance(c, ast.Constant) and isinstance(c.value, str)]
        if isinstance(nodo, ast.Dict):
            for k, v in zip(nodo.keys, nodo.values):
                if isinstance(k, ast.Constant) and k.value in ("error", "texto", "mensaje") and isinstance(v, ast.Constant):
                    out.append(v.value)
        if isinstance(nodo, ast.Assign) and any(getattr(t, "id", "") == "TIPOS" for t in nodo.targets):
            out += [c.value for c in nodo.value.values if isinstance(c, ast.Constant)]
    return out


def all_visible_texts(root=ROOT):
    out = {}
    out["index.html"] = html_texts((root / "estatico" / "index.html").read_text(encoding="utf-8"))
    for f in sorted((root / "estatico").glob("*.js")):
        out[f.name] = js_texts(f.read_text(encoding="utf-8"))
    out["servidor.py"] = py_texts((root / "servidor.py").read_text(encoding="utf-8"))
    for name in ("README.md", "abrir_catacumba.sh"):
        txt = (root / name).read_text(encoding="utf-8")
        txt = re.sub(r"`[^`\n]*`", " ", txt)                      # code spans are identifiers
        txt = re.sub(r"\S+\.(?:sh|py|json|md)\b", " ", txt)          # file names are identifiers
        out[name] = [ln for ln in txt.splitlines() if not ln.lstrip().startswith(("#!", "    "))]
    return out


class TestEnglishOnly(unittest.TestCase):
    def test_no_spanish_in_user_visible_community_text(self):
        for archivo, textos in all_visible_texts().items():
            self.assertEqual(spanish_hits(textos), [], f"Spanish text found in {archivo}")

    def test_the_detector_catches_spanish_and_accepts_english(self):
        for malo in ("Guardar cambios", "No hay nada aquí", "Está listo", "Carpeta", "Último cambio", "¿Responde?"):
            self.assertEqual(spanish_hits([malo]), [malo], malo)
        for bueno in ("Save changes", "Nothing here yet", "Latest change", "No answer", "Add it as one project"):
            self.assertEqual(spanish_hits([bueno]), [], bueno)

    def test_a_spanish_string_planted_in_any_community_file_is_found(self):
        with tempfile.TemporaryDirectory() as t:
            copia = support.community_copy(Path(t) / "tree")
            shutil_copy = __import__("shutil").copy2
            shutil_copy(ROOT / "README.md", copia / "README.md")
            shutil_copy(ROOT / "abrir_catacumba.sh", copia / "abrir_catacumba.sh")
            self.assertEqual(sum(len(spanish_hits(v)) for v in all_visible_texts(copia).values()), 0)
            h = copia / "estatico" / "index.html"
            h.write_text(h.read_text(encoding="utf-8").replace("<h1>Catacumba</h1>", "<h1>Catacumba</h1><p>Guardar en la carpeta</p>"), encoding="utf-8")
            j = copia / "estatico" / "app.js"
            j.write_text(j.read_text(encoding="utf-8") + '\nconst x = "No se pudo guardar";\n', encoding="utf-8")
            s = copia / "servidor.py"
            s.write_text(s.read_text(encoding="utf-8") + '\ndef _x():\n    raise ValueError("La carpeta no existe")\n', encoding="utf-8")
            hits = {k: spanish_hits(v) for k, v in all_visible_texts(copia).items()}
            self.assertTrue(hits["index.html"] and hits["app.js"] and hits["servidor.py"], hits)

    def test_the_server_answers_in_english(self):
        with tempfile.TemporaryDirectory() as t:
            env = dict(os.environ, CATACUMBA_CONFIG=str(Path(t) / "c.json"), CATACUMBA_PORT="0")
            copia = support.community_copy(Path(t) / "tree")
            codigo = ("import servidor;"
                      "import json;"
                      "res=[];\n"
                      "for f,a in ((servidor.validar_nuevo,({'nombre':'','tipo':'carpeta','donde':'/'},)),"
                      "(servidor.validar_nuevo,({'nombre':'x','tipo':'zzz','donde':'/'},)),"
                      "(servidor.validar_preferencias,({'fondo':'nope'},dict(servidor.PREFERENCIAS)))):\n"
                      "    try: f(*a)\n"
                      "    except ValueError as e: res.append(str(e))\n"
                      "print(json.dumps(res))")
            r = subprocess.run([sys.executable, "-B", "-c", codigo], cwd=str(copia), env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            mensajes = json.loads(r.stdout)
            self.assertEqual(len(mensajes), 3)
            self.assertEqual(spanish_hits(mensajes), [])


# ------------------------------------------------------------------ 2. neutral names
class TestRemovedFeaturesStayRemoved(unittest.TestCase):
    """Two features were removed for provenance reasons. Their words are built from parts so this file does not match itself."""

    WORDS = ("pomo" + "doro", "snip" + "pet", "fragmen" + "to", "catapul" + "ta")

    def shipped(self, root=None):
        """Files a user gets. A clone also holds .git (binary objects): that is version-control metadata, not a shipped file."""
        root = Path(root) if root else ROOT
        return [p for p in sorted(root.rglob("*")) if p.is_file() and "personal" not in p.relative_to(root).parts
                and not ({".git", "__pycache__"} & set(p.relative_to(root).parts)) and p.name != "requests_to_lead.md"]

    def test_the_scan_works_in_a_clone_with_git_metadata_and_binary_files(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".git" / "objects" / "ab").mkdir(parents=True)
            (root / ".git" / "objects" / "ab" / "cdef").write_bytes(b"\x78\x01\xf6\xff\x00binary object")
            (root / "logo.png").write_bytes(b"\x89PNG\xf6\xff")
            (root / "README.md").write_text("plain\n", encoding="utf-8")
            self.assertEqual([f.name for f in self.shipped(root)], ["README.md", "logo.png"])
            for f in self.shipped(root):                       # binary files must be readable by the scan without crashing
                f.read_text(encoding="utf-8", errors="replace")

    def test_no_trace_of_the_removed_features_in_any_shipped_file(self):
        archivos = self.shipped()
        self.assertGreater(len(archivos), 10)
        for f in archivos:
            self.assertFalse(f.name.lower().startswith(self.WORDS), f"file of a removed feature: {f.name}")
            txt = f.read_text(encoding="utf-8", errors="replace").lower()
            for w in self.WORDS:
                self.assertNotIn(w, txt, f"{f.relative_to(ROOT)} still mentions a removed feature ({w})")

    def test_the_readme_license_section_starts_with_the_pseudonymous_copyright_line(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        section = readme.split("## License", 1)[1].lstrip("\n").splitlines()
        self.assertEqual(section[0], "Copyright (c) 2026 G8Umbra")
        self.assertEqual(readme.count("Copyright (c)"), 1)           # one holder line, no other names or organisations

    def test_the_organisation_tagline_is_not_shipped(self):
        """The tagline of an unrelated organisation must not appear in Community (owner decision: no association)."""
        parts = ("Better Diagno" + "stics", "Better Deci" + "sions", "Better Li" + "ves")
        for f in self.shipped():
            if f.name in ("INTEGRATION.md",):
                continue
            txt = f.read_text(encoding="utf-8", errors="replace")
            for w in parts:
                self.assertNotIn(w, txt, f"{f.relative_to(ROOT)} still carries the removed tagline")

    def test_the_remaining_tabs_and_views_are_consistent(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        tabs = re.findall(r'data-tipo="(\w+)"', html)
        self.assertEqual(tabs, ["todo", "repo", "proyecto", "carpeta", "pagina", "favoritos", "ascii"])
        for t in ("todo", "repo", "proyecto", "carpeta", "pagina", "favoritos"):          # card views share one list
            self.assertIn(t, ("todo", "repo", "proyecto", "carpeta", "pagina", "favoritos"))
        self.assertIn('estado.tipo === "ascii"', js)                                    # the only separate view
        self.assertIn('id="ascii-studio"', html)
        self.assertEqual(len(re.findall(r"<section[^>]*\bhidden\b", html)), len(set(re.findall(r'<section id="([\w-]+)"[^>]*\bhidden\b', html))))
        scripts = re.findall(r'<script src="/estatico/([\w.]+)"', html)
        self.assertEqual(sorted(scripts), ["app.js", "ascii.js"])
        links = re.findall(r'<link rel="stylesheet" href="/estatico/([\w.]+)"', html)
        self.assertEqual(sorted(links), ["ascii.css", "estilo.css"])
        for nombre in scripts + links:
            self.assertTrue((STATIC / nombre).is_file(), nombre)
        self.assertEqual(sorted(p.name for p in STATIC.iterdir()), ["app.js", "ascii.css", "ascii.js", "estilo.css", "icono.svg", "index.html"])

    def test_the_readme_lists_only_what_exists_and_states_how_it_is_built(self):
        txt = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("## How it is built", txt)
        self.assertIn("Catacumba Community is developed with AI assistance (Claude Code, by Anthropic) under the direction of G8Umbra, who maintains it.", txt)
        self.assertIn("ASCII banner maker", txt)


class TestNoAccountLinksOrEmails(unittest.TestCase):
    """The public account is not verified yet: shipped Community files carry no repository URL and no email address."""

    def test_no_github_url_and_no_email_in_shipped_files(self):
        host = "".join(("git", "hub", ".com"))
        email = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}")
        archivos = community_files({".py", ".js", ".css", ".html", ".sh", ".md", ".svg", ".json", ".txt"})
        self.assertIn("README.md", [f.name for f in archivos])
        for f in archivos:
            txt = f.read_text(encoding="utf-8")
            self.assertNotIn(host, txt.lower(), f"{f.relative_to(ROOT)} mentions a code-hosting URL")
            if f.name != "test_servidor.py":
                self.assertIsNone(email.search(txt), f"{f.relative_to(ROOT)} contains an email address")

    def test_the_detectors_work(self):
        self.assertTrue(re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}", "write to a.b" + "@" + "example.org"))


class TestNeutralNames(unittest.TestCase):
    def test_the_organisation_name_appears_nowhere_in_the_shipped_tree(self):
        palabra = "templo" + "gic"
        archivos = [p for p in sorted(ROOT.rglob("*")) if p.is_file() and ".git" not in p.relative_to(ROOT).parts
                    and "personal" not in p.relative_to(ROOT).parts and "__pycache__" not in p.parts
                    and p.name not in ("INTEGRATION.md", "requests_to_lead.md")]
        self.assertGreater(len(archivos), 10)
        for f in archivos:
            self.assertNotIn(palabra, f.read_text(encoding="utf-8", errors="ignore").lower(), str(f.relative_to(ROOT)))

    def test_the_readme_names_only_the_maker(self):
        lineas = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
        i = lineas.index("Catacumba Community is made by G8Umbra.")          # exact sentence, wherever it sits
        self.assertEqual(lineas.count("Catacumba Community is made by G8Umbra."), 1)
        self.assertEqual((lineas[i - 1], lineas[i + 1]), ("", ""))             # its own paragraph
        self.assertLess(i, 15)                                                 # near the top, in the introduction

    def test_the_about_dialog_has_no_maker_section_and_no_outbound_link(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("ac-maker", html)
        self.assertEqual(re.findall(r'href="(https?://[^"]+)"', html), [])

    def test_the_backgrounds_are_exactly_the_generic_set(self):
        from_py = re.search(r"TEMAS = \{([^}]*)\}", (ROOT / "servidor.py").read_text(encoding="utf-8")).group(1)
        self.assertEqual(set(re.findall(r'"(\w+)"', from_py)), {"liso", "noche", "blueprint", "compass", "frio", "atardecer", "bosque", "foto"})

    def test_themes_have_neutral_names_and_art(self):
        from_py = re.search(r"TEMAS = \{([^}]*)\}", (ROOT / "servidor.py").read_text(encoding="utf-8")).group(1)
        ids = set(re.findall(r'"(\w+)"', from_py))
        self.assertTrue({"blueprint", "compass"} <= ids)
        css = (STATIC / "estilo.css").read_text(encoding="utf-8")
        for t in ids - {"foto", "liso"}:
            self.assertIn(f"fondo-{t}", css, t)


# ------------------------------------------------------------------ 3. MPL-2.0 headers
MPL = ("This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0. If a copy of the MPL was not "
       "distributed with this file, You can obtain one at https://mozilla.org/MPL/2.0/.")


def has_header(text):
    cabeza = "\n".join(text.splitlines()[:14])
    plano = re.sub(r"^\s*(#|//|/\*|\*|<!--)\s?", "", cabeza, flags=re.M)
    plano = re.sub(r"\s+", " ", plano.replace("-->", " ").replace("*/", " "))
    return MPL in plano and "SPDX-License-Identifier: MPL-2.0" in plano


class TestLicenseHeaders(unittest.TestCase):
    def test_every_community_source_file_carries_the_mpl_header_and_spdx_line(self):
        archivos = community_files({".py", ".js", ".css", ".html", ".sh"})
        self.assertGreaterEqual(len(archivos), 12)
        for f in archivos:
            self.assertTrue(has_header(f.read_text(encoding="utf-8")), f"missing MPL-2.0 header: {f.relative_to(ROOT)}")

    def test_the_detector_rejects_a_missing_or_altered_header(self):
        self.assertTrue(has_header("# " + MPL[:60] + "\n# " + MPL[60:] + "\n# SPDX-License-Identifier: MPL-2.0\nx=1\n"))
        self.assertFalse(has_header("x = 1\n"))
        self.assertFalse(has_header("# " + MPL + "\n"))                                  # no SPDX line
        self.assertFalse(has_header("# " + MPL.replace("v. 2.0", "v. 1.1") + "\n# SPDX-License-Identifier: MPL-2.0\n"))
        self.assertFalse(has_header("\n" * 30 + "# " + MPL + "\n# SPDX-License-Identifier: MPL-2.0\n"))   # not at the top

    def test_no_license_text_is_copied_into_the_tree_and_the_private_plugin_is_not_marked(self):
        if (ROOT / "personal").exists():                         # the development tree: the build adds LICENSE
            self.assertFalse((ROOT / "LICENSE").exists(), "the lab tree must not carry a copy of the license")
        else:                                                    # a built Community tree: the real MPL-2.0 text is there
            self.assertIn("Mozilla Public License Version 2.0", (ROOT / "LICENSE").read_text(encoding="utf-8")[:300])
        for f in (ROOT / "personal").rglob("*.py"):
            self.assertNotIn("SPDX-License-Identifier", f.read_text(encoding="utf-8"), str(f))


# ------------------------------------------------------------------ 4. local-only data
def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


LOOPBACK = {"127.0.0.1", "::1", "localhost"}


class TestLocalOnly(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.home = Path(self.t.name) / "home"
        (self.home / "Projects" / "app").mkdir(parents=True)
        env = dict(GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="T", GIT_COMMITTER_EMAIL="t@e",
                   GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull, PATH=os.environ["PATH"])
        for cmd in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "x", "--allow-empty"]):
            subprocess.run(["git", "-C", str(self.home / "Projects" / "app"), *cmd], check=True, env=env)
        (self.home / "Projects" / "app" / "f.txt").write_text("hello")
        self.port = free_port()
        self.env = {"CATACUMBA_PORT": str(self.port), "CATACUMBA_CONFIG": str(Path(self.t.name) / "cfg" / "c.json")}
        with mock.patch.dict(os.environ, self.env):
            self.s = support.load_servidor(Path(self.t.name) / "tree", "servidor_localonly")
        self.s.HOME = self.home

    def test_the_guard_really_blocks_outside_addresses(self):
        intentos = []
        with self.guard(intentos):
            with self.assertRaises(OSError):
                socket.create_connection((".".join(("203", "0", "113", "7")), 80), timeout=1)
            with self.assertRaises(OSError):
                socket.getaddrinfo("example.com", 80)
        self.assertTrue(intentos)

    def guard(self, intentos):
        real_connect = socket.socket.connect
        real_gai = socket.getaddrinfo

        def connect(sock, addr, *a, **k):
            host = addr[0] if isinstance(addr, tuple) else addr
            if sock.family in (socket.AF_INET, socket.AF_INET6) and host not in LOOPBACK:
                intentos.append(host)
                raise OSError("blocked by the test: non-loopback connection to %s" % (host,))
            return real_connect(sock, addr, *a, **k)

        def gai(host, *a, **k):
            if host not in LOOPBACK and host is not None:
                intentos.append(host)
                raise OSError("blocked by the test: name lookup of %s" % (host,))
            return real_gai(host, *a, **k)

        stack = mock.patch.multiple(socket.socket, connect=connect)
        from contextlib import ExitStack
        es = ExitStack()
        es.enter_context(stack)
        es.enter_context(mock.patch.object(socket, "getaddrinfo", gai))
        return es

    def call(self, metodo, ruta, cuerpo=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        cab = {"Host": f"127.0.0.1:{self.port}"}
        if metodo == "POST":
            cab.update({"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{self.port}"})
        c.request(metodo, ruta, json.dumps(cuerpo or {}) if metodo == "POST" else None, cab)
        r = c.getresponse()
        d = r.read()
        return r.status, (json.loads(d) if r.getheader("Content-Type", "").startswith("application/json") else d)

    def test_first_run_add_project_continue_and_export_open_no_outside_connection(self):
        s = self.s
        srv = s.ThreadingHTTPServer(("127.0.0.1", self.port), s.Manejador)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        intentos = []
        with self.guard(intentos):
            st, d = self.call("GET", "/api/todo")                         # first run, no config yet
            self.assertEqual((st, d["onboarding"]["vacio"]), (200, True))
            self.assertEqual(self.call("GET", "/")[0], 200)
            st, r = self.call("POST", "/api/scan", {"donde": str(self.home / "Projects")})
            self.assertEqual(st, 200, r)
            carpeta = self.home / "Documents" / "novel"
            carpeta.mkdir(parents=True)
            st, r = self.call("POST", "/api/agregar", {"nombre": "novel", "tipo": "proyecto", "donde": str(carpeta)})
            self.assertEqual(st, 200)
            ident = r["item"]["id"]
            self.assertEqual(self.call("POST", "/api/continue/visit", {"id": ident})[0], 200)
            self.assertEqual(self.call("POST", "/api/continue/note", {"id": ident, "note": "chapter 2"})[0], 200)
            st, exp = self.call("GET", "/api/continue/export")
            self.assertEqual((st, exp["projects"][0]["note"]), (200, "chapter 2"))
            self.assertEqual(self.call("GET", "/api/about")[0], 200)
            self.assertEqual(self.call("POST", "/api/preferencias", {"recordar": False})[0], 200)
            self.assertEqual(self.call("POST", "/api/continue/clear", {"confirm": True})[0], 200)
            self.assertEqual(self.call("GET", "/api/todo?fresco=1")[0], 200)
        self.assertEqual(intentos, [], "the app tried to reach a non-loopback address")

    def test_the_only_network_client_code_is_the_user_triggered_page_check(self):
        codigo = (ROOT / "servidor.py").read_text(encoding="utf-8")
        self.assertEqual(sorted(set(re.findall(r"urllib\.request\.\w+|http\.client|requests\.|socket\.create_connection|smtplib|ftplib", codigo))),
                         ["urllib.request.Request", "urllib.request.urlopen"])
        self.assertEqual(len(re.findall(r"urllib\.request\.urlopen", codigo)), 1)
        self.assertIn("catacumba-optional-network", codigo)
        # no analytics / update checks / third-party hosts in the code or the pages
        for f in community_files({".py", ".js", ".html"}):
            if f.parent.name == "tests":
                continue
            txt = f.read_text(encoding="utf-8")
            for host in re.findall(r"https?://([\w.-]+)", txt):
                self.assertIn(host, {"127.0.0.1", "localhost", "mozilla.org", "duckduckgo.com", "www.google.com",
                                     "www.w3.org"}, f"{f.name}: {host}")


# ------------------------------------------------------------------ 5. first run: no config, unwritable folder
class TestFirstRunRobustness(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name)

    def load(self, config, name):
        with mock.patch.dict(os.environ, {"CATACUMBA_CONFIG": str(config), "CATACUMBA_PORT": str(free_port())}):
            s = support.load_servidor(self.root / ("tree-" + name), "servidor_fr_" + name)
        s.HOME = self.root
        return s

    def test_no_config_at_all_creates_a_valid_empty_start(self):
        cfg = self.root / "nothing" / "yet" / "c.json"          # even the parent folders do not exist
        s = self.load(cfg, "a")
        self.assertFalse(cfg.exists())
        c = s.leer_config()
        self.assertTrue(cfg.is_file())
        self.assertEqual((c["extras"], c["buscar_en"]), ([], []))
        self.assertEqual(json.loads(cfg.read_text())["extras"], [])
        self.assertTrue(s.onboarding_state(c, [])["vacio"])

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can write anywhere")
    def test_an_unwritable_settings_folder_gives_a_clear_message_and_no_crash(self):
        bloqueada = self.root / "locked"
        bloqueada.mkdir()
        bloqueada.chmod(0o500)
        self.addCleanup(bloqueada.chmod, 0o700)
        s = self.load(bloqueada / "sub" / "c.json", "b")
        c = s.leer_config()                                       # must not raise
        self.assertTrue(s.onboarding_state(c, [])["vacio"])
        self.assertIn("cannot save its settings", s._memoria["problema"])
        self.assertIn("CATACUMBA_CONFIG", s._memoria["problema"])
        with self.assertRaises(ValueError) as e:                  # a change reports the same clear message
            s.guardar_config(c)
        self.assertIn("cannot save its settings", str(e.exception))
        self.assertEqual(s.continue_summary()["projects"], [])    # reading history with nothing saved is fine
        with self.assertRaises(ValueError) as e2:
            s.save_note({"id": "x-0000abcd", "nombre": "n", "tipo": "proyecto", "donde": str(self.root)}, "hi")
        self.assertIn("cannot save", str(e2.exception))
        port = s.PUERTO
        srv = s.ThreadingHTTPServer(("127.0.0.1", port), s.Manejador)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        h = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
        h.request("GET", "/api/todo", headers={"Host": f"127.0.0.1:{port}"})
        r = h.getresponse()
        d = json.loads(r.read())
        self.assertEqual(r.status, 200)
        self.assertFalse(d["almacenamiento"]["ok"])
        self.assertIn("cannot save its settings", d["almacenamiento"]["mensaje"])
        h = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
        h.request("POST", "/api/agregar", json.dumps({"nombre": "x", "tipo": "carpeta", "donde": str(self.root)}),
                  {"Host": f"127.0.0.1:{port}", "Origin": f"http://127.0.0.1:{port}", "Content-Type": "application/json"})
        r = h.getresponse()
        err = json.loads(r.read())
        self.assertEqual(r.status, 400)
        self.assertIn("cannot save its settings", err["error"])

    def test_the_first_run_controls_are_reachable_and_usable_by_keyboard(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        bloque = re.search(r'<section id="bienvenida".*?</section>', html, flags=re.S).group(0)
        self.assertNotRegex(bloque, r'tabindex="[1-9]')
        self.assertNotRegex(bloque, r"onclick=|<div[^>]*role=\"button\"")
        self.assertIn('<form id="bv-form"', bloque)               # Enter in the path field submits the form
        self.assertIn('type="submit" id="bv-buscar"', bloque)
        for ident in ("bv-ruta", "bv-buscar", "bv-uno"):
            self.assertIn(f'id="{ident}"', bloque)
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn('$("#bv-titulo").focus()', js)              # focus starts at the guide
        self.assertIn('id="bv-titulo" tabindex="-1"', html)


if __name__ == "__main__":
    unittest.main()
