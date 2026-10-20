# Rise of Incarnates Revival Sources

An anonymized source snapshot based on the Library text update. No configured
server address, personal account, certificate pin, game executable, Steam DLL,
runtime profile, credential, log or Git history is included.

## Local Settings

Copy `deployment.example.json` to `deployment.local.json` at the repository root.
Only the example belongs in Git. The local file and generated settings are ignored.
An explicit `ROI_DEPLOYMENT_FILE` environment variable can point to a private copy
elsewhere. A component-local copy in `client/` or `server/` is also supported;
it takes precedence over the repository-root file. Use the same structure.

Fill only the fields needed for your chosen mode:

| Fields | Purpose |
| --- | --- |
| `client.steam_path`, `depot_path`, `game_path` | Optional local paths; blank uses Steam discovery/prompts and the client-local game folder. Setup command-line arguments take precedence. |
| `client.internet_host`, `lan_host`, `port` | Your gateway's public and LAN hostnames or IPv4 addresses, and external TCP port. The LAN and Internet launchers can target the same server. |
| `client.certificate_sha256` | SHA-256 fingerprint of **your own** gateway certificate. Verify it through a trusted channel; never disable pin checks. |
| `client.vpn_lobby_host`, `vpn_lobby_port` | Endpoint used by private VPN joining and access-file provisioning. |
| `server.public_bind_host`, `public_port` | Explicit local server interface and published TCP port. `any` intentionally publishes on every IPv4 interface; there is no implicit wildcard default. |
| `server.vpn_bind_host`, `vpn_interface`, `vpn_network` | Explicit VPN interface address, interface name and CIDR. The address must belong to the CIDR. |
| `server.python_base` | Reviewed official Python image reference, including an immutable SHA-256 digest. No operator's image pin is supplied. |

Blank public/VPN settings fail closed. Steam Discovery and local-only modes do
not require a deployment file. Internal native-game loopback addresses are
constructed in `network_defaults.py`, rather than storing literal IP strings.
These protocol-local bindings are not user-configurable or public listeners.

## Client Setup

1. Install Python 3.10+ and the supported Steam game plus historical asset depot.
2. Fill optional local paths in the ignored deployment file, or use discovery.
3. Run `client/Setup.bat`. It builds the patched executable from your own game.
4. Run `Online - Steam.bat` for your configured public gateway, or
   `Online - Steam (LAN).bat` for its LAN route. Both start the game.
5. `Online - Steam Discovery.bat` uses Steam lobby discovery without a gateway.

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
```

The audit checks the public inventory, literal IPv4/IPv6 strings, personal-name
patterns, private paths, full account identifiers, secret-like values and generated
files. It checks image metadata and manifests too. Do not force-add ignored files.
If you have previously committed private files, ignoring them does not remove
them from Git history; clean that history and rotate exposed credentials before
publishing. This snapshot was created without copying another checkout's history.

API evidence in `api/` describes the recovered baseline, not an original live
server. The loopback response example uses a placeholder instead of a literal
address. Native loopback behavior is unchanged. Baseline source hashes in the
evidence are historical references, not hashes of this anonymized snapshot.

Recovered Library artwork and game text remain subject to their owners' rights.
This snapshot does not grant a license to third-party assets or original code.
Review redistribution rights before making a public repository.
