# Catacumba

**All your projects on one screen, and a way back to where you left off.**

Catacumba is a small local app that lists your code repositories, project folders, document folders and web pages
in one place, lets you search and sort them, and remembers where you stopped in each one, so you can pick up the
next day without hunting for files. It runs on your own computer and nothing leaves it.

*Better Diagnostics, Better Decisions, Better Lives.*

Catacumba Community is made by G8Umbra, associated with TempLogic Systems (https://templogicsystems.com/).

## What you get

- **Free, no account, no subscription.** Nothing to sign up for. There is no upgrade screen.
- **Private by design.** It listens only on `127.0.0.1` (this computer). It makes no network request of its own and
  sends no telemetry. The only traffic is what you ask for: a "does this page answer?" check on a web page you added,
  or the web-search box, which opens your browser.
- **Read-only on your projects.** It looks and opens. It never changes, moves or deletes your files. "Remove from list"
  only removes the card.
- **Guided first run.** With nothing configured you get a friendly start: pick a folder that looks like it holds
  projects (or type one), and Catacumba finds the git projects in it, or adds it as a single project folder.
- **Find things fast.** Search (press `/`), tabs by kind, sort (latest change, recently opened, name, most unsaved
  changes), an "only with unsaved changes" filter, favourites.
- **Continue where you left off.** When you open an item, Catacumba remembers, locally, when you opened it, the files
  changed most recently in it (names and times only, never contents) and a note you can write to your future self.
  The home view shows the last items you worked on. You can view, export, pause and clear all of it in **About**.
- **Comfortable to use.** Works from phone width up, light and dark theme (follows your system, or pick one),
  full keyboard use, visible focus, skip link, reduced-motion respected.
- **A small extra tool:** an ASCII banner maker for text headers.
- **Optional, easy to ignore:** an About page with an optional section of plain links about its maker. It can be hidden with one checkbox.

## Run it

Needs Python 3.10 or newer (standard library only) and git. No packages to install.

    python3 servidor.py                # then open http://127.0.0.1:8310/
    sh abrir_catacumba.sh              # starts it in the background and opens a window

Environment variables (all optional):

| Variable | Meaning | Default |
|---|---|---|
| `CATACUMBA_PORT` | port on 127.0.0.1 | `8310` |
| `CATACUMBA_CONFIG` | your list and settings file | `~/.config/catacumba/catacumba.json` |
| `CATACUMBA_DATA_DIR` | folder for the "where you left off" file | the folder of the config file |

## Your data

Catacumba stores a few small, readable files on your own computer, and nothing else. It sends nothing anywhere:
no telemetry, no analytics, no update check, no account, no cloud. The only network traffic is something you ask for
yourself: the "Does it answer?" button on a web page you added, and the web-search box (which opens your browser).

| What | Where | Contains |
|---|---|---|
| Your list and settings | `catacumba.json` in your config folder (default `~/.config/catacumba/`, or the path in `CATACUMBA_CONFIG`) | the folders and pages you added, the folders searched for git projects, favourites, background and search-engine choice, and the two switches "remember where I left off" and "show the About links" |
| Where you left off | `continue.json` in the same folder (or in `CATACUMBA_DATA_DIR`) | per item: its name and place, when you last opened it, how many times, the note you wrote, and the names and times (never the contents) of the files changed most recently in it |
| Your notes | inside `continue.json` | the text you type in "Note to my future self" (500 characters at most per item) |
| Browser conveniences | your browser's local storage | theme and sort order |

- **See it:** **About** shows the exact paths and how much is saved. The files are plain JSON; open them in any editor.
- **Export it:** **About**, "Export as a file" (also `GET /api/continue/export`) downloads your history as one JSON file.
- **Pause it:** **About**, untick "Remember where I left off". Nothing new is recorded while it is off.
- **Delete it:** per item with "Forget this item's history" in its panel; everything with **About**, "Clear all of it" (two clicks); or delete the files yourself.
- **If the settings folder is read-only,** Catacumba still starts, shows a clear message, and does not lose or invent anything; point `CATACUMBA_CONFIG` to a folder you can write to.

## Safety

- The server answers only requests addressed to `127.0.0.1` or `localhost` on its own port, and only accepts changes from its own page.
- Actions only work on items already in your list. No command text ever comes from the browser.
- Folders can be added only from your home folder or a connected disk; pages must be `http://` or `https://`.
- The page is served with a strict content security policy and loads no external scripts, fonts or images.

## Plugins (optional)

If a file `personal/plugin.py` sits next to `servidor.py`, it is loaded as a plugin (by path, never by a static import). Without it, Catacumba is complete
and starts with no extra menu entries. A plugin is a folder whose `plugin.py` defines `register(host)` (and may set `API_VERSION = 1`) and
returns a dict with a required `name` and any of these optional keys:

| Key | What it does |
|---|---|
| `config_path` | default config file location (used when `CATACUMBA_CONFIG` is not set) |
| `initial_config(home)` | the list to start a brand-new install with |
| `repo_extra(info)` | add `chips` (small labels) and `acciones` (buttons) to a repository card |
| `detail(path)` | return extra `{titulo, texto}` sections for a repository's detail panel |
| `routes_get`, `routes_post` | extra API routes: `path -> fn(query)` returning `(status, body)`, or `path -> fn(item, data)` returning a body |
| `ui` | `{styles, scripts, fragment}` served from `personal/static/` under `/plugin/`; fragment elements with `data-slot="header-actions"` or `data-slot="main-top"` are placed in the page |

A plugin that fails to load is reported in `About` and on stderr; the app keeps running without it.

## How it is built

Catacumba Community is developed with AI assistance (Claude Code, by Anthropic) under the direction of G8Umbra, who maintains it.

## License

Copyright (c) 2026 G8Umbra

Catacumba Community is licensed under the **Mozilla Public License 2.0 (MPL-2.0)**; every source file carries its
notice and an `SPDX-License-Identifier: MPL-2.0` line, and the full text is in the `LICENSE` file of a release.
In plain terms: you may use, change and share Catacumba freely, including in your own projects. If you change a file
that is covered by the MPL and distribute the result, you must share the source of your changes to that file under the
same license. This is a summary, not legal advice; the license text is what applies.

## Tests

    python3 -B -m unittest discover -s tests -v          # Community: runs against a copy of the server with no plugin

## Contributing

The code is plain Python and vanilla HTML/CSS/JS with no build step. Keep it dependency-free, keep every request
local, and add a test with each behaviour. Do not add anything that sends data away or needs an account.

By contributing you agree that your contribution is licensed under MPL-2.0. New source files need the header shown in
any existing file (a test checks this). All text a user can see must be in English, and the Community code must not
refer to private products, folders or machines (tests check both).
