# Rise of Incarnates Revival Sources

An anonymized source snapshot including the Library text update and subsequent
source-safety and regression-test corrections. No configured
server address, personal account, certificate pin, game executable, Steam DLL,
runtime profile, credential, log or Git history is included.

See [STATUS.md](STATUS.md) for the current implementation boundaries and verified
source changes. Source tests do not establish native-game acceptance or deployment.

## Local Settings

Copy `deployment.example.json` to `deployment.local.json` at the repository root.
Only the example belongs in Git. The local file and generated settings are ignored.
An explicit `ROI_DEPLOYMENT_FILE` environment variable can point to a private copy
elsewhere. A component-local copy in `client/` or `server/` is also supported;
it takes precedence over the repository-root file. Use the same structure.

Fill only the settings needed for your chosen mode. Keep the `client` and `server`
objects in the file even if you use only one side. Unused string fields can stay
`""`; leave unused numeric port fields at their defaults rather than making them
blank. JSON does not support comments or trailing commas.

### Configuration Lookup

The first applicable file is used; settings from different files are **not merged**:

1. `server/configure.py --config PATH` selects that file for that command only.
2. Otherwise, `ROI_DEPLOYMENT_FILE` selects an explicit private file.
3. Otherwise, the component's `client/deployment.local.json` or
   `server/deployment.local.json` is used, if present.
4. Otherwise, the repository-root `deployment.local.json` is used.

An explicitly selected missing file is an error, not a fallback to another file.
If you use `--config` when generating server settings, also arrange for provisioning
and the firewall guard to find that same configuration through their normal lookup
or `ROI_DEPLOYMENT_FILE`. The command does not permanently select it for other tools.

### File Version

| Option | Type / Default | Meaning |
| --- | --- | --- |
| `version` | Integer `2` in the example; version `1` remains supported | Configuration format version. It is not the game, patch or API version. Version 2 adds the required progression selector below. |

### Progression Policy

Version 2 requires `policy.progression_mode`; an empty or unknown value fails
validation. The available values record the intended policy, but the local
profile and battle-award handlers do not yet consume this selector. Selecting a
mode does **not** currently grant levels, cubes, grid cells, XP, LP, or change
battle drops. Do not treat a valid config as proof that the gameplay policy is
implemented or deploy this setting as an active progression choice.

| `policy.progression_mode` | Meaning |
| --- | --- |
| `faithful` | Intended evidence-backed behavior without operator grants. Original starter entitlements and award curves remain unresolved. |
| `fully_unlocked` | Proposed revival target: account starts at level 15, characters at level 1, skill-cube pieces fully upgraded and all 16 cells of the native 4x4 grid unlocked. Player and character XP would continue, item drops would be disabled and LP would remain awarded. This intentionally remains selector-only: even the startup subset is not enabled. Cube caps, level curves and settlement integration remain unresolved. |
| `match_xp` | Proposed revival target: 8 XP for a loss, 10 XP for a win, or 16 XP for a win with highest damage, applied to both player/account and character XP. Level curves and award integration remain separate and are not active. |

Version 1 deployment files remain accepted without policy fields and retain
their prior behavior. They are not migrated or rewritten by loading a version
2 configuration.

The selected revival LP targets and their remaining input/authority gaps are
listed in [STATUS.md](STATUS.md). They are not verified original rules or enabled
runtime rewards. Do not use the selector as a substitute for implementation.

### Client Settings

These settings apply to each player's own machine. Server operators also use
`client.vpn_lobby_host` and `client.vpn_lobby_port` when provisioning VPN access files.

| Option | Type / Default | Meaning and When Needed |
| --- | --- | --- |
| `client.steam_path` | String, `""` | Optional path to the normal, unmodified Steam game installation, normally ending in `steamapps/common/Rise_of_Incarnates`. This provides the executable and loose files, **not** the historical depot. Blank makes Setup search Steam libraries and then prompt if necessary. The path resolver also accepts its `exe` folder or the full `roi.exe` path. |
| `client.depot_path` | String, `""` | Optional path to the downloaded historical assets, ending in `steamapps/content/app_258160/depot_258162`. This folder must contain `resource/masterWindows/GxArchivedFile001.dat`. Blank makes Setup try the depot under the detected Steam folder; if assets are missing it prints download instructions and stops. |
| `client.game_path` | String, `""` | Output folder where Setup assembles the playable, patched game. Blank uses `client/game` beside `Setup.bat`. Use a separate output folder, not your original Steam installation or depot. |
| `client.internet_host` | String, `""` | Public gateway hostname or IPv4 address used by `Online - Steam.bat`. Required for that launcher. Enter only the host, for example `gateway.example.invalid` as a placeholder to replace, without a URL scheme, path or port. |
| `client.lan_host` | String, `""` | LAN-reachable hostname or IPv4 address of the same gateway, used by `Online - Steam (LAN).bat`. Required only for that launcher; it avoids depending on router NAT loopback. It is not automatically copied from `internet_host` or the server bind setting. |
| `client.port` | Integer `52714` | TCP port the client connects to on either gateway route. Use the externally forwarded port for Internet players and the published host port for LAN players. Both launchers share this setting; if those ports differ, use separate private configuration files for the two routes. |
| `client.certificate_sha256` | String, `""` | Required for either public TLS launcher. The exact SHA-256 fingerprint of the gateway's certificate: 64 hexadecimal characters, with no colons or prefix. Obtain it from the server operator over a trusted channel. Blank or invalid pins fail closed; never disable pin verification. |
| `client.vpn_lobby_host` | String, `""` | Private VPN lobby hostname or IPv4 address used by `Online - Join.bat`, access-file import and server-side invitation provisioning. Required for those VPN operations, not for public TLS or Steam Discovery. Imported access files must match this configured endpoint. |
| `client.vpn_lobby_port` | Integer `52711` | Destination lobby TCP port for private VPN joining and provisioned access files. Normally keep `52711`: the VPN Compose service publishes lobby port `52711` and profile-relay port `52713`. Changing this setting alone does not reconfigure the server or relay. |

For path strings, prefer absolute paths. JSON accepts forward slashes; if using
Windows backslashes, double each one. Setup's `-Steam`, `-Depot` and `-Game`
command-line arguments override the corresponding deployment-file paths. Setup
writes the resolved paths to ignored `client/tools/config.json`; later launches
use that runtime configuration. Editing a deployment path does not migrate an
already assembled game folder: rerun Setup with the intended paths when needed.

To calculate the certificate fingerprint from the server's public certificate:

```sh
openssl x509 -in private/public-cert.pem -outform DER | sha256sum
```

Copy only the 64-character hash into `client.certificate_sha256`. Share neither
the private key nor a whole private deployment file containing machine-local values.

### Server Settings

These settings are used by the container configuration generator or the optional
VPN firewall guard. Ordinary players do not need to fill them in.

| Option | Type / Default | Meaning and When Needed |
| --- | --- | --- |
| `server.public_bind_host` | String, `""` | Required by `configure.py --mode public`. The IPv4 address of a local server interface on which Docker publishes the TLS gateway. It must belong to the server; it is usually not the router's external address. DNS names are not accepted here. `any` explicitly chooses every IPv4 interface; blank is an error, not an implicit wildcard. |
| `server.public_port` | Integer `52714` | Host TCP port published by public Compose. It maps to the fixed gateway port `52714` inside the container. Configure router forwarding to this host port and set each client's `port` for its route. This does not publish the raw backend ports. |
| `server.vpn_bind_host` | String, `""` | Required for VPN configuration and the firewall guard. The server's local IPv4 VPN-interface address. It must be within `vpn_network`; unspecified and multicast addresses are rejected. Public TLS mode does not use this field. |
| `server.vpn_interface` | String, `""` | Required for VPN configuration and the guard. The actual host VPN-interface name, such as `wg0`, not a peer name or client tunnel label. Accepted names are 1-15 letters, digits, dots, underscores or hyphens and must begin with a letter or digit. |
| `server.vpn_network` | String, `""` | Required for VPN configuration and the guard. The IPv4 VPN subnet in CIDR form, using the network address and prefix length. The prefix must be at least `/8`, and the bind address must belong to it. The guard permits the lobby ports only from this subnet arriving on `vpn_interface`; it does not create VPN routes or reconfigure WireGuard. |
| `server.python_base` | String, `""` | Required for either container mode. A reviewed official Python image pinned by an immutable digest, in the exact form `python:TAG@sha256:DIGEST`. Replace `TAG` with an appropriate Python 3.10+ image tag and `DIGEST` with its real 64-character hexadecimal digest. An unpinned tag, blank value or registry-prefixed image name is rejected by the current validator. |

All configured ports must be JSON integers from `1024` through `65535`, not quoted
strings. Client gateway/VPN hosts support DNS names or IPv4 addresses, not IPv6
literals; server bind fields and the VPN subnet require IPv4. The public gateway
certificate/key file locations remain the fixed secret paths documented below;
there are no extra JSON settings for them.

After changing container settings, rerun `server/configure.py` for the intended
mode, review Compose's rendered configuration, and deliberately recreate the
container when ready. Editing JSON alone does not change a running container.
Stop the VPN firewall guard before changing its configuration so its old rules
can be removed with the old settings.

Blank public/VPN settings fail closed. Steam Discovery and local-only modes do
not require a deployment file. Internal native-game loopback addresses are
constructed in `network_defaults.py`, rather than storing literal IP strings.
These protocol-local bindings are not user-configurable or public listeners.

## Client Setup

1. Install Python 3.10+ and install Rise of Incarnates normally through Steam.
   Keep this unmodified Steam installation: Setup verifies its executable.
2. With Steam running, press **Win+R**, enter `steam://open/console`, and press
   **Enter** to open Steam's Console tab.
3. In the Steam console, enter this exact command and press **Enter**:

   ```text
   download_depot 258160 258162 1099989411347492672
   ```

4. Wait until Steam reports **Depot download complete**. The historical assets
   are roughly 9 GB; do not run Setup while the download is incomplete. Steam's
   completion message shows the actual destination, normally
   `<Steam folder>/steamapps/content/app_258160/depot_258162`.
5. Copy `deployment.example.json` to ignored `deployment.local.json`. Choose an
   explicit `policy.progression_mode`; it remains selector-only as described above.
   Fill in the networking fields for your chosen mode and, optionally, the local paths.
   If the depot is in another Steam library or on another drive, set
   `client.depot_path` to the exact folder reported by Steam. Do not use the depot
   as `client.steam_path`; the normal install and historical assets have different roles.
6. Run `client/Setup.bat`. It builds a separate playable game from your own files.
   Keep Steam running and logged in when launching the game.
7. For the configured public gateway, run `client/Online - Steam.bat`; on its LAN,
   use `client/Online - Steam (LAN).bat`. Each selects its route and starts the game.
8. Alternatively, `client/Online - Steam Discovery.bat` selects direct Steam lobby
   discovery without a gateway. That file only changes the mode; run
   `client/Play Rise of Incarnates.bat` afterward to launch the game.

The source checkout includes component manifests used by Setup's integrity check.
After intentionally editing public sources, run `python refresh_manifests.py`.
This refreshes hashes only; it does not start the game, modify profiles or deploy.

`Apply Update.bat` is not a substitute for a clean Setup when moving from an
older executable patch generation. Keep your own existing installation backed up.
The obsolete original browser helper is restored only from your own verified
Steam files; it is not redistributed here.

## Container Setup

For the public TLS gateway, from `server/`:

```sh
python configure.py --mode public
docker compose -f compose.public.yaml config
docker compose -f compose.public.yaml up -d --build
```

Place your own PEM certificate and private key in `server/private/public-cert.pem`
and `server/private/public-key.pem`. Give the unprivileged container account access
to those files, without making the key world-readable. The gateway remains pinned
by clients, and the raw backend ports are not published. Forward only the configured
external TCP port on your own router/firewall. The public mode deliberately permits
any player with a configured client, not an invitation or Steam-ID allowlist.

For a private VPN deployment:

```sh
python configure.py --mode vpn
python provision_players.py --invite
docker compose config
```

Install and review the optional `roi-lobby-guard.service` and `roi-lobby.service`
templates before starting the VPN Compose project. Their generic service account
and install paths must exist on your machine. The guard requires root and a
root-owned settings file at the path named in its unit. It validates settings
before running commands and refuses unknown existing guard-chain rules. Stop the
guard before changing VPN settings so its old rules can be removed correctly.
Never make the VPN interface globally trusted just for this game.

`configure.py` creates an ignored `server/.env` and backs up any prior copy.
It never starts services or changes firewall rules. Compose requires its bind
variables explicitly; running it without configured values fails.

## Publication Checks

```sh
python -m unittest discover -s tests
python audit_public.py
python client/tools/check_launch.py --package
```

The audit checks the public inventory, literal IPv4/IPv6 strings, private paths,
email addresses, full account identifiers, secret-like values and image metadata.
The separate package check verifies client component hashes and launcher dependencies.
Review names and other free text as well: pattern scanning cannot identify every
possible secret or personal detail. Do not force-add ignored files.
If you have previously committed private files, ignoring them does not remove
them from Git history; clean that history and rotate exposed credentials before
publishing. Source updates copy only the reviewed file inventory, not another
checkout's Git metadata. These working-tree checks do not inspect or rewrite
existing commits, author information or other historical metadata.

API evidence in `api/` describes the recovered baseline, not an original live
server. The loopback response example uses a placeholder instead of a literal
address. Native loopback behavior is unchanged. Baseline source hashes in the
evidence are historical references, not hashes of this anonymized snapshot.

Recovered Library artwork and game text remain subject to their owners' rights.
This snapshot does not grant a license to third-party assets or original code.
Review redistribution rights before making a public repository.
