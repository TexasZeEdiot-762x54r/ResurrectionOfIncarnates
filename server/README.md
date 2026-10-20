# Rise of Incarnates revival: private lobby server

## Anonymized Configuration

Start with the repository-root README and `deployment.example.json`. Real host
addresses, the TLS pin and setup paths belong only in the ignored local file.
Run `python configure.py --mode public` or `--mode vpn` from this folder to
generate Compose variables. The historical notes below do not override these
configuration requirements. No service was deployed by preparing this snapshot.

## Separate Public TLS Variant (2026-10-19)

Read `PUBLIC-LOBBY.txt` for the public deployment. It uses `compose.public.yaml`
and `Dockerfile.public`, publishing only TLS TCP 52714. It deliberately allows
anonymous identities, without invitations, and must use its own directory and
TLS key. Do not remove authentication from the private deployment below.
Only the public certificate fingerprint, not the private key, belongs in clients.

## Current hardened setup (2026-10-18)

Use this section instead of the legacy examples below. The bundled Compose file
binds only to **<vpn_bind_host>**, with TCP **52711** for lobbies and **52713** for the
authenticated profile relay. Both ports must be reachable only through WireGuard.
Do not put wg0 in firewalld's trusted zone or publish these ports on the internet.

1. Extract this ZIP to a new server directory on Rocky Linux. Keep SELinux enabled.
2. Using Python 3.10+, create a private invitation without listing Steam IDs:
   `python3 provision_players.py --invite`.
   This writes `private/lobby-auth.json` and `private/lobby-invitation.json`.
   Existing credentials are preserved on reruns. The Compose default now sets
   `ROI_AUTH_MODE=invite`; unlisted IDs are admitted with a valid invitation key.
3. Send the private invitation only to trusted WireGuard players. On Windows,
   rename it `lobby-access.json` beside Import Lobby Access.bat and import it after Setup.
4. For the non-root container, make only the auth secret readable by UID 10001:
   `sudo chown 10001:10001 private/lobby-auth.json` and
   `sudo chmod 0400 private/lobby-auth.json`. Keep the private directory mode 0700.
5. Set `server.python_base` in your private deployment file to an official
   `python:TAG@sha256:DIGEST` reference. Run `python configure.py --mode vpn`,
   then review `docker compose config` before starting the service.
   Podman users can use a compatible Compose provider with the same compose.yaml;
   verify secrets and non-root file access before enabling automatic startup.
6. Review HARDENING.txt and the supplied port-specific firewall guard before
   exposing the container on your WireGuard interface. Inspect container logs;
   never disable SELinux or use privileged mode to resolve a permissions failure.

For an existing server, preserve its private directory, existing image digest,
service paths and firewall rules. Do not provision a new set of tokens over it.
The supplied systemd units contain deployment-specific paths; inspect/adapt them
before installation. This ZIP is not an unattended root installer.

Invite-mode limits: this removes Steam-ID preapproval, not authentication or the
VPN requirement. Anyone with an invitation can claim a previously unregistered
ID; Steam ownership is not verified. First-use ID/key bindings are held in memory
(maximum 128 new IDs) until server restart. Already-provisioned accounts keep
their original keys, and a different key cannot overwrite a claimed profile.
People sharing the same invitation key share its trust: keep invitations private.
Existing per-player keys also work as invitations, so installed clients do not
need replacement credentials just to keep connecting.

For the old strict allowlist behavior, set ROI_AUTH_MODE=bound and provision with
`--steam-id STEAMID64`. Never remove the credential secret to simulate open access.

Skill-grid storage and migration run on each player's loopback profile server.
No shared-lobby protocol or current Rocky deployment change is needed for this
grid patch. Client and server ZIPs contain no player credentials or game assets.

## Legacy topology reference (not deployment commands)

This bundle is the **server side** only: the shared lobby server that lists custom rooms and lets players join
them. It runs in a container (Docker or Podman, e.g. on Rocky Linux) or with plain Python 3.10+.

## What runs where

| Where | Process | Purpose |
|---|---|---|
| Server (this bundle) | `nrt_server.py` (container `roi-lobby`), TCP 52711 | Lobby list: create, search, join, leave |
| Each player's PC (client package) | patched `roi.exe` | the game |
| Each player's PC | `server.py` on loopback:52710 | that player's profile, outfits, master data (local only) |
| Each player's PC | Steam client | login, and the match connection between players |

When a client uses this server (`Online - Join.bat`), it does **not** run its own lobby server. Matches do not go
through this server or the VPN: the host's game registers with Steam and the others connect to it through Steam,
so every player needs Steam running and internet access as usual.

## Logs

Use `docker logs roi-lobby` (or the equivalent Podman command). Keep logs private.
Do not launch the shared server without ROI_AUTH_FILE or without the secret mount.

## Players

1. Install the client package (`RiseOfIncarnates-Offline`) and run its `Setup.bat` once.
2. Connect to the WireGuard network.
3. Import your administrator-provisioned private lobby access file for <vpn_bind_host>.
4. Run `Play Rise of Incarnates.bat`, then Play → Custom Match → Create Lobby / Search Lobby → Advanced Search.

`Online - Steam Discovery.bat` selects Steam discovery; `Online - Steam.bat`
uses the separately configured public TLS gateway.

## Notes

- Everyone, server included, should use files from the same package version.
- Rooms live in memory: restarting the container closes all open lobbies (players just create them again).
- The server log contains players' Steam IDs; keep it private.
