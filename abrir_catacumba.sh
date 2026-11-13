#!/bin/sh
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Opens Catacumba. If its server is not running it is started first (takes about a second).
# The server keeps running in the background until you stop it (for example: pkill -f servidor.py).
#   CATACUMBA_SERVER_ONLY=1 sh abrir_catacumba.sh    start the server without opening a window
#   CATACUMBA_PORT=8310                              change the port (this machine only, 127.0.0.1)
set -u
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PORT=${CATACUMBA_PORT:-8310}
URL="http://127.0.0.1:$PORT/"
LOGDIR="${XDG_STATE_HOME:-$HOME/.local/state}/catacumba"

answers() { curl -s -m 2 -o /dev/null "${URL}api/salud"; }

if ! answers; then
    mkdir -p "$LOGDIR"
    CATACUMBA_PORT=$PORT setsid python3 -B "$HERE/servidor.py" >> "$LOGDIR/server.log" 2>&1 < /dev/null &
    i=0
    while [ $i -lt 40 ] && ! answers; do sleep 0.25; i=$((i + 1)); done
    answers || { echo "Catacumba did not start; see $LOGDIR/server.log" >&2; exit 1; }
fi

[ "${CATACUMBA_SERVER_ONLY:-0}" = 1 ] && exit 0
# as an app window when Chrome or Chromium exist, otherwise in the default browser
if command -v google-chrome >/dev/null 2>&1; then
    exec google-chrome --app="$URL" --class=Catacumba >/dev/null 2>&1
fi
if command -v chromium >/dev/null 2>&1; then
    exec chromium --app="$URL" >/dev/null 2>&1
fi
exec xdg-open "$URL"
