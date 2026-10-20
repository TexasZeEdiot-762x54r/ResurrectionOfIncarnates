# Rise of Incarnates — offline revival

> Public TLS lobby deployment: read `PUBLIC-LOBBY.txt` first.
> Public anonymized snapshot of `20261020-library-text-v25`. Configure the ignored
> `deployment.local.json` using the repository-root example and README first.
> Read `CLIENT-REFRESH.txt`
> for a clean rebuild that rules out mixed older executable/script patches.
> `Online - Steam.bat` now selects the shared public service and launches the game.
> `Online - Steam (LAN).bat` reaches the same service through its LAN address.
> `Online - Steam Discovery.bat` preserves the separate direct Steam directory.
> Local Library recovery and its remaining gaps are documented in `LIBRARY.txt`.

## Current release status (2026-10-19)

Two players have completed native multiplayer matches. Lobby creation, endpoint
registration and shared-server search presence have been corrected. This is still
experimental: multiplayer results have appeared with the mail-response correction,
but a roughly 48-second wait remained. The result-ready handler has now produced
timely results in a user-confirmed multiplayer match. Intermittent audio initialization
faults remain under investigation. Solo bot result screens have been user-confirmed.
Original XP/reward rates remain unknown, so XP awards stay disabled.

For all compatibility fixes, use Setup.bat in a NEW patch folder with your own
supported Steam executable and full historical depot. Apply Update.bat migrates
metadata/profile data but deliberately does NOT rebuild the executable or apply
the updated shell-table overlay. It alone is not a full upgrade from the incoming
October 18 package. Keep your old installation and profile backed up.

The public directory uses pinned TLS on TCP 52714, without an invitation or
Steam-ID allowlist. It does not authenticate claimed player identities. The
older private WireGuard option remains separate; read HARDENING.txt for it.
No invitations, private keys, profiles, executables or resource archives are distributed.

Play **Rise of Incarnates** (Bandai Namco, 2014; online service closed in December 2015) again on your own PC:
VS Bot matches with voices and every character, Customize with all items unlocked, saved outfits and character
choice. The official servers are replaced by two small local "stand-in" servers that run on your PC while you play.

Setup builds the executable and archive assets from your own Steam copy of the game.
The package also contains page-only Library captures recovered from reference footage;
see `LIBRARY.txt` for recovered content and remaining gaps. Credits is unchanged.

## What you need

- Windows, Steam, and **Rise of Incarnates in your Steam library** (installed).
- About **11 GB** of free disk space.
- **Python 3.10 or newer** from <https://www.python.org/downloads/> (tick *Add python.exe to PATH* when installing).
- Internet once during setup (it installs two Python libraries, `pefile` and `capstone`).

## Setup (once)

1. **Download the full game assets.** The Steam install of the shut-down game only has stub archives, so fetch the
   last full version of the asset depot (about 9 GB):
   - press **Win+R**, enter `steam://open/console`
   - type `download_depot 258160 258162 1099989411347492672` and press Enter
   - wait until Steam reports that the depot download is complete
     (it lands in `<Steam>\steamapps\content\app_258160\depot_258162`).
2. **Run `Setup.bat`.** It finds your Steam install and the depot (or asks for the folder), copies them into a
   `game` folder next to this file, unpacks the script files the patched game needs from your archives, applies a
   data fix from your Steam install, and builds the patched `roi.exe`.

## Play

1. Start Steam and log in.
2. Run **`Play Rise of Incarnates.bat`**. The logo appears after about 40 seconds.
3. Go to **Play → VS. Bot**. Pick your Incarnate with **Character Select**, change outfits in **Customize**.

## Online with other players (experimental)

Use the shared **public TLS directory** described in `PUBLIC-LOBBY.txt`.
Steam still carries the native battle traffic. Only the operator forwards a port.

1. Everyone does the Setup above with this same package version, starts Steam, and runs
   `Online - Steam.bat` (the operator's LAN uses `Online - Steam (LAN).bat`).
2. One player: **Play → Custom Match → Create Lobby**. The room is listed on the shared service.
3. Others: **Play → Custom Match → Search Lobby → Advanced Search → Search**, then the join button on the room.
   (The "Friend Lobby" tab only lists rooms of your Steam friends.)
4. A battle starts once at least two people in the lobby press **BATTLE**. Alone, BATTLE just waits on a black screen.

Rooms you create are visible to other users of this service while open. Room/member IDs and
shared profile metadata are not private. `Online - Off.bat` selects local-only discovery.

Direct Steam discovery remains available through `Online - Steam Discovery.bat`, then Play.
It is a different room directory; both players must choose the same mode. Private WireGuard
access remains available with `Import Lobby Access.bat` and `Online - Join.bat`.
Windows external hosting is disabled. Do not forward the unencrypted native lobby ports.

What runs on each player's PC: the patched game, `tools\server.py` (your profile and game data, only on
loopback:52710), Steam, and either the loopback TLS tunnel (public mode) or
`tools\nrt_server.py` (local/direct Steam mode).

If something goes wrong, send the host's and your `tools\logs\nrt.log` and `tools\logs\play.log` (they contain
Steam IDs of the people you played with; share them privately, not in public channels).

## Good to know

- Two-PC native matches have been completed; multiplayer results and intermittent
  audio faults remain under investigation. This is not a fully restored service.
- Some outfit/store metadata remains placeholder data. The skill patch includes 340
  recovered original cube variants; see SKILL-GRIDS.txt for recovery limits and
  the recovered expansion-right mechanism, missing original level-reward table,
  and explicitly non-original LP test price. No guessed level rewards are enabled.
- HP / cost / experience values are placeholders; the original balance data was never kept.
- Your character choice, outfits and seen tutorials are stored in `tools\player_profile.json`.
- Bot XP/reward handling is reconstructed but disabled pending authentic rates
  and curves. See AWARD-PIPELINE.txt; no synthetic balance data is shipped.
- If something crashes, `tools\logs\play.log` has the details.

## How it works (short)

- `tools\build.py` patches your own `roi.exe` (the shutdown build) so it starts normally instead of showing the
  "service ended" screen, talks to the local servers, and fixes several bugs of the shut-down build (missing data
  loaders, double resource loading that caused white textures, sound packs that never unloaded, memory limits).
- `tools\server.py` (profile, master data, VS Bot results, customize; always on `loopback`) and
  `tools\nrt_server.py` (lobby list: create, search, join) answer the game's online requests. With Steam lobbies
  on, `tools\steam_dir.py` publishes and finds rooms through your Steam client, using the game's own
  `steam_api64.dll` and your own login.

Made with AI assistance (OpenAI Codex, then Anthropic Claude) by reverse engineering the game on an owned copy.
Do not share game files or patched executables; share this package and let everyone build from their own copy.
