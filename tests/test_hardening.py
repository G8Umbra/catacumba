# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
"""Regression tests for the security fixes S1-S7 and the check of the original ASCII font.
Each security test fails on the code before the fix and passes now. Everything runs in temporary folders."""
import http.client
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

ROOT = support.ROOT

with socket.socket() as _s:
    _s.bind(("127.0.0.1", 0))
    PORT = _s.getsockname()[1]
TMP = tempfile.TemporaryDirectory()
os.environ["CATACUMBA_PORT"] = str(PORT)
os.environ["CATACUMBA_CONFIG"] = str(Path(TMP.name) / "cfg" / "catacumba.json")
servidor = support.load_servidor(Path(TMP.name) / "tree", "servidor_hardening")
GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="T",
               GIT_COMMITTER_EMAIL="t@e", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)


def make_repo(path):
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True, env=GIT_ENV)
    (path / "a.txt").write_text("x")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, env=GIT_ENV)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "first"], check=True, env=GIT_ENV)
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name)


class TestS1GitRunsNoProgramsFromARepository(Base):
    def test_a_program_named_in_a_scanned_repository_is_never_executed(self):
        repo = make_repo(self.root / "evil")
        marker = self.root / "executed.marker"
        hook = self.root / "hook.sh"
        hook.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
        hook.chmod(0o755)
        subprocess.run(["git", "-C", str(repo), "config", "core.fsmonitor", str(hook)], check=True, env=GIT_ENV)
        # sanity: plain git does run it, so the test can detect the problem
        subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, env=GIT_ENV)
        self.assertTrue(marker.exists(), "control: plain git should execute the configured program")
        marker.unlink()
        servidor.git(str(repo), "status", "--porcelain")
        servidor.info_repo(str(repo))
        servidor.detalle_repo(str(repo))
        self.assertFalse(marker.exists(), "Catacumba's git wrapper executed a program named by the repository")


class TestS2PrivateUserData(Base):
    def test_the_data_folder_is_0700_and_the_files_are_0600_even_with_a_permissive_umask(self):
        cfg = self.root / "data" / "catacumba.json"
        old = os.umask(0o022)
        self.addCleanup(os.umask, old)
        with mock.patch.object(servidor, "CONFIG", cfg):
            servidor.guardar_config({"extras": []})
            servidor.write_continue({"version": 1, "projects": {}})
        self.assertEqual(stat.S_IMODE(cfg.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(cfg.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((cfg.parent / "continue.json").stat().st_mode), 0o600)


    def test_a_folder_the_user_chose_keeps_its_mode_but_the_default_folder_is_tightened(self):
        mine = self.root / "my-notes"
        mine.mkdir(mode=0o755)
        mine.chmod(0o755)
        servidor.carpeta_privada(mine)
        self.assertEqual(stat.S_IMODE(mine.stat().st_mode), 0o755)
        default = self.root / "catacumba"
        default.mkdir()
        default.chmod(0o755)
        servidor.carpeta_privada(default)
        self.assertEqual(stat.S_IMODE(default.stat().st_mode), 0o700)


class TestS3NegativeContentLength(Base):
    def test_a_negative_content_length_cannot_bypass_the_body_limit(self):
        for patcher in (mock.patch.object(servidor, "CONFIG", self.root / "cfg3" / "catacumba.json"), mock.patch.object(servidor, "HOME", self.root)):
            patcher.start()
            self.addCleanup(patcher.stop)
        srv = servidor.ThreadingHTTPServer(("127.0.0.1", PORT), servidor.Manejador)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        carpeta = self.root / "proj"
        carpeta.mkdir()
        body = json.dumps({"nombre": "x", "tipo": "carpeta", "donde": str(carpeta), "pad": "a" * 20000}).encode()
        req = (f"POST /api/agregar HTTP/1.1\r\nHost: 127.0.0.1:{PORT}\r\nOrigin: http://127.0.0.1:{PORT}\r\n"
               f"Content-Type: application/json\r\nContent-Length: -1\r\nConnection: close\r\n\r\n").encode() + body
        with socket.create_connection(("127.0.0.1", PORT), timeout=10) as c:
            c.sendall(req)
            c.shutdown(socket.SHUT_WR)
            resp = b""
            while True:
                chunk = c.recv(65536)
                if not chunk:
                    break
                resp += chunk
        status = int(resp.split(b" ", 2)[1])
        self.assertEqual(status, 400, resp[:200])           # no body was read: "The name is missing"
        self.assertEqual(servidor.leer_config()["extras"], [])


class TestS4ConverterGetsAnExplicitFormat(Base):
    def test_the_image_converter_input_is_prefixed_with_the_checked_format(self):
        fotos = self.root / "Pictures"
        fotos.mkdir()
        for nombre, coder in (("a.png", "png"), ("b.jpg", "jpeg"), ("c.webp", "webp")):
            (fotos / nombre).write_bytes(b"not really an image")
            with mock.patch.object(servidor, "FOTOS_RAICES", [fotos]), mock.patch.object(servidor, "CACHE_FOTOS", self.root / "cache"), \
                    mock.patch.object(servidor.subprocess, "run") as run:
                real = servidor.foto_permitida(fotos / nombre)
                servidor.foto_achicada(real, "mini")
            args = run.call_args[0][0]
            self.assertEqual(args[0], "convert")
            self.assertIn(f"{coder}:{real}[0]", args, nombre)


class TestS5Csp(Base):
    def test_the_csp_forbids_base_and_form_targets(self):
        srv = servidor.ThreadingHTTPServer(("127.0.0.1", PORT), servidor.Manejador)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
        c.request("GET", "/", headers={"Host": f"127.0.0.1:{PORT}"})
        csp = c.getresponse().getheader("Content-Security-Policy")
        for parte in ("default-src 'self'", "frame-ancestors 'none'", "base-uri 'none'", "form-action 'none'"):
            self.assertIn(parte, csp)


class TestS6RelativePathsCannotBecomeOptions(Base):
    def test_a_path_starting_with_a_dash_reaches_code_and_xdg_open_as_an_absolute_path(self):
        (self.root / "-n").mkdir()
        item = {"id": "x-0000abcd", "nombre": "t", "tipo": "carpeta", "donde": "-n"}
        cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, cwd)
        ok = subprocess.CompletedProcess([], 0)
        with mock.patch.object(servidor.subprocess, "run", return_value=ok), mock.patch.object(servidor.subprocess, "Popen") as popen:
            servidor.abrir_en_code(item)
            servidor.abrir(item)
        for llamada in popen.call_args_list:
            argumento = llamada[0][0][-1]
            self.assertTrue(argumento.startswith("/"), f"relative path reached a command line: {llamada[0][0]}")


class TestS7SymlinkedHome(Base):
    def test_a_home_folder_reached_through_a_symlink_still_accepts_its_own_projects(self):
        real = self.root / "real-home"
        (real / "proj").mkdir(parents=True)
        link = self.root / "home-link"
        link.symlink_to(real)
        with mock.patch.object(servidor, "HOME", link):
            self.assertEqual(servidor.carpeta_permitida(str(link / "proj")), str(real / "proj"))
            with self.assertRaises(ValueError):
                servidor.carpeta_permitida("/etc")


class TestAsciiFont(unittest.TestCase):
    """The banner font is original (see the comment in ascii.js); every glyph must be a clean 5 x 5 block."""

    @classmethod
    def setUpClass(cls):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node is not installed")
        r = subprocess.run([node, "-e", "console.log(JSON.stringify(require(process.argv[1]).fuente))", str(ROOT / "estatico" / "ascii.js")],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise AssertionError(r.stderr)
        cls.font = json.loads(r.stdout)

    def test_every_supported_character_exists_with_consistent_height_and_width(self):
        soportados = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -_/?!.:")
        for c in soportados:
            self.assertIn(c, self.font, c)
        for c, glifo in self.font.items():
            self.assertEqual(len(glifo), 5, f"height of {c!r}")
            self.assertEqual({len(fila) for fila in glifo}, {5}, f"width of {c!r}")
            self.assertTrue(set("".join(glifo)) <= {"#", " "}, c)
            if c != " ":
                self.assertIn("#", "".join(glifo), f"{c!r} is blank")

    def test_letters_and_digits_are_all_distinct(self):
        vistos = {}
        for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
            clave = tuple(self.font[c])
            self.assertNotIn(clave, vistos, f"{c} looks the same as {vistos.get(clave)}")
            vistos[clave] = c

    def test_the_file_states_that_the_font_was_authored_for_this_project(self):
        txt = (ROOT / "estatico" / "ascii.js").read_text(encoding="utf-8")
        self.assertIn("authored from scratch for this project", txt)


if __name__ == "__main__":
    unittest.main()
