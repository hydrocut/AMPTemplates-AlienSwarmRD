# AMPTemplates-AlienSwarmRD — Alien Swarm: Reactive Drop dedicated server for AMP

**AMP Generic Module** template for the **Alien Swarm: Reactive Drop** dedicated server (free game,
Steam app `563560`; dedicated server `582400`, anonymous SteamCMD), on **Linux under Wine**, for co-op
games of up to 8 players. Written for TeamKit, a free French game host, on 12 Oct 2026.

> Résumé en français à la fin du fichier.

Based on the community template by **Greelan** shipped in
[CubeCoders/AMPTemplates](https://github.com/CubeCoders/AMPTemplates) (`alien-swarm-reactive-drop*`):
same SteamCMD app, Wine image and Source RCON. Thanks to him. This version differs on the points below,
all checked on a real server (see *Tested*).

## Differences with the CubeCoders / Greelan template

| | Greelan template | This template |
|---|---|---|
| Console | not readable (`HasReadableConsole=False`): no join/leave/chat in AMP | readable: the game log (`-condebug` → `console.log`) is copied to stdout, with French `TeamKit : …` lines for ready / join / leave / chat |
| How it runs | `xvfb-run wine srcds.exe` | `srcds_console.exe` inside a pseudo-terminal (`script`), **no Xvfb**: without a terminal the Windows console of the game stops at once (`CTextConsoleWin32::GetLine: !GetNumberOfConsoleInputEvents`) |
| VAC | always `-insecure` | **secure by default** (works under Wine: `VAC secure mode is activated`), `-insecure` only if *Anti-triche VAC* is unticked |
| `server.cfg` | executed once (`+exec`) | executed at start **and at every map** (the game runs `newmapsettings.cfg` on each map load; the template makes it `exec server.cfg`). The game itself never runs `server.cfg` |
| Lobby-only | `sv_allow_lobby_connect_only 1` | `0` by default (see below) |
| RCON | binds to the container address only | `-ip 0.0.0.0`: RCON listens on 127.0.0.1 too, where AMP connects |
| Ports | game, client and SourceTV ports | **one port** (UDP game + TCP RCON). `+clientport` and `+tv_port` are read too late by this engine (sockets already open on 27005 / 27020); the client port is outgoing only and moves to the next free one; SourceTV is off (`-nohltv`) |
| Empty-server shutdown | the game quits after 1 h when empty (`rd_server_shutdown_after_num_secs 3600`) and AMP sees a stopped server | the start script relaunches it at once; delay exposed in AMP |
| Text | raw | the engine reads `.cfg` files byte by byte: a UTF-8 letter splits the line (`hostname "… été"` became `[FR] TeamKit` + `Unknown command`). Names and messages are transliterated to ASCII; passwords with non-ASCII, `"` or `;` are refused with a message |
| Game settings | Source generic cvars | difficulty, Onslaught, hardcore friendly fire, challenges, default campaign, locks, Workshop, welcome message, bans, votes, idle kick (see below) |

## How it runs

- Image **`cubecoders/ampbase:wine-stable`** (Debian 13, Wine 11.0), container **required**. The server
  is Windows-only and 32-bit (`srcds_console.exe`, `PE32`); a `win64` prefix runs it.
- AMP runs `/bin/bash lancer-asrd.sh <port> <max players>`. The script reads `582400/reglages-asrd.txt`
  (rendered by AMP from `AMP_reglages-asrd.txt`), validates every value, writes
  `reactivedrop/cfg/server.cfg`, `newmapsettings.cfg`, `workshop.cfg` (and `perso.cfg` once, never
  overwritten), then starts:
  `wine srcds_console.exe -game reactivedrop -console -condebug -nobreakpad -nohltv -ip 0.0.0.0 -port <port> -maxplayers <n> [-insecure] +rd_dedicated_server_language french +sv_logfile 0 +log on +exec server.cfg +map lobby`
- Ready line (`Console.AppReadyRegex`): `TeamKit : serveur Alien Swarm: Reactive Drop pret (port N).`,
  printed on `Connection to Steam servers successful.` (3–4 s after start). Without Steam after 3 min it
  warns and declares ready anyway; with no map loaded it stops with an error.
- Stop (AMP `SIGTERM`): `quit` is typed into the game console, Wine is killed after 20 s at most.
  Measured: 3 s, no process left. After a hard kill of the script, the next start cleans Wine first.
- If the game quits by itself after more than 2 minutes (empty-server shutdown, `quit` from RCON), the
  script relaunches it. If the game announced an update (`Your server is out of date…`), the script
  stops for good and says to run Update.

### Challenges are re-armed

When the server empties (and at start), the game resets difficulty to 2 and the challenge to none, then
loads the first mission of `asw_default_campaign` (`CAlienSwarm::OnServerHibernating`). `server.cfg`
puts the values back, but a challenge only becomes active when a map is loaded (`EnableChallenge` in the
game rules constructor). So, when a challenge is set, the script reloads that map once, server still
empty (`changelevel`, 1 s). Checked with the server query: game description `ASBI` / `One Hit`.

### Lobby-only connections

`sv_allow_lobby_connect_only` is an engine cvar (default `1`). In the public game code a client that
arrives without a Steam lobby sends `cl_lobby_invalid_request`, and the server kicks it ("Wait a few
seconds and reconnect to this server (lobby not found)") when the cvar is 1. The in-game dedicated
server list joins with `connect <IP:port>` (`vfoundgames.cpp`). Default here: `0`, so players can join
from the list and by IP. Not tested with a real client.

## Settings exposed in AMP (French UI)

| Group | Settings (game cvar) |
|---|---|
| Serveur | name (`hostname`), password (`sv_password`), RCON (AMP random), max players 1–8 (`-maxplayers`; the engine takes 32, a mission has 8 marines), region (`sv_region`, Europe), tags (`sv_tags`, `fr,teamkit`: the game adds its own and cuts the total at 64 characters), VAC, lobby-only, welcome message + delay (`rm_welcome_message`, `rm_welcome_message_delay`) |
| Partie | difficulty 1–5 (`asw_skill`), Onslaught (`asw_horde_override` + `asw_wanderer_override`), hardcore friendly fire (`asw_marine_ff_absorption 0` + `asw_sentry_friendly_fire_scale 1`, what the lobby checkbox does), challenge (10 official co-op challenges, or a Workshop challenge id), lock these choices (`rd_lock_*`), default campaign (`asw_default_campaign`, 12 campaigns), auto restart on failure (`rd_auto_fast_restart`), one-player missions (`asw_ignore_need_two_player_requirement`), bots (`rd_player_bots_allowed`), idle kick (`rd_kick_inactive_players`) |
| Bans et votes | banned SteamIDs (`banid`, any form converted to `STEAM_1:Y:Z`), kick vote share (`asw_vote_kick_fraction`), mission vote share (`asw_vote_map_fraction`) |
| Workshop et avancé | Workshop item ids (`rd_enable_workshop_item` in `workshop.cfg`), empty-server restart delay (`rd_server_shutdown_after_num_secs`), stop on game update (`rd_server_restart_on_update`) |

Every cvar was read in the real server (`cvarlist`, `help`, value read back after start). Not exposed:
`rd_hackall` (cheat cvar, refused without `sv_cheats 1`), SourceTV, client port, a start mission (the
game always goes to the first mission of the default campaign when empty), map rotation (`rd_mapcycle_*`
only apply to Deathmatch / Bonus / Endless), admin list (the game has none: admins use RCON), Steam group
(`sv_steamgroup*`, not testable without clients): use `perso.cfg`.

## Files

| File | Role |
|---|---|
| `asrd.kvp`, `asrd*.json`, `manifest.json` | the AMP template |
| `scripts/AMP_reglages-asrd.txt` | settings model, rendered by AMP to `582400/reglages-asrd.txt` |
| `scripts/lancer-asrd.sh` | start script |
| `verifier.py` | pre-push checks, must print `Tout est bon.` |

Both `scripts/` files are downloaded from this repository (raw.githubusercontent.com, branch `main`) at
each Update, so **the repository must be public**.

## Update stages

1. SteamCMD app `582400` (game `563560`), `ForceDownloadPlatform: Windows`, anonymous.
2. FetchURL `AMP_reglages-asrd.txt` and `lancer-asrd.sh` into the instance root.
3. `lancer-asrd.sh preparer`: creates the Wine prefix if missing (13 s, 1.4 GB, kept across Updates),
   prints the Wine version and the Steam build id.

Greelan's extra SteamCMD stage (app `1007`) is not needed: `steamclient.dll` ships with `582400` and the
server connected to Steam without it.

## Console, players, admin

- AMP commands go through **Source RCON** (`AdminMethod=SourceRCON`, random password kept by AMP,
  127.0.0.1 + game port). Tested: wrong password refused, `status`, `say`, cvars.
- Player list: `TeamKit : <name> a rejoint la partie (SteamID …).` / `a quitte la partie` / `[Chat] <name> : <text>`,
  built from the Source log lines `"Name<id><STEAM_1:…><>" entered the game`, `disconnected (reason "…")`,
  `say "…"`. The format was read on real SourceTV / console lines; **no human player joined during the
  test**.
- In-game admins: `rcon_password <password>` then `rcon <command>` in the game console (`kickid`,
  `banid 0 STEAM_1:0:123` + `writeid`: kept in `banned_user.cfg`, loaded at every map).

## Tested (12 Oct 2026, throwaway container on the TeamKit host)

| | |
|---|---|
| Install | SteamCMD anonymous, 2.87 GB downloaded, 2.7 GB on disk, build `25157705`, version `7.1.4.6/7146 7940` |
| Ready | 3–4 s after start; Steam connected; VAC secure; server query answers with name, map, challenge, tags, password flag |
| Port | `-port` works (27215 tested); UDP + TCP on 0.0.0.0 |
| RAM / CPU | `srcds_console.exe` 240–295 MB resident, ~1.2 % of one core when empty (hibernating); plan 1.5 GB |
| Disk | 2.7 GB server + 1.4 GB Wine prefix (+ Workshop items, e.g. 680 MB for a 221 MB campaign download) |
| Workshop | item 1093180806 downloaded by the server (221 MB), then the game restarted its map by itself to load it |
| Empty shutdown | with 1 min: game quit after ~2 min, relaunched by the script |
| Stop | SIGTERM: 3 s, nothing left; SIGKILL then start: cleaned and restarted |

Not tested: a real player joining (list, IP, password, ban, welcome message, chat, join/leave lines),
`sv_allow_lobby_connect_only` with a client, the update shutdown, and AMP itself (Update, template
rendering, RCON console) — the first AMP install is the real test.

## Before pushing

```
python verifier.py
```

Must print `Tout est bon.`: JSON, includes, complete `Console.*` / `Limits.*`, new ids, Wine image,
settings ↔ model ↔ script keys, choices ↔ accepted values ↔ installed challenges and campaigns, download
URLs, LF/ASCII, `bash -n`, 20 runs of the **real script** under bash (Wine stubbed) with the `server.cfg`
read back like the engine (ASCII, one command per line), the log filter on real server lines, and the
console regexes.

## Install in AMP

ADS → Configuration → Instance Deployment → **Configuration Repositories**: add
`hydrocut/AMPTemplates-AlienSwarmRD:main`, save, **Fetch latest**. Create Instance →
**Alien Swarm: Reactive Drop (TeamKit)**, game port (UDP + TCP) → **Update** (must end with
`TeamKit : serveur dedie installe, build Steam …`) → **Start**.

## Credits

Alien Swarm: Reactive Drop is © Reactive Drop Team / Valve. Original AMP template by Greelan
(CubeCoders/AMPTemplates). This repository only contains the template; the server is downloaded from
Steam by SteamCMD.

---

## Résumé en français

Template AMP pour le **serveur dédié d'Alien Swarm: Reactive Drop** (jeu gratuit ; serveur Steam
582400 téléchargé **sans compte**), en coopération jusqu'à **8 joueurs**. Il part du template de
**Greelan** (dépôt de CubeCoders) et le corrige :

- **Console lisible dans AMP** : arrivées, départs et chat dans la liste des joueurs, ligne « prêt »
  claire. Le serveur tourne sous **Wine** dans le conteneur `cubecoders/ampbase:wine-stable`
  (obligatoire), sans Xvfb, dans un pseudo-terminal.
- **Anti-triche VAC actif** (le mode sécurisé marche sous Wine) ; `-insecure` seulement sur demande.
- **Un seul port** à ouvrir (UDP jeu + TCP RCON), réglable : plusieurs instances possibles.
- **Rejoignable par la liste des serveurs du jeu et par IP** (`sv_allow_lobby_connect_only 0`).
- **Réglages en français** : nom, mot de passe, région Europe, tags, message d'accueil avec le Discord,
  difficulté, Onslaught, tir ami hardcore, défis, campagne de départ, verrouillage des choix, relance
  auto après échec, bots, inactifs, bannis (SteamID), votes, objets du Workshop, redémarrage à vide.
- Le jeu **lit ses fichiers en ASCII** : accents retirés automatiquement du nom et du message.
- Le jeu **s'arrête seul** quand il est vide depuis une heure (voulu par ses développeurs) : le
  template le relance aussitôt.
- **Testé en vrai** le 12 oct. 2026 dans un conteneur jetable : prêt en 3 à 4 s, ~300 Mo de RAM,
  4,1 Go sur disque, Workshop téléchargé, RCON, arrêt propre. **Pas testé : un vrai joueur.**
- Avant de pousser : `python verifier.py` doit répondre « Tout est bon. ».
