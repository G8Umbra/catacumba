# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
"""Helpers for the Community tests: they always run against a COPY of the server with no plugin folder,
so a developer's own plugin (or its absence) can never change what these tests prove."""
import importlib.util
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def community_copy(dest):
    """Copy only the Community files (server + static) into dest. Returns dest."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "servidor.py", dest / "servidor.py")
    shutil.copytree(ROOT / "estatico", dest / "estatico", dirs_exist_ok=True)
    assert not (dest / "personal").exists()
    return dest


def load_servidor(dest, name="servidor_copy"):
    """Import servidor.py from a Community copy. Environment variables (port, config) must be set before this call."""
    dest = community_copy(dest)
    spec = importlib.util.spec_from_file_location(name, dest / "servidor.py")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[name] = modulo
    spec.loader.exec_module(modulo)
    assert modulo.PLUGIN is None
    return modulo
