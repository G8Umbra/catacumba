# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
"""Catacumba core (Community tree): finds repositories, reads their state, only adds what is valid, and nobody
outside can talk to it. Runs against a COPY of the server without any plugin folder, using throwaway repositories
in temporary folders; it touches none of the user's real data."""
import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    PUERTO_PRUEBA = s.getsockname()[1]
TMP = tempfile.TemporaryDirectory()
os.environ["CATACUMBA_PORT"] = str(PUERTO_PRUEBA)
os.environ["CATACUMBA_CONFIG"] = os.path.join(TMP.name, "tablero.json")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

servidor = support.load_servidor(Path(TMP.name) / "tree", "servidor_core")

GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="T",
               GIT_COMMITTER_EMAIL="t@e", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)


def repo(ruta, mensaje="Primero", sucio=False):
    ruta.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(ruta)], check=True, env=GIT_ENV)
    (ruta / "a.txt").write_text("x")
    subprocess.run(["git", "-C", str(ruta), "add", "-A"], check=True, env=GIT_ENV)
    subprocess.run(["git", "-C", str(ruta), "commit", "-q", "-m", mensaje], check=True, env=GIT_ENV)
    if sucio:
        (ruta / "b.txt").write_text("y")
    return ruta


class TestBuscar(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.raiz = Path(self.t.name)

    def config(self, **kw):
        c = {"buscar_en": [str(self.raiz)], "profundidad": 3, "ignorar": [], "extras": []}
        c.update(kw)
        return c

    def test_encuentra_repos_sin_entrar_a_lo_que_no_debe(self):
        uno = repo(self.raiz / "uno")
        dos = repo(self.raiz / "proyectos" / "dos")
        repo(uno / "adentro")                                  # a repo inside another one does not count separately
        repo(self.raiz / "node_modules" / "paquete")          # carpetas de programas no se recorren
        repo(self.raiz / ".oculta" / "tres")
        repo(self.raiz / "a" / "b" / "c" / "d" / "lejos")     # deeper than the search depth
        ignorada = repo(self.raiz / "Mounted" / "suyo")
        hallados = servidor.buscar_repos(self.config(ignorar=[str(self.raiz / "Mounted")]))
        self.assertEqual(hallados, sorted([str(uno), str(dos)]))
        self.assertNotIn(str(ignorada), hallados)

    def test_estado_de_un_repo(self):
        r = repo(self.raiz / "app", "Arregla el botón", sucio=True)
        i = servidor.info_repo(str(r))
        self.assertEqual((i["nombre"], i["rama"], i["mensaje"], i["sin_guardar"]), ("app", "main", "Arregla el botón", 1))
        self.assertTrue(i["id"].startswith("r-") and i["id"] == servidor.info_repo(str(r))["id"])   # el mismo id siempre

    def test_detalle_y_un_repo_sin_commits(self):
        r = repo(self.raiz / "app", "Primero")
        d = servidor.detalle_repo(str(r))
        self.assertEqual([c["mensaje"] for c in d["commits"]], ["Primero"])
        vacio = self.raiz / "vacio"
        subprocess.run(["git", "init", "-q", str(vacio)], check=True)
        self.assertEqual(servidor.info_repo(str(vacio))["mensaje"], "(sin commits)")


class TestAgregar(unittest.TestCase):
    def test_solo_lo_valido(self):
        home = str(servidor.HOME)
        bien = servidor.validar_nuevo({"nombre": " Mis notas ", "tipo": "carpeta", "donde": home})
        self.assertEqual((bien["nombre"], bien["donde"]), ("Mis notas", home))
        self.assertEqual(servidor.validar_nuevo({"nombre": "P", "tipo": "pagina", "donde": "https://example.com/"})["tipo"], "pagina")
        for malo, texto in (({"nombre": "", "tipo": "carpeta", "donde": home}, "name"),
                            ({"nombre": "x", "tipo": "carpeta", "donde": "/etc"}, "home folder"),
                            ({"nombre": "x", "tipo": "carpeta", "donde": home + "/no-existe-1234"}, "does not exist"),
                            ({"nombre": "x", "tipo": "pagina", "donde": "javascript:alert(1)"}, "http"),
                            ({"nombre": "x", "tipo": "programa", "donde": "/bin/sh"}, "Unknown type")):
            with self.assertRaises(ValueError) as e:
                servidor.validar_nuevo(malo)
            self.assertIn(texto, str(e.exception))


def foto(ruta, ancho=1200, alto=800):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["convert", "-size", f"{ancho}x{alto}", "gradient:navy-orange", str(ruta)], check=True)
    return ruta


class TestFondo(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.raiz = Path(self.t.name) / "Pictures"
        viejas = (servidor.FOTOS_RAICES, servidor.CACHE_FOTOS)
        servidor.FOTOS_RAICES, servidor.CACHE_FOTOS = [self.raiz], Path(self.t.name) / "cache"
        self.addCleanup(lambda: setattr(servidor, "FOTOS_RAICES", viejas[0]) or setattr(servidor, "CACHE_FOTOS", viejas[1]))

    def test_solo_fotos_de_sus_carpetas_y_sin_capturas(self):
        buena = foto(self.raiz / "playa.jpg")
        foto(self.raiz / "Snapshot_2026-10-01.png")
        (self.raiz / "notas.txt").write_text("x")
        afuera = foto(Path(self.t.name) / "otra" / "afuera.jpg")
        (self.raiz / "enlace.jpg").symlink_to(afuera)              # un enlace que se sale tampoco
        self.assertEqual(servidor.listar_fotos(), [str(buena)])
        for mala in (afuera, self.raiz / "enlace.jpg", self.raiz / "notas.txt", "/etc/passwd", str(self.raiz / ".." / "otra" / "afuera.jpg")):
            self.assertIsNone(servidor.foto_permitida(mala), mala)

    def test_la_foto_se_achica(self):
        real = servidor.foto_permitida(foto(self.raiz / "grande.png", 3000, 2000))
        archivo, tipo = servidor.foto_achicada(real, "mini")
        self.assertEqual(tipo, "image/jpeg")
        medida = subprocess.run(["identify", "-format", "%wx%h", archivo], capture_output=True, text=True, check=True).stdout
        self.assertEqual(medida, "300x200")
        self.assertEqual(servidor.foto_achicada(real, "mini")[0], archivo)   # la segunda vez sale de la copia guardada

    def test_preferencias(self):
        base = dict(servidor.PREFERENCIAS)
        self.assertEqual(servidor.validar_preferencias({"fondo": "blueprint", "buscador": "google"}, base)["fondo"], "blueprint")
        favoritos = ["r-0123456789", "x-1234abcd"]
        self.assertEqual(servidor.validar_preferencias({"favoritos": favoritos}, base)["favoritos"], favoritos)
        buena = str(foto(self.raiz / "playa.jpg"))
        self.assertEqual(servidor.validar_preferencias({"fondo": "foto", "foto": buena}, base)["foto"], buena)
        for mala, texto in (({"fondo": "url(javascript:1)"}, "background"), ({"buscador": "bing"}, "search engine"),
                            ({"fondo": "foto", "foto": "/etc/passwd"}, "photo"), ({"fondo": "foto"}, "photo"),
                            ({"favoritos": ["../servidor.py"]}, "favorites"), ({"favoritos": ["x-1234abcd"] * 2}, "favorites")):
            with self.assertRaises(ValueError) as e:
                servidor.validar_preferencias(mala, base)
            self.assertIn(texto, str(e.exception))


class TestServidor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = servidor.ThreadingHTTPServer(("127.0.0.1", PUERTO_PRUEBA), servidor.Manejador)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def pedir(self, metodo, ruta, cuerpo=None, host=None, origen="default", tipo="application/json"):
        c = http.client.HTTPConnection("127.0.0.1", PUERTO_PRUEBA, timeout=30)
        cab = {"Host": host or f"127.0.0.1:{PUERTO_PRUEBA}"}
        if metodo == "POST":
            cab["Content-Type"] = tipo
            if origen == "default":
                cab["Origin"] = f"http://127.0.0.1:{PUERTO_PRUEBA}"
            elif origen:
                cab["Origin"] = origen
        c.request(metodo, ruta, json.dumps(cuerpo or {}) if metodo == "POST" else None, cab)
        r = c.getresponse()
        datos = r.read()
        return r.status, (json.loads(datos) if r.getheader("Content-Type", "").startswith("application/json") else datos)

    def test_la_pantalla_y_la_lista(self):
        st, pagina = self.pedir("GET", "/")
        self.assertEqual(st, 200)
        self.assertIn(b"<h1>Catacumba</h1>", pagina)
        st, d = self.pedir("GET", "/api/todo")
        self.assertEqual(st, 200)
        self.assertIn("repos", d)
        self.assertIn("extras", d)

    def test_nadie_de_afuera(self):
        self.assertEqual(self.pedir("GET", "/api/todo", host="malo.example")[0], 403)
        self.assertEqual(self.pedir("POST", "/api/agregar", {"nombre": "x"}, origen=None)[0], 403)
        self.assertEqual(self.pedir("POST", "/api/agregar", {"nombre": "x"}, origen="https://malo.example")[0], 403)
        self.assertEqual(self.pedir("POST", "/api/agregar", {"nombre": "x"}, tipo="text/plain")[0], 415)
        self.assertEqual(self.pedir("GET", "/estatico/../servidor.py")[0], 404)

    def test_agregar_y_quitar_sin_tocar_nada(self):
        carpeta = tempfile.mkdtemp(dir=servidor.HOME)
        self.addCleanup(os.rmdir, carpeta)
        st, r = self.pedir("POST", "/api/agregar", {"nombre": "Prueba", "tipo": "carpeta", "donde": carpeta})
        self.assertEqual(st, 200)
        ident = r["item"]["id"]
        self.assertIn(ident, [e["id"] for e in self.pedir("GET", "/api/todo")[1]["extras"]])
        self.assertEqual(self.pedir("POST", "/api/quitar", {"id": ident})[0], 200)
        self.assertNotIn(ident, [e["id"] for e in self.pedir("GET", "/api/todo")[1]["extras"]])
        self.assertTrue(os.path.isdir(carpeta), "quitar de la lista no borra la carpeta")
        self.assertEqual(self.pedir("POST", "/api/quitar", {"id": ident})[0], 400)

    def test_fondo_y_fotos(self):
        st, r = self.pedir("POST", "/api/preferencias", {"fondo": "compass"})
        self.assertEqual((st, r["preferencias"]["fondo"]), (200, "compass"))
        self.assertEqual(self.pedir("GET", "/api/todo")[1]["preferencias"]["fondo"], "compass")
        self.assertEqual(self.pedir("POST", "/api/preferencias", {"fondo": "nada"})[0], 400)
        self.assertEqual(self.pedir("POST", "/api/preferencias", {"fondo": "liso"}, origen="https://malo.example")[0], 403)
        self.assertEqual(self.pedir("GET", "/api/foto?tam=fondo&ruta=/etc/passwd")[0], 404)
        self.assertEqual(self.pedir("GET", "/api/foto?tam=enorme&ruta=/usr/share/backgrounds/x.jpg")[0], 404)
        self.assertIn("fotos", self.pedir("GET", "/api/fotos")[1])

    def test_favoritos_persisten_en_preferencias(self):
        favoritos = ["r-0123456789", "x-1234abcd"]
        st, respuesta = self.pedir("POST", "/api/preferencias", {"favoritos": favoritos})
        self.assertEqual((st, respuesta["preferencias"]["favoritos"]), (200, favoritos))
        self.assertEqual(self.pedir("GET", "/api/todo")[1]["preferencias"]["favoritos"], favoritos)
        self.assertEqual(self.pedir("POST", "/api/preferencias", {"favoritos": ["mal"]})[0], 400)

    def test_una_accion_sobre_algo_que_no_esta(self):
        st, r = self.pedir("POST", "/api/abrir", {"id": "no-esta"})
        self.assertEqual((st, r["error"]), (400, "It is not in the list"))


if __name__ == "__main__":
    unittest.main()
