"""Where things are: the Steam install (shutdown build, provides roi.exe + loose files), the full asset depot
(depot 258162, manifest 1099989411347492672), and the playable game folder that setup assembles.

Read from config.json next to this file (written by setup.ps1 from local settings).
"""
from network_defaults import LOCAL_LOBBY, LOOPBACK
from network_defaults import listen_address
import json
import os
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
_cfg = {}
try:
    _cfg = json.loads((HERE / "config.json").read_text(encoding="utf-8-sig"))
except (OSError, ValueError):
    pass

STEAM = pathlib.Path(_cfg.get("steam", str(HERE/'unconfigured-steam')))
DEPOT = pathlib.Path(_cfg.get("depot", str(HERE/'unconfigured-depot')))
GAME = pathlib.Path(_cfg.get("game", str(HERE.parent/'game')))
LIBS = pathlib.Path(_cfg.get("libs", str(HERE/'libs')))

# Online lobbies (online.ps1 changes these):
#   lobby_mode "steam": every PC runs its own lobby server; rooms are published and found as Steam lobbies.
#   lobby_mode "server": one shared lobby server; lobby_server is where every game connects (host's address),
#   lobby_listen the address this PC's lobby server accepts connections on (all interfaces when hosting).
#   Environment variables ROI_LOBBY_MODE / ROI_LOBBY_LISTEN override config.json (used by the container image).
LOBBY_MODE = os.environ.get("ROI_LOBBY_MODE") or _cfg.get("lobby_mode", "steam")
LOBBY_SERVER = _cfg.get("lobby_server", LOCAL_LOBBY) if LOBBY_MODE == "server" else LOCAL_LOBBY
LOBBY_LISTEN = (os.environ.get("ROI_LOBBY_LISTEN") or _cfg.get("lobby_listen", LOOPBACK)) if LOBBY_MODE == "server" \
    else LOOPBACK
LOBBY_LISTEN = listen_address(LOBBY_LISTEN)

STEAM_EXE = STEAM / "exe" / "roi.exe"
STEAM_RES = STEAM / "resource" / "masterWindows"
GAME_EXE = GAME / "exe" / "roi.exe"
GAME_RES = GAME / "resource" / "masterWindows"
