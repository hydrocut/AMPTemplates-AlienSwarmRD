#!/bin/bash
# lancer-asrd.sh - pose par le template AMP TeamKit (recree a chaque Update).
#
#   lancer-asrd.sh preparer                          etape d'Update : prefixe Wine, dossiers
#   lancer-asrd.sh <port> <joueurs max>                demarrage (ligne de commande d'AMP)
#   lancer-asrd.sh filtre                            (verifier.py) journal -> console
#
# Le serveur dedie d'Alien Swarm: Reactive Drop (app Steam 582400) n'existe qu'en version
# Windows 32 bits : il tourne ici sous Wine (image cubecoders/ampbase:wine-stable).
# Ce script :
#  1. lit les reglages qu'AMP ecrit dans 582400/reglages-asrd.txt et les controle ;
#  2. ecrit reactivedrop/cfg/server.cfg (relu par le jeu a CHAQUE carte), workshop.cfg et,
#     une seule fois, perso.cfg (lignes en plus, jamais ecrase) ;
#  3. lance srcds_console.exe dans un pseudo-terminal (script) : sans terminal, sa console
#     Windows s'arrete net ("CTextConsoleWin32::GetLine: !GetNumberOfConsoleInputEvents",
#     essai du 12/10/2026). Sans affichage : ni Xvfb ni DISPLAY ;
#  4. recopie le journal du jeu (-condebug -> reactivedrop/console.log) dans la console
#     d'AMP, sans le bruit, et y ajoute des lignes "TeamKit : ..." en francais : pret,
#     arrivees, departs, chat (lues par les regex d'AMP) ;
#  5. relance le jeu s'il s'arrete tout seul (rd_server_shutdown_after_num_secs : le jeu
#     se coupe quand il est vide depuis 90 s apres N secondes de marche, voulu par les
#     developpeurs) ; s'arrete pour de bon si le jeu annonce une mise a jour ;
#  6. a l'arret demande par AMP (SIGTERM) : "quit" dans la console du jeu, puis Wine coupe.
cd "$(dirname "$0")" || exit 1
ICI="$PWD"
JEU="$ICI/582400"
MOD="$JEU/reactivedrop"
BIN="$JEU/srcds_console.exe"
REGLAGES="$JEU/reglages-asrd.txt"
CFG="$MOD/cfg/server.cfg"
WORKSHOP="$MOD/cfg/workshop.cfg"
PERSO="$MOD/cfg/perso.cfg"
LOGJEU="$MOD/console.log"

export WINEPREFIX="$ICI/.wine" WINEARCH=win64 WINEDEBUG=-all
export LANG=C.UTF-8 LC_ALL=C.UTF-8
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp}"
unset DISPLAY

manque_jeu() {
  echo "ERREUR : $BIN introuvable. Lance Update : SteamCMD telecharge le serveur (app 582400, sans compte Steam)."
}

# -- Journal du jeu -> console d'AMP ------------------------------------------
# Lignes de journal (log on) : L 10/12/2026 - 18:49:56: "Nom<2><[U:1:123]><>" entered the game
RE_JOUEUR='^L [0-9/]+ - [0-9:]+: "(.*)<([0-9]+)><([^<>]*)><([^<>]*)>" (.*)$'
RE_CVAR='^L [0-9/]+ - [0-9:]+: "[A-Za-z0-9_.]+" = "'
lire_journal() {
  local l nom id sid reste msg
  while IFS= read -r l; do
    l="${l%$'\r'}"
    # liste des reglages a chaque carte (60 lignes) : L ...: "sv_cheats" = "0"
    [[ "$l" =~ $RE_CVAR ]] && continue
    case "$l" in
      # avertissements sans effet, releves a chaque demarrage
      *': server cvars start'|*': server cvars end'|*': Log file started '*|*': Log file closed'|\
      'Server logging data to file '*|'Cannot access ISteamInventory!'|'-- Error --:  empty soundname'*|\
      'Unknown command "mat_do_not_shrink_dynamic_vb"'|'Setting breakpad minidump AppID'*|\
      'SteamInternal_SetMinidumpSteamID'*|'Unqualified = '*|'')
        continue ;;
    esac
    printf '%s\n' "$l"
    case "$l" in
      'Connection to Steam servers successful.'*)
        : > "$ETAT/steam"
        if [ ! -e "$ETAT/pret" ]; then
          : > "$ETAT/pret"
          echo "TeamKit : serveur Alien Swarm: Reactive Drop pret (port $PORT)."
        fi ;;
      'Server is hibernating'*) : > "$ETAT/veille" ;;
      'L '*': Started map "'*)
        : > "$ETAT/carte"
        # Serveur vide : le jeu remet difficulte 2 et "aucun defi", puis charge la campagne
        # par defaut (CAlienSwarm::OnServerHibernating). server.cfg (via newmapsettings.cfg)
        # remet nos valeurs, mais un defi n'est active qu'au chargement d'une carte : on
        # recharge donc une fois la carte, serveur toujours vide (essai du 12/10/2026).
        # (au demarrage et apres un "restart" interne, ce passage se fait depuis la carte lobby)
        carte="${l#*Started map \"}"; carte="${carte%%\"*}"
        if [ "$carte" = lobby ]; then : > "$ETAT/veille"; fi
        if [ -e "$ETAT/veille" ] && [ "$carte" != lobby ]; then
          rm -f "$ETAT/veille"
          if [ "$DEFI" != 0 ]; then
            echo "TeamKit : serveur vide, rechargement de $carte pour activer le defi $DEFI."
            console_jeu "changelevel $carte"
          fi
        fi ;;
      'Your server is out of date'*)
        : > "$ETAT/maj"
        echo "TeamKit : une mise a jour du jeu est sortie. Le serveur s'arretera des qu'il sera vide : lance Update dans AMP, puis Start." ;;
      *': server_message: "quit"'*) : > "$ETAT/quit" ;;
    esac
    if [[ "$l" =~ $RE_JOUEUR ]]; then
      nom="${BASH_REMATCH[1]}"; id="${BASH_REMATCH[2]}"; sid="${BASH_REMATCH[3]}"; reste="${BASH_REMATCH[5]}"
      case "$sid" in BOT|Console|'') continue ;; esac
      case "$reste" in
        'entered the game')
          echo "TeamKit : $nom a rejoint la partie (SteamID $sid)." ;;
        'disconnected'*)
          echo "TeamKit : $nom a quitte la partie (SteamID $sid)." ;;
        'say "'*'"'|'say_team "'*'"')
          msg="${reste#* \"}"; msg="${msg%\"}"
          echo "[Chat] $nom : $msg" ;;
      esac
    fi
  done
}
# Commande dans la console du jeu (tuyau ouvert sur le descripteur 3 par le lanceur).
console_jeu() {
  if [ -n "$TK_FILTRE" ]; then echo "(console du jeu) $1"; else printf '%s\r' "$1" >&3; fi
}
# Utilise par verifier.py : passe un journal du jeu (entree standard) dans le filtre.
#   lancer-asrd.sh filtre <port> <defi>
if [ "$1" = "filtre" ]; then
  ETAT=$(mktemp -d) || exit 1
  PORT="${2:-27015}"
  DEFI="${3:-0}"
  TK_FILTRE=1
  lire_journal
  rm -rf "$ETAT"
  exit 0
fi

if [ "$1" = "preparer" ]; then
  [ -f "$BIN" ] || { manque_jeu; exit 1; }
  if [ ! -f "$WINEPREFIX/system.reg" ]; then
    echo "TeamKit : creation du prefixe Wine (une quinzaine de secondes, une seule fois)..."
    # mscoree / mshtml : pas de Mono ni de Gecko a telecharger, le jeu n'en a pas besoin.
    WINEDLLOVERRIDES="mscoree,mshtml=" timeout 300 wineboot --init > /dev/null 2>&1
    timeout 60 wineserver -w
    if [ ! -f "$WINEPREFIX/system.reg" ]; then
      echo "ERREUR : la creation du prefixe Wine a echoue. Cette instance doit tourner dans le conteneur cubecoders/ampbase:wine-stable."
      exit 1
    fi
  fi
  mkdir -p "$MOD/cfg" || exit 1
  build=$(sed -n 's/^[[:space:]]*"buildid"[[:space:]]*"\([0-9]*\)".*/\1/p' "$JEU/steamapps/appmanifest_582400.acf" 2>/dev/null | head -n 1)
  echo "TeamKit : $(wine --version 2>/dev/null || echo 'Wine introuvable'), prefixe pret."
  echo "TeamKit : serveur dedie installe, build Steam ${build:-inconnu}."
  exit 0
fi

# -- Demarrage ----------------------------------------------------------------
refuser() {
  echo "ERREUR : $1"
  echo "Corrige ce reglage dans l'onglet Configuration d'AMP, puis relance."
  exit 1
}

PORT="$1"; JOUEURS="$2"
[[ "$PORT" =~ ^[0-9]+$ ]] && [ "$PORT" -ge 1024 ] && [ "$PORT" -le 65535 ] || refuser "port '$PORT' invalide (1024 a 65535)."
[[ "$JOUEURS" =~ ^[0-9]+$ ]] && [ "$JOUEURS" -ge 1 ] && [ "$JOUEURS" -le 8 ]   || refuser "joueurs maximum '$JOUEURS' : de 1 a 8 (8 marines jouables par mission)."
[ -f "$BIN" ] || { manque_jeu; exit 1; }
[ -f "$REGLAGES" ] || { echo "ERREUR : $REGLAGES absent. AMP l'ecrit au demarrage a partir de AMP_reglages-asrd.txt : lance Update."; exit 1; }
command -v wine > /dev/null || { echo "ERREUR : Wine absent. Cette instance doit tourner dans le conteneur cubecoders/ampbase:wine-stable."; exit 1; }
command -v script > /dev/null || { echo "ERREUR : la commande script (util-linux) est absente du conteneur."; exit 1; }
[ -f "$WINEPREFIX/system.reg" ] || { echo "ERREUR : prefixe Wine absent : lance Update."; exit 1; }

declare -A R
while IFS= read -r ligne || [ -n "$ligne" ]; do
  ligne="${ligne%$'\r'}"
  case "$ligne" in
    \#*|'') ;;
    *=*) R["${ligne%%=*}"]="${ligne#*=}" ;;
  esac
done < "$REGLAGES"

# Texte libre ecrit entre guillemets droits dans server.cfg. Le jeu lit ses .cfg octet par
# octet : une lettre accentuee (UTF-8) coupe la ligne en morceaux (essai du 12/10/2026 :
# hostname "[FR] TeamKit - ete" devenait "[FR] TeamKit" suivi de "Unknown command").
# Donc : lettres accentuees -> sans accent, ponctuation typographique -> ASCII, le reste
# (emojis...) retire ; " devient ' (il fermerait la valeur), ; devient , (il couperait la
# commande) ; caracteres de controle retires.
ASCII_TABLE="c3a0:a c3a1:a c3a2:a c3a3:a c3a4:a c3a5:a c3a6:ae c3a7:c c3a8:e c3a9:e c3aa:e c3ab:e
c3ac:i c3ad:i c3ae:i c3af:i c3b1:n c3b2:o c3b3:o c3b4:o c3b5:o c3b6:o c3b9:u c3ba:u c3bb:u c3bc:u
c3bd:y c3bf:y c39f:ss c380:A c381:A c382:A c383:A c384:A c385:A c386:AE c387:C c388:E c389:E
c38a:E c38b:E c38c:I c38d:I c38e:I c38f:I c391:N c392:O c393:O c394:O c395:O c396:O c399:U c39a:U
c39b:U c39c:U c39d:Y c592:OE c593:oe c5b8:Y e28093:- e28094:- e28092:- e28098:' e28099:' e2809c:'
e2809d:' c2ab:' c2bb:' e280a6:... e282ac:EUR c2b7:- e280a2:-"
texte() {
  local v="$1" p o h
  for p in $ASCII_TABLE; do
    h="${p%%:*}"; o=""
    while [ -n "$h" ]; do o="$o\x${h:0:2}"; h="${h:2}"; done
    printf -v o "$o"
    v="${v//"$o"/${p#*:}}"
  done
  for h in c2a0 e280af e28089; do   # espaces insecables -> espace
    o=""; while [ -n "$h" ]; do o="$o\x${h:0:2}"; h="${h:2}"; done
    printf -v o "$o"
    v="${v//"$o"/ }"
  done
  local q="'"
  v="${v//\"/$q}"
  v="${v//;/,}"
  printf '%s' "$v" | LC_ALL=C tr -cd '\040-\176' | tr -s ' ' | sed 's/^ //; s/ $//'
}

NOM=$(texte "${R[nom]}")
MDP="${R[motdepasse]}"
RCON="${R[rcon]}"
# Les mots de passe ne sont pas retouches (le joueur tape l'original) : on refuse ce que le
# jeu lirait mal.
for v in MDP RCON; do
  if [ -n "$(printf '%s' "${!v}" | LC_ALL=C tr -d '\040-\176')" ] || [[ "${!v}" == *[\"\;]* ]]; then
    refuser "mot de passe ($v) : lettres sans accent, chiffres et ponctuation simple seulement, sans guillemet \" ni point-virgule."
  fi
done
REGION="${R[region]:-3}"
TAGS=$(texte "${R[tags]}")
VAC="${R[vac]:-1}"
LOBBY="${R[lobby_seul]:-0}"
ACCUEIL=$(texte "${R[accueil]}")
NIVEAU="${R[difficulte]:-2}"
ONSLAUGHT="${R[onslaught]:-0}"
FF="${R[tir_ami_hardcore]:-0}"
DEFI="${R[defi]:-0}"
DEFI_AUTRE=$(texte "${R[defi_autre]}")
VERROU="${R[verrouiller]:-0}"
CAMPAGNE="${R[campagne]:-jacob}"
DEUX="${R[seul_possible]:-1}"
INACTIF="${R[inactifs]:-0}"
DELAI="${R[delai_accueil]:-10}"
ECHEC="${R[echec_auto]:-0}"
BOTS="${R[bots]:-1}"
VOTE_EXCL="${R[vote_exclusion]:-60}"
VOTE_MISSION="${R[vote_mission]:-60}"
BANNIS="${R[bannis]}"
VIDE="${R[redemarrage_vide]:-60}"
MAJ="${R[arret_maj]:-1}"
WS="${R[workshop]}"

[ -n "$NOM" ] || NOM="[FR] TeamKit - Alien Swarm: Reactive Drop"
[[ "$REGION" =~ ^(-1|0|1|2|3|4|5|6|7|255)$ ]] || refuser "region '$REGION' inconnue."
for v in VAC LOBBY ONSLAUGHT FF VERROU DEUX MAJ ECHEC BOTS; do
  [[ "${!v}" =~ ^[01]$ ]] || refuser "case a cocher $v : '${!v}' (0 ou 1)."
done
[[ "$NIVEAU" =~ ^[1-5]$ ]] || refuser "difficulte '$NIVEAU' : de 1 (facile) a 5 (brutal)."
[[ "$DEFI" =~ ^(0|asbi|difficulty_tier1|difficulty_tier2|energy_weapons|level_one|one_hit|rd_first_person|rd_third_person|riflemod_classic|traitors)$ ]] \
  || refuser "defi '$DEFI' inconnu."
if [ -n "$DEFI_AUTRE" ]; then
  [[ "$DEFI_AUTRE" =~ ^[A-Za-z0-9_.-]{1,64}$ ]] || refuser "identifiant de defi '$DEFI_AUTRE' : lettres, chiffres, _ . - seulement (nom du fichier du defi, sans .txt)."
  DEFI="$DEFI_AUTRE"
fi
[[ "$CAMPAGNE" =~ ^(jacob|rd-area9800|rd-operationcleansweep|rd-tarnorcampaign1|rd_accident32|rd_biogen_corporation|rd_lanasescape_campaign|rd_nh_campaigns|rd_paranoia|rd_reduction_campaign|rd_research7|tilarus5)$ ]] \
  || refuser "campagne '$CAMPAGNE' inconnue."
[[ "$INACTIF" =~ ^[0-9]+$ ]] && [ "$INACTIF" -le 3600 ] || refuser "exclusion des inactifs '$INACTIF' : de 0 a 3600 secondes."
[[ "$DELAI" =~ ^[0-9]+$ ]] && [ "$DELAI" -le 30 ] || refuser "delai du message d'accueil '$DELAI' : de 0 a 30 secondes."
for v in VOTE_EXCL VOTE_MISSION; do
  [[ "${!v}" =~ ^[0-9]+$ ]] && [ "${!v}" -ge 1 ] && [ "${!v}" -le 100 ] || refuser "part des joueurs pour un vote ($v) '${!v}' : de 1 a 100 %."
done
[[ "$VIDE" =~ ^[0-9]+$ ]] && [ "$VIDE" -le 10080 ] || refuser "redemarrage a vide '$VIDE' : de 0 (jamais) a 10080 minutes."
# Objets du Workshop : numeros separes par des espaces, virgules ou retours a la ligne.
IDS=""
for i in $(printf '%s' "$WS" | tr ',;' '  '); do
  [[ "$i" =~ ^[0-9]{1,20}$ ]] || refuser "objet du Workshop '$i' : il faut le numero (id=... dans l'adresse de la page du Workshop)."
  IDS="$IDS $i"
done
# Bannis : le jeu (banid) ne prend que la forme STEAM_X:Y:Z et ecrit lui-meme STEAM_1 pour
# les joueurs (asw_player.cpp) ; banid refuse "[U:1:N]" et prend un SteamID64 pour un numero
# de joueur (essai du 12/10/2026). On convertit donc tout en STEAM_1:Y:Z.
steam_id() {
  local s="$1" n
  if [[ "$s" =~ ^STEAM_[0-5]:([01]):([0-9]{1,10})$ ]]; then
    echo "STEAM_1:${BASH_REMATCH[1]}:${BASH_REMATCH[2]}"
  elif [[ "$s" =~ ^\[U:1:([0-9]{1,10})\]$ ]]; then
    n="${BASH_REMATCH[1]}"; echo "STEAM_1:$((n % 2)):$((n / 2))"
  elif [[ "$s" =~ ^7656119[0-9]{10}$ ]]; then
    n=$((s - 76561197960265728)); [ "$n" -gt 0 ] && echo "STEAM_1:$((n % 2)):$((n / 2))"
  fi
}
BANS=""
for i in $(printf '%s' "$BANNIS" | tr ',;' '  '); do
  b=$(steam_id "$i")
  [ -n "$b" ] || refuser "banni '$i' : SteamID inconnu (formes acceptees : STEAM_1:0:12345, [U:1:24690] ou 76561197960290418)."
  BANS="$BANS $b"
done
# rm_welcome_message passe par un printf du jeu : % doit etre double.
ACCUEIL="${ACCUEIL//%/%%}"

# 60 -> 0.6 (part des joueurs), 100 -> 1
fraction() {
  if [ "$1" -ge 100 ]; then echo 1; else printf '0.%02d' "$1" | sed 's/0*$//'; fi
}

mkdir -p "$MOD/cfg" || exit 1
{
  echo "// server.cfg - ECRIT PAR lancer-asrd.sh a chaque demarrage, depuis les reglages d'AMP."
  echo "// Ne le modifie pas : change les reglages dans AMP, ou ajoute tes lignes dans perso.cfg."
  echo "// Lu au demarrage (+exec server.cfg) puis a chaque carte (newmapsettings.cfg) : le jeu"
  echo "// ne l'execute pas tout seul (essai du 12/10/2026)."
  echo "hostname \"$NOM\""
  echo "sv_password \"$MDP\""
  echo "rcon_password \"$RCON\""
  echo "sv_region $REGION"
  echo "sv_tags \"$TAGS\""
  echo "sv_lan 0"
  echo "sv_allow_lobby_connect_only $LOBBY"
  echo "rm_welcome_message \"$ACCUEIL\""
  echo "rm_welcome_message_delay $DELAI"
  echo "asw_skill $NIVEAU"
  echo "asw_horde_override $ONSLAUGHT"
  echo "asw_wanderer_override $ONSLAUGHT"
  # Tir ami hardcore : ce que fait le jeu quand le chef du salon le coche (cl_hardcore_ff).
  echo "asw_marine_ff_absorption $((1 - FF))"
  echo "asw_sentry_friendly_fire_scale $FF"
  echo "rd_challenge \"$DEFI\""
  echo "rd_lock_difficulty $VERROU"
  echo "rd_lock_onslaught $VERROU"
  echo "rd_lock_hardcoreff $VERROU"
  echo "rd_lock_challenge $VERROU"
  echo "asw_default_campaign \"$CAMPAGNE\""
  echo "asw_ignore_need_two_player_requirement $DEUX"
  echo "rd_kick_inactive_players $INACTIF"
  echo "rd_auto_fast_restart $ECHEC"
  echo "rd_player_bots_allowed $BOTS"
  echo "asw_vote_kick_fraction $(fraction "$VOTE_EXCL")"
  echo "asw_vote_map_fraction $(fraction "$VOTE_MISSION")"
  echo "rd_server_shutdown_after_num_secs $((VIDE * 60))"
  echo "rd_server_restart_on_update $MAJ"
  echo "sv_logecho 1"
  # Bannis d'AMP, puis ceux poses en jeu (banid + writeid -> banned_user.cfg, addip + writeip).
  for b in $BANS; do echo "banid 0 $b"; done
  echo "execifexists banned_user.cfg"
  echo "execifexists banned_ip.cfg"
  echo "exec perso.cfg"
} > "$CFG"

# Le jeu execute newmapsettings.cfg a chaque carte (CAlienSwarm::LevelInitPostEntity).
printf '%s
' "// newmapsettings.cfg - ECRIT PAR lancer-asrd.sh : remet les reglages d'AMP a chaque carte."   "exec server.cfg" > "$MOD/cfg/newmapsettings.cfg"

{
  echo "// workshop.cfg - ECRIT PAR lancer-asrd.sh : objets du Workshop choisis dans AMP."
  [ -z "$IDS" ] || echo "rd_enable_workshop_item$IDS"
} > "$WORKSHOP"

if [ ! -f "$PERSO" ]; then
  printf '%s\n' \
    "// perso.cfg - lignes en plus pour le serveur Alien Swarm: Reactive Drop, une par ligne :" \
    "//   nom_de_la_variable \"valeur\"" \
    "// Execute a la fin de server.cfg, a chaque carte. Le template ne l'ecrase jamais." \
    "// Les lignes qui commencent par // sont ignorees." > "$PERSO"
fi

# -ip 0.0.0.0 : sans lui, le RCON (TCP) n'ecoute que sur l'adresse du conteneur, pas sur
# 127.0.0.1 ou AMP le cherche. Ports client (27005) et SourceTV (27020) : le jeu ignore
# +clientport / +tv_port (lus trop tard, essai du 12/10/2026) ; SourceTV est coupe (-nohltv),
# le port client ne sert qu'aux connexions sortantes et n'a pas a etre ouvert.
ARGS="-game reactivedrop -console -condebug -nobreakpad -nohltv -ip 0.0.0.0 -port $PORT -maxplayers $JOUEURS"
[ "$VAC" = 1 ] || ARGS="$ARGS -insecure"
ARGS="$ARGS +rd_dedicated_server_language french +sv_logfile 0 +log on +exec server.cfg +map lobby"

# Utilise seulement par verifier.py : s'arrete apres avoir ecrit les fichiers.
if [ -n "$TK_ESSAI" ]; then
  echo "ARGS=$ARGS"
  exit 0
fi

echo "TeamKit : Alien Swarm: Reactive Drop, port $PORT (UDP jeu + TCP RCON), $JOUEURS joueurs, VAC $([ "$VAC" = 1 ] && echo actif || echo coupe), difficulte $NIVEAU, defi $DEFI."

# Restes d'un arret brutal (lanceur tue net) : Wine garderait le port, et l'ancien
# lecteur du journal recopierait chaque ligne une deuxieme fois.
wineserver -k > /dev/null 2>&1
pkill -x -f "tail -n +1 -F $LOGJEU" 2> /dev/null

ETAT=$(mktemp -d "$XDG_RUNTIME_DIR/asrd.XXXXXX") || exit 1
mkfifo "$ETAT/entree" || exit 1
# Le lanceur garde le tuyau ouvert en lecture-ecriture : le jeu ne voit jamais sa fin.
exec 3<> "$ETAT/entree"

ARRET=0
arreter() {
  trap - TERM INT
  ARRET=1
  echo "TeamKit : arret demande, envoi de quit au serveur."
  printf 'quit\r' >&3
}
trap arreter TERM INT

LECTEUR=""
SERVEUR=""
lancer_jeu() {
  [ ! -f "$LOGJEU" ] || mv -f "$LOGJEU" "$MOD/console.precedent.log"
  rm -f "$ETAT/pret" "$ETAT/steam" "$ETAT/carte" "$ETAT/quit"
  ( tail -n +1 -F "$LOGJEU" 2> /dev/null | lire_journal ) &
  LECTEUR=$!
  cd "$JEU" || exit 1
  echo "TeamKit : demarrage de srcds_console.exe sous Wine (sans affichage)."
  # Le jeu dessine une barre d'etat dans son terminal : elle part a la poubelle, le journal
  # complet est dans console.log.
  script -qfec "wine srcds_console.exe $ARGS" /dev/null < "$ETAT/entree" > /dev/null 2>&1 &
  SERVEUR=$!
  cd "$ICI" || exit 1
  DEBUT=$(date +%s)
  # Garde-fou : sans Steam au bout de 3 minutes, on le dit (le serveur tourne, mais
  # n'apparait pas dans la liste et refuse les joueurs en mode VAC).
  (
    for t in $(seq 1 180); do
      sleep 1
      [ -e "$ETAT/steam" ] && exit 0
      kill -0 "$SERVEUR" 2> /dev/null || exit 0
    done
    if [ -e "$ETAT/carte" ]; then
      echo "ATTENTION : pas de connexion aux serveurs Steam apres 3 minutes. Le serveur tourne mais n'est pas visible dans la liste du jeu."
      : > "$ETAT/pret"
      echo "TeamKit : serveur Alien Swarm: Reactive Drop pret (port $PORT)."
    else
      echo "ERREUR : aucune carte chargee apres 3 minutes. Dernieres lignes dans reactivedrop/console.log."
      : > "$ETAT/echec"
      kill -TERM $$ 2> /dev/null
    fi
  ) &
  GARDE=$!
}

arreter_lecteur() {
  kill "$GARDE" 2> /dev/null
  sleep 1
  pkill -P "$LECTEUR" 2> /dev/null
  kill "$LECTEUR" 2> /dev/null
}

CODE=0
while true; do
  lancer_jeu
  # Arret demande par AMP : quit, puis 20 s pour que le jeu se ferme, puis Wine coupe.
  while kill -0 "$SERVEUR" 2> /dev/null; do
    wait "$SERVEUR"
    if [ "$ARRET" = 1 ]; then
      for t in $(seq 1 20); do
        kill -0 "$SERVEUR" 2> /dev/null || break
        sleep 1
      done
      break
    fi
  done
  wineserver -k > /dev/null 2>&1
  DUREE=$(( $(date +%s) - DEBUT ))
  arreter_lecteur
  if [ "$ARRET" = 1 ]; then
    [ -e "$ETAT/echec" ] && CODE=1
    break
  fi
  if [ -e "$ETAT/maj" ]; then
    echo "TeamKit : serveur arrete pour la mise a jour du jeu. Lance Update dans AMP, puis Start."
    CODE=0
    break
  fi
  if [ -e "$ETAT/quit" ] && [ "$DUREE" -ge 120 ]; then
    echo "TeamKit : le serveur s'est arrete de lui-meme apres $((DUREE / 60)) min (redemarrage a vide ou commande quit) : relance."
    continue
  fi
  echo "ERREUR : le serveur s'est arrete au bout de $DUREE s. Dernieres lignes dans reactivedrop/console.log (et console.precedent.log)."
  CODE=1
  break
done
exec 3>&-
rm -rf "$ETAT"
exit "$CODE"
