# -*- coding: utf-8 -*-
"""
Contrôle du template avant de le pousser (même rôle que ceux de Riftbreaker et d'Alien Arena).

    python verifier.py

1. tous les JSON se parsent ;
2. le .kvp : fichiers inclus, bloc Console.* / Limits.* complet, image Wine, conteneur
   obligatoire, SteamCMD anonyme, RCON Source au mot de passe tiré par AMP, arrêt par SIGTERM,
   même dépôt que le manifest, identifiants neufs (absents des autres templates TeamKit) ;
3. le port : un seul (jeu UDP + RCON TCP), passé au lanceur avec le nombre de joueurs ;
4. chaque réglage d'AMP est dans le modèle scripts/AMP_reglages-asrd.txt (rendu par AMP en
   reglages-asrd.txt) et les clés du modèle sont exactement celles que lit le lanceur ;
5. les choix proposés (difficulté, défis, campagnes, région, cases, bornes) sont ceux qu'accepte
   le lanceur ; défis et campagnes = ceux du serveur installé le 12/10/2026 (build 25157705) ;
6. les fichiers téléchargés à l'Update existent dans scripts/, à l'URL du dépôt du manifest ;
7. les scripts : LF, ASCII, aucun {{, `bash -n` ;
8. aller-retour par le VRAI lanceur sous bash (Wine remplacé par des bouchons) : rendu des
   réglages comme AMP (remplacement brut), écriture de server.cfg, relecture comme le moteur
   Source (une commande par ligne, tout en ASCII) ; défauts, textes piégés, bannis, Workshop,
   refus clairs ;
9. le filtre de journal du lanceur sur de vraies lignes du serveur (12/10/2026) : bruit retiré,
   ligne « prêt » une fois, rechargement pour le défi, arrivées / départs / chat ;
10. les regex de console d'AMP.
"""
import glob
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ICI = os.path.dirname(os.path.abspath(__file__))
NOM = 'asrd'
MODELE = 'scripts/AMP_reglages-asrd.txt'
LANCEUR = 'scripts/lancer-asrd.sh'
soucis = []


def lire(nom, binaire=False):
    with open(os.path.join(ICI, nom), 'rb') as f:
        brut = f.read()
    return brut if binaire else brut.decode('utf-8')


def ok(quoi, detail):
    print('ok   %-26s %s' % (quoi, detail))


def py(motif):
    # AMP est en C# : (?<nom>...) ; Python veut (?P<nom>...)
    return re.compile(motif.replace('(?<', '(?P<'))


# ── 1. JSON ──────────────────────────────────────────────────────────────────
data = {}
for nom in ('manifest.json', NOM + 'config.json', NOM + 'metaconfig.json', NOM + 'ports.json', NOM + 'updates.json'):
    try:
        data[nom] = json.loads(lire(nom))
        ok(nom, 'JSON valide')
    except Exception as e:
        soucis.append('%s : JSON invalide (%s)' % (nom, e))
if soucis:
    print('\n'.join('NON  ' + s for s in soucis))
    sys.exit(1)
config = data[NOM + 'config.json']
updates = data[NOM + 'updates.json']
ports = data[NOM + 'ports.json']
manifest = data['manifest.json']
lanceur = lire(LANCEUR)
modele = lire(MODELE)

# ── 2. kvp ───────────────────────────────────────────────────────────────────
kvp = lire(NOM + '.kvp')
cles = dict(l.split('=', 1) for l in kvp.splitlines() if '=' in l)
for ref in re.findall(r'@IncludeJson\[([^\]]+)\]', kvp):
    if not os.path.isfile(os.path.join(ICI, ref)):
        soucis.append('@IncludeJson[%s] : fichier absent' % ref)
for cle in ('Meta.ConfigManifest', 'Meta.MetaConfigManifest', 'Meta.ConfigRoot'):
    if not os.path.isfile(os.path.join(ICI, cles.get(cle, '?'))):
        soucis.append('%s pointe sur un fichier absent' % cle)
ATTENDUES = ['App.SupportsUniversalSleep', 'App.WakeupMode', 'App.ApplicationReadyMode', 'Console.FilterMatchRegex',
             'Console.FilterMatchReplacement', 'Console.ThrowawayMessageRegex', 'Console.AppReadyRegex',
             'Console.UserJoinRegex', 'Console.UserLeaveRegex', 'Console.UserChatRegex', 'Console.UpdateAvailableRegex',
             'Console.PreConnectRegex', 'Console.ConnectIPRegex', 'Console.MetricsRegex', 'Console.HideFromConsoleRegex',
             'Console.SuppressLogAtStart', 'Console.UserActions', 'Limits.SleepMode', 'Limits.SleepOnStart',
             'Limits.SleepDelayMinutes', 'Limits.DozeDelay', 'Limits.AutoRetryCount', 'Limits.SleepStartThresholdSeconds']
absentes = [c for c in ATTENDUES if c not in cles]
if absentes:
    soucis.append('clés absentes du .kvp : ' + ', '.join(absentes))
else:
    ok('kvp complet', 'les %d clés Console/Limits sont là' % len(ATTENDUES))
ATTENDU_KVP = {
    'Meta.SpecificDockerImage': 'cubecoders/ampbase:wine-stable',  # serveur Windows seulement
    'Meta.ContainerPolicy': 'Required',
    'Meta.DockerRequired': 'True',
    'Meta.DisplayImageSource': 'steam:563560',
    'App.SteamUpdateAnonymousLogin': 'True',
    'App.SteamForceLoginPrompt': 'False',
    'App.ExecutableLinux': '/bin/bash',
    'App.ExitMethod': 'SIGTERM',               # le lanceur envoie quit au jeu puis coupe Wine
    'App.HasReadableConsole': 'True',
    'App.HasWriteableConsole': 'False',        # les commandes passent par le RCON
    'App.AdminMethod': 'SourceRCON',
    'App.AdminPortRef': 'GamePort',
    'App.UseRandomAdminPassword': 'True',      # aucun mot de passe en dur
    'App.PersistRandomPassword': 'True',
    'App.IgnoreSTDOUTAfterRCON': 'False',      # la console lit toujours le journal
    'App.ApplicationReadyMode': 'RegexMatch',
    'App.BaseDirectory': './asrd/582400/',
    'App.RootDir': './asrd/',
    'App.MaxUsers': '8',
    'App.CommandLineArgs': '"{{$FullRootDir}}lancer-asrd.sh" {{$GamePort}} {{$MaxUsers}}',
    'Limits.SleepMode': 'False',
}
for cle, val in ATTENDU_KVP.items():
    if cles.get(cle) != val:
        soucis.append('%s devrait valoir %s (vaut %r)' % (cle, val, cles.get(cle)))
if cles.get('Meta.URL') != manifest['url'] or manifest['origin'] != manifest['url'] + '.git':
    soucis.append('Meta.URL et manifest.json ne désignent pas le même dépôt')
if manifest.get('authors') != ['Hydrocut', 'TeamKit'] or not manifest.get('prefix', '').startswith('TeamKit'):
    soucis.append('manifest : auteurs Hydrocut + TeamKit, prefix TeamKit…')
# identifiants neufs : ni l'AppConfigId ni l'id du manifest ne doivent exister ailleurs
autres = [p for p in glob.glob(os.path.join(ICI, '..', 'AMPTemplates-*', '*'))
          if os.path.abspath(os.path.dirname(p)) != ICI and p.endswith(('.kvp', 'manifest.json'))]
deja = ''
for p in autres:
    if os.path.isfile(p):
        deja += io.open(p, encoding='utf-8', errors='replace').read()
for quoi, val in (('Meta.AppConfigId', cles.get('Meta.AppConfigId', '')), ('id du manifest', manifest['id'])):
    if not re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}', val):
        soucis.append('%s : UUID v4 attendu (%r)' % (quoi, val))
    elif val in deja:
        soucis.append('%s déjà utilisé par un autre template TeamKit' % quoi)
# Greelan : AppConfigId 25acbd1f-... ; le nôtre doit en différer pour coexister dans ADS
if cles.get('Meta.AppConfigId') == '25acbd1f-66d9-4c22-9c80-eeec416e8a24':
    soucis.append('AppConfigId identique au template communautaire de Greelan')
ok('kvp', 'Wine, conteneur obligatoire, SteamCMD anonyme, RCON aléatoire, %d autres templates lus' % len(autres))

# ── 3. port ──────────────────────────────────────────────────────────────────
if (len(ports) != 1 or ports[0]['Protocol'] != 'Both' or ports[0]['Ref'] != 'GamePort'
        or cles.get('App.PrimaryApplicationPortRef') != 'GamePort' or ports[0]['Port'] != 27015):
    soucis.append('port : un seul, GamePort 27015 en Both (UDP jeu + TCP RCON)')
else:
    ok('port', '27015 UDP+TCP, réglable, passé au lanceur')

# ── 4. réglages <-> modèle <-> lanceur ───────────────────────────────────────
par_nom = {c['ParamFieldName']: c for c in config}
if len(par_nom) != len(config) or len({c['FieldName'] for c in config}) != len(config):
    soucis.append('réglages en double')
dans_modele = re.findall(r'\{\{([A-Za-z0-9_$]+)\}\}', modele)
for c in config:
    if c.get('IncludeInCommandLine') is not False:
        soucis.append('%s : IncludeInCommandLine doit être false' % c['FieldName'])
    if c['FieldName'] == '$MaxUsers':
        if c['ParamFieldName'] in dans_modele:
            soucis.append('$MaxUsers passe par la ligne de commande, pas par le modèle')
        continue
    if c['FieldName'] != c['ParamFieldName'] and c['FieldName'] != '$RemoteAdminPassword':
        soucis.append('%s : FieldName et ParamFieldName différents' % c['FieldName'])
    if dans_modele.count(c['ParamFieldName']) != 1:
        soucis.append('{{%s}} doit apparaître une fois dans %s' % (c['ParamFieldName'], MODELE))
for x in set(dans_modele) - set(par_nom):
    soucis.append('{{%s}} dans le modèle sans réglage dans AMP' % x)
cles_modele = {}
for l in modele.splitlines():
    if l.startswith('#') or not l.strip():
        continue
    r = re.fullmatch(r'([a-z_]+)=\{\{([A-Za-z0-9_]+)\}\}', l)
    if not r:
        soucis.append('ligne du modèle inattendue : %s' % l)
        continue
    cles_modele[r.group(1)] = r.group(2)
lues = set(re.findall(r'\$\{R\[(\w+)\]', lanceur))
if set(cles_modele) != lues:
    soucis.append('clés du modèle %s ≠ clés lues par le lanceur %s' % (sorted(set(cles_modele) ^ lues), ''))
meta = data[NOM + 'metaconfig.json']
if (len(meta) != 1 or meta[0].get('ConfigType') != 'template' or meta[0].get('ConfigFile') != 'reglages-asrd.txt'
        or meta[0].get('ConfigFileTemplate') != 'asrd/AMP_reglages-asrd.txt'):
    soucis.append('metaconfig : template asrd/AMP_reglages-asrd.txt -> reglages-asrd.txt (dossier 582400/)')
if 'REGLAGES="$JEU/reglages-asrd.txt"' not in lanceur:
    soucis.append('le lanceur ne lit pas le fichier rendu par AMP (582400/reglages-asrd.txt)')
if par_nom['MotDePasseRcon']['FieldName'] != '$RemoteAdminPassword' or not par_nom['MotDePasseRcon'].get('Hidden'):
    soucis.append('le mot de passe RCON doit être $RemoteAdminPassword (tiré par AMP), caché')
if not [s for s in soucis if 'modèle' in s or 'réglage' in s]:
    ok('réglages', '%d réglages, modèle et lanceur d’accord' % len(config))


# ── 5. choix proposés <-> lanceur <-> serveur installé ───────────────────────
def motif(variable):
    r = re.search(r'\[\[ "\$%s" =~ \^\(([-A-Za-z0-9_|]+)\)\$ \]\]' % variable, lanceur)
    return set(r.group(1).split('|')) if r else None


# Relevés dans reactivedrop/resource/ du serveur installé (12/10/2026) : défis dont
# allowed_mode permet la coopération, campagnes de resource/campaigns/.
DEFIS = {'0', 'asbi', 'difficulty_tier1', 'difficulty_tier2', 'energy_weapons', 'level_one', 'one_hit',
         'rd_first_person', 'rd_third_person', 'riflemod_classic', 'traitors'}
CAMPAGNES = {'jacob', 'rd-area9800', 'rd-operationcleansweep', 'rd-tarnorcampaign1', 'rd_accident32',
             'rd_biogen_corporation', 'rd_lanasescape_campaign', 'rd_nh_campaigns', 'rd_paranoia',
             'rd_reduction_campaign', 'rd_research7', 'tilarus5'}
for champ, attendu, du_lanceur in (('Defi', DEFIS, motif('DEFI')), ('Campagne', CAMPAGNES, motif('CAMPAGNE')),
                                   ('Region', {'-1', '0', '1', '2', '3', '4', '5', '6', '7', '255'}, motif('REGION'))):
    c = par_nom[champ]
    if set(c['EnumValues']) != attendu or du_lanceur != attendu:
        soucis.append('%s : AMP %s, lanceur %s, attendu %s' % (champ, sorted(c['EnumValues']), sorted(du_lanceur or []), sorted(attendu)))
    if c['DefaultValue'] not in c['EnumValues']:
        soucis.append('%s : valeur par défaut hors liste' % champ)
if set(par_nom['Difficulte']['EnumValues']) != {'1', '2', '3', '4', '5'} or '[[ "$NIVEAU" =~ ^[1-5]$ ]]' not in lanceur:
    soucis.append('Difficulte : 1 à 5 (asw_skill, « Game skill level (1-5) »)')
cases = [c for c in config if c['InputType'] == 'checkbox']
for c in cases:
    if c['EnumValues'] != {'False': '0', 'True': '1'} or c['DefaultValue'] not in ('0', '1'):
        soucis.append('%s : case à cocher 0/1' % c['ParamFieldName'])
BORNES = {'$MaxUsers': ('1', '8'), 'Inactifs': ('0', '3600'), 'RedemarrageVide': ('0', '10080'),
          'DelaiAccueil': ('0', '30'), 'VoteExclusion': ('1', '100'), 'VoteMission': ('1', '100')}
for c in config:
    if c['InputType'] == 'number':
        b = BORNES.get(c['FieldName'])
        if (c.get('MinValue'), c.get('MaxValue')) != b:
            soucis.append('%s : bornes %s-%s, attendu %s' % (c['FieldName'], c.get('MinValue'), c.get('MaxValue'), b))
if par_nom['JoueursMax']['DefaultValue'] != cles.get('App.MaxUsers'):
    soucis.append('App.MaxUsers doit valoir le défaut de « Joueurs maximum »')
DEFAUTS_TK = {'NomServeur': '[FR] TeamKit - Alien Swarm: Reactive Drop', 'Region': '3', 'Tags': 'fr,teamkit',
              'Vac': '1', 'LobbySeulement': '0', 'Difficulte': '2', 'Defi': '0', 'Campagne': 'jacob'}
for k, v in DEFAUTS_TK.items():
    if par_nom[k]['DefaultValue'] != v:
        soucis.append('défaut TeamKit : %s devrait valoir %r' % (k, v))
if 'discord.gg/EuAjGMYPHY' not in par_nom['MessageAccueil']['DefaultValue']:
    soucis.append('le message d’accueil par défaut doit donner le Discord TeamKit')
ok('choix', 'difficulté, %d défis, %d campagnes, régions, %d cases, bornes' % (len(DEFIS), len(CAMPAGNES), len(cases)))

# ── 6. Update ────────────────────────────────────────────────────────────────
depot = manifest['url'].replace('https://github.com/', '')
fetch = [e for e in updates if e['UpdateSource'] == 'FetchURL']
for e in fetch:
    attendu = 'https://raw.githubusercontent.com/%s/main/scripts/%s' % (depot, e['UpdateSourceArgs'])
    if e['UpdateSourceData'] != attendu:
        soucis.append('URL inattendue pour %s : %s' % (e['UpdateSourceArgs'], e['UpdateSourceData']))
    elif not os.path.isfile(os.path.join(ICI, 'scripts', e['UpdateSourceArgs'])):
        soucis.append('scripts/%s absent du dépôt' % e['UpdateSourceArgs'])
    elif e.get('UpdateSourceTarget') != '{{$FullRootDir}}' or e.get('OverwriteExistingFiles') is not True:
        soucis.append('%s : doit être réécrit dans {{$FullRootDir}} à chaque Update' % e['UpdateSourceArgs'])
if {e['UpdateSourceArgs'] for e in fetch} != {'AMP_reglages-asrd.txt', 'lancer-asrd.sh'}:
    soucis.append('l’Update doit déposer AMP_reglages-asrd.txt et lancer-asrd.sh')
st = [e for e in updates if e['UpdateSource'] == 'SteamCMD']
if (len(st) != 1 or st[0]['UpdateSourceData'] != '582400' or st[0].get('UpdateSourceArgs') != '563560'
        or st[0].get('ForceDownloadPlatform') != 'Windows' or updates[0] is not st[0]):
    soucis.append('étape SteamCMD : la première, app 582400 (jeu 563560), ForceDownloadPlatform Windows')
if updates[-1].get('UpdateSourceArgs') != '"{{$FullRootDir}}lancer-asrd.sh" preparer':
    soucis.append('la dernière étape doit être « lancer-asrd.sh preparer »')
if not [s for s in soucis if 'Update' in s or 'URL' in s or 'SteamCMD' in s]:
    ok('Update', 'SteamCMD 582400 (Windows), 2 fichiers du dépôt, préfixe Wine')

# ── 7. scripts ───────────────────────────────────────────────────────────────
for nom in (LANCEUR, MODELE):
    brut = lire(nom, binaire=True)
    if b'\r' in brut:
        soucis.append('%s : fins de ligne Windows (CRLF)' % nom)
    if any(o > 127 for o in brut):
        soucis.append('%s : caractères non ASCII' % nom)
if '{{' in lanceur:
    soucis.append('le lanceur contient {{ : AMP pourrait le remplacer')
for besoin, pourquoi in [
    ('script -qfec "wine srcds_console.exe $ARGS"', 'pseudo-terminal : sans lui la console Windows du jeu s’arrête'),
    ('-ip 0.0.0.0', 'sans lui le RCON n’écoute pas sur 127.0.0.1'),
    ('-condebug', 'journal du jeu dans console.log'),
    ('+exec server.cfg', 'le jeu n’exécute pas server.cfg tout seul'),
    ('"exec server.cfg" > "$MOD/cfg/newmapsettings.cfg"', 'réglages remis à chaque carte'),
    ('+log on', 'arrivées, départs et chat dans le journal'),
    ('-nohltv', 'SourceTV coupé (son port ne se règle pas)'),
    ('wineserver -k', 'arrêt et nettoyage des restes de Wine'),
    ('trap arreter TERM INT', 'arrêt demandé par AMP'),
    ("printf 'quit\\r' >&3", 'arrêt propre par la console du jeu'),
]:
    if besoin not in lanceur:
        soucis.append('lanceur : %s (%s)' % (besoin, pourquoi))
if '-insecure' in re.search(r'^ARGS="-game[^"]*"', lanceur, re.M).group(0):
    soucis.append('-insecure ne doit être ajouté que si VAC est décoché')


def trouver_bash():
    for c in (r'C:\Program Files\Git\bin\bash.exe', r'C:\Program Files\Git\usr\bin\bash.exe', '/bin/bash'):
        if os.path.isfile(c):
            return c
    c = shutil.which('bash')
    if c and 'system32' not in c.lower():   # le bash de WSL ne verrait pas les chemins Windows
        return c
    return None


bash = trouver_bash()
if bash:
    r = subprocess.run([bash, '-n', os.path.join(ICI, LANCEUR)], capture_output=True, text=True)
    if r.returncode:
        soucis.append('bash -n : %s' % r.stderr.strip())
    else:
        ok('bash -n', LANCEUR)


# ── 8. aller-retour par le vrai lanceur ──────────────────────────────────────
def lire_cfg(texte):
    # Comme le moteur Source : une commande par ligne, // = commentaire ; le dernier gagne.
    # Le moteur lit octet par octet : tout doit être ASCII (essai du 12/10/2026).
    v, bans = {}, []
    for l in texte.splitlines():
        l = l.strip()
        if not l or l.startswith('//'):
            continue
        if any(ord(c) > 126 or ord(c) < 32 for c in l):
            raise ValueError('ligne non ASCII : %r' % l)
        r = re.fullmatch(r'(\w+) "([^";]*)"', l) or re.fullmatch(r'(\w+) (-?[0-9.]+)', l)
        if r:
            v[r.group(1)] = r.group(2)
            continue
        r = re.fullmatch(r'banid 0 (STEAM_1:[01]:\d+)', l)
        if r:
            bans.append(r.group(1))
            continue
        r = re.fullmatch(r'(execifexists|exec) ([\w.]+)', l)
        if r:
            v.setdefault('#exec', []).append(r.group(2))
            continue
        r = re.fullmatch(r'rd_enable_workshop_item((?: \d+)+)', l)
        if r:
            v['#workshop'] = r.group(1).split()
            continue
        raise ValueError('ligne illisible pour le jeu : %r' % l)
    v['#bans'] = bans
    return v


DEFAUTS = {c['ParamFieldName']: str(c.get('DefaultValue', '')) for c in config}
DEFAUTS['MotDePasseRcon'] = 'Rc0nAleatoire42'   # AMP le tire au hasard

if not bash:
    print('---  aller-retour              bash introuvable : étape 8 sautée (à faire avant de pousser)')
else:
    with tempfile.TemporaryDirectory() as tmp:
        racine = os.path.join(tmp, 'asrd')
        os.makedirs(os.path.join(racine, '582400', 'reactivedrop', 'cfg'))
        os.makedirs(os.path.join(racine, '.wine'))
        open(os.path.join(racine, '.wine', 'system.reg'), 'w').close()
        open(os.path.join(racine, '582400', 'srcds_console.exe'), 'w').close()
        shutil.copy(os.path.join(ICI, LANCEUR), racine)
        bouchons = os.path.join(tmp, 'bouchons')
        os.makedirs(bouchons)
        for b in ('wine', 'wineserver', 'script'):
            with open(os.path.join(bouchons, b), 'w', newline='\n') as f:
                f.write('#!/bin/bash\nexit 0\n')
        env = dict(os.environ, TK_ESSAI='1')
        if os.name == 'nt':
            env['PATH'] = '/' + bouchons[0].lower() + bouchons[2:].replace('\\', '/') + ':/usr/bin:/bin'
        else:
            env['PATH'] = bouchons + os.pathsep + env.get('PATH', '')
        lanceur_tmp = os.path.join(racine, 'lancer-asrd.sh').replace('\\', '/')
        cfgdir = os.path.join(racine, '582400', 'reactivedrop', 'cfg')

        def lancer(change, port='27015', joueurs='8'):
            v = dict(DEFAUTS, **change)
            t = modele
            for k, x in v.items():
                t = t.replace('{{%s}}' % k, x)       # AMP : remplacement brut
            with open(os.path.join(racine, '582400', 'reglages-asrd.txt'), 'w', encoding='utf-8', newline='\n') as f:
                f.write(t)
            for f in glob.glob(os.path.join(cfgdir, '*.cfg')):
                if not f.endswith('perso.cfg'):
                    os.remove(f)
            p = subprocess.run([bash, lanceur_tmp, port, joueurs], env=env, capture_output=True, timeout=120)
            sortie = p.stdout.decode('utf-8', 'replace') + p.stderr.decode('utf-8', 'replace')
            lu = None
            if os.path.exists(os.path.join(cfgdir, 'server.cfg')):
                lu = lire_cfg(io.open(os.path.join(cfgdir, 'server.cfg'), encoding='utf-8', errors='replace').read())
                ws = lire_cfg(io.open(os.path.join(cfgdir, 'workshop.cfg'), encoding='utf-8').read())
                lu['#workshop'] = ws.get('#workshop', [])
                nm = io.open(os.path.join(cfgdir, 'newmapsettings.cfg'), encoding='utf-8').read()
                lu['#newmap'] = lire_cfg(nm).get('#exec')
            args = re.search(r'^ARGS=(.*)$', sortie, re.M)
            return p.returncode, sortie, lu, args.group(1).split() if args else []

        n = 0

        def cas(titre, change, code_attendu, attendu=None, dans_args=(), hors_args=(), bans=None, ws=None,
                port='27015', joueurs='8'):
            global n
            n += 1
            try:
                code, sortie, lu, args = lancer(change, port, joueurs)
            except ValueError as e:
                soucis.append('aller-retour « %s » : %s' % (titre, e))
                return
            if code != code_attendu:
                soucis.append('aller-retour « %s » : code %s au lieu de %s\n%s' % (titre, code, code_attendu, sortie))
                return
            if code_attendu == 1:
                if 'ERREUR' not in sortie or lu is not None:
                    soucis.append('aller-retour « %s » : refus sans message clair, ou server.cfg écrit quand même' % titre)
                return
            for k, x in (attendu or {}).items():
                if lu.get(k) != x:
                    soucis.append('aller-retour « %s » : %s = %r au lieu de %r' % (titre, k, lu.get(k), x))
            for a in dans_args:
                if a not in args:
                    soucis.append('aller-retour « %s » : %s absent de la ligne de lancement %s' % (titre, a, args))
            for a in hors_args:
                if a in args:
                    soucis.append('aller-retour « %s » : %s ne devrait pas être sur la ligne de lancement' % (titre, a))
            if bans is not None and lu['#bans'] != bans:
                soucis.append('aller-retour « %s » : bannis %s au lieu de %s' % (titre, lu['#bans'], bans))
            if ws is not None and lu['#workshop'] != ws:
                soucis.append('aller-retour « %s » : Workshop %s au lieu de %s' % (titre, lu['#workshop'], ws))
            if lu['#newmap'] != ['server.cfg'] or lu['#exec'][-1] != 'perso.cfg':
                soucis.append('aller-retour « %s » : newmapsettings.cfg / perso.cfg' % titre)

        cas('défauts TeamKit', {}, 0, {
            'hostname': '[FR] TeamKit - Alien Swarm: Reactive Drop', 'sv_password': '', 'rcon_password': 'Rc0nAleatoire42',
            'sv_region': '3', 'sv_tags': 'fr,teamkit', 'sv_allow_lobby_connect_only': '0', 'asw_skill': '2',
            'asw_horde_override': '0', 'asw_wanderer_override': '0', 'asw_marine_ff_absorption': '1',
            'asw_sentry_friendly_fire_scale': '0', 'rd_challenge': '0', 'rd_lock_difficulty': '0',
            'asw_default_campaign': 'jacob', 'rd_server_shutdown_after_num_secs': '3600',
            'rd_server_restart_on_update': '1', 'asw_vote_kick_fraction': '0.6', 'asw_vote_map_fraction': '0.6',
            'rm_welcome_message_delay': '10', 'rd_player_bots_allowed': '1', 'rd_auto_fast_restart': '0',
            'rm_welcome_message': 'Bienvenue sur le serveur TeamKit ! Hebergement gratuit : teamkit.fr - Discord : discord.gg/EuAjGMYPHY'},
            dans_args=['-port', '27015', '-maxplayers', '8', '-ip', '0.0.0.0', '-nohltv', '+map', 'lobby'],
            hors_args=['-insecure'], bans=[], ws=[])
        cas('textes piégés', {'NomServeur': '[FR] TeamKit – été ; // « test » 🚀 "ok" Œuvre',
                              'MessageAccueil': 'Salut ! 100 % gratuit ; l’équipe…', 'Tags': 'fr ,été'}, 0,
            {'hostname': "[FR] TeamKit - ete , // ' test ' 'ok' OEuvre",
             'rm_welcome_message': "Salut ! 100 %% gratuit , l'equipe...", 'sv_tags': 'fr ,ete'})
        cas('nom vide', {'NomServeur': '  '}, 0, {'hostname': '[FR] TeamKit - Alien Swarm: Reactive Drop'})
        cas('partie corsée', {'Difficulte': '5', 'Onslaught': '1', 'TirAmiHardcore': '1', 'Defi': 'one_hit',
                              'Verrouiller': '1', 'Campagne': 'rd_research7', 'MotDePasse': 'essai123',
                              'VoteExclusion': '75', 'VoteMission': '5', 'Inactifs': '300'}, 0,
            {'asw_skill': '5', 'asw_horde_override': '1', 'asw_wanderer_override': '1', 'asw_marine_ff_absorption': '0',
             'asw_sentry_friendly_fire_scale': '1', 'rd_challenge': 'one_hit', 'rd_lock_challenge': '1',
             'rd_lock_hardcoreff': '1', 'asw_default_campaign': 'rd_research7', 'sv_password': 'essai123',
             'asw_vote_kick_fraction': '0.75', 'asw_vote_map_fraction': '0.05', 'rd_kick_inactive_players': '300'})
        cas('défi du Workshop', {'Defi': 'asbi', 'DefiAutre': 'mon_defi-2'}, 0, {'rd_challenge': 'mon_defi-2'})
        cas('VAC coupé, 4 joueurs, autre port', {'Vac': '0', 'VoteMission': '100'}, 0, {'asw_vote_map_fraction': '1'},
            dans_args=['-insecure', '-port', '27215', '-maxplayers', '4'], port='27215', joueurs='4')
        cas('bannis sous trois formes', {'Bannis': 'STEAM_0:1:111, [U:1:24692];76561197960290418'}, 0,
            bans=['STEAM_1:1:111', 'STEAM_1:0:12346', 'STEAM_1:0:12345'])
        cas('Workshop', {'Workshop': '1093180806, 2000000001'}, 0, ws=['1093180806', '2000000001'])
        cas('jamais de redémarrage à vide', {'RedemarrageVide': '0', 'ArretMaj': '0'}, 0,
            {'rd_server_shutdown_after_num_secs': '0', 'rd_server_restart_on_update': '0'})
        cas('9 joueurs', {}, 1, joueurs='9')
        cas('port 80', {}, 1, port='80')
        cas('mot de passe accentué', {'MotDePasse': 'été'}, 1)
        cas('mot de passe à guillemet', {'MotDePasse': 'a"b'}, 1)
        cas('défi inconnu', {'Defi': 'nimporte'}, 1)
        cas('défi du Workshop invalide', {'DefiAutre': 'a b'}, 1)
        cas('banni invalide', {'Bannis': 'Kevin'}, 1)
        cas('Workshop invalide', {'Workshop': 'https://steamcommunity.com/x'}, 1)
        cas('difficulté 6', {'Difficulte': '6'}, 1)
        cas('vote à 0 %', {'VoteExclusion': '0'}, 1)
        with open(os.path.join(cfgdir, 'perso.cfg'), 'a', encoding='utf-8', newline='\n') as f:
            f.write('sv_steamgroup 123\n')
        if 'sv_steamgroup' not in io.open(os.path.join(cfgdir, 'perso.cfg'), encoding='utf-8').read():
            soucis.append('perso.cfg')
        cas('perso.cfg gardé', {}, 0)
        if 'sv_steamgroup 123' not in io.open(os.path.join(cfgdir, 'perso.cfg'), encoding='utf-8').read():
            soucis.append('aller-retour : perso.cfg a été écrasé')
        if not [s for s in soucis if s.startswith('aller-retour')]:
            ok('aller-retour', '%d cas par le vrai lanceur (bash), dont 10 refus' % n)

# ── 9. filtre de journal sur de vraies lignes (12/10/2026, build 25157705) ────
# Lignes relevées dans reactivedrop/console.log ; les quatre lignes de joueur humain
# (Kevin) ont la forme exacte des lignes SourceTV / Console relevées, avec un SteamID :
# aucun vrai joueur n'a pu se connecter pendant l'essai.
JOURNAL = r'''NET_GetBindAddresses found 172.17.0.34: 'eth0'
Network: IP 0.0.0.0, mode MP, dedicated Yes, ports 27215 SV / 27006 CL
Server is hibernating
maxplayers set to 8
Cannot access ISteamInventory!
Server logging enabled.
L 10/12/2026 - 20:15:13: server_cvar: "sv_tags" "fr,teamkit"
Unknown command "mat_do_not_shrink_dynamic_vb"
---- Host_NewGame ----
L 10/12/2026 - 20:15:13: Loading map "lobby"
L 10/12/2026 - 20:15:13: server cvars start
L 10/12/2026 - 19:45:46: "sv_cheats" = "0"
L 10/12/2026 - 19:45:46: "r_AirboatViewDampenFreq" = "7.0"
L 10/12/2026 - 20:15:13: server cvars end
L 10/12/2026 - 20:15:13: Started map "lobby" (CRC "-1874936839")
Host_NewGame on map lobby
Unqualified = rd_research7_save_126_09_12_20_15_14.campaignsave
Creating new save with filename: save/rd_research7_save_126_09_12_20_15_14.campaignsave
New save created: save/rd_research7_save_126_09_12_20_15_14.campaignsave
---- Host_Changelevel ----
L 10/12/2026 - 20:15:14: Loading map "rd-res1forestentrance"
L 10/12/2026 - 20:15:14: Started map "rd-res1forestentrance" (CRC "1229901337")
-- Error --:  empty soundname, .qc error on AE_CL_PLAYSOUND in model aliens/drone/drone.mdl, sequence Jump_Glide, animevent # 1
Connection to Steam servers successful.
   VAC secure mode is activated.
---- Host_Changelevel ----
L 10/12/2026 - 20:15:16: Started map "rd-res1forestentrance" (CRC "1229901337")
Connection to Steam servers successful.
L 10/12/2026 - 19:45:47: "SourceTV<2><BOT><>" connected, address "none"
L 10/12/2026 - 19:45:47: "SourceTV<2><BOT><>" entered the game
L 10/12/2026 - 19:54:07: rcon from "127.0.0.1:41408": command "status"
L 10/12/2026 - 19:54:10: "Console<0><Console><Console>" say "Test RCON TeamKit"
L 10/12/2026 - 21:00:01: "Kevin [FR]<3><STEAM_1:0:12345><>" connected, address "203.0.113.5:27005"
L 10/12/2026 - 21:00:05: "Kevin [FR]<3><STEAM_1:0:12345><>" entered the game
L 10/12/2026 - 21:00:09: "Kevin [FR]<3><STEAM_1:0:12345><>" say "salut : "on" y va ?"
L 10/12/2026 - 21:00:10: "Kevin [FR]<3><STEAM_1:0:12345><>" say_team "go"
L 10/12/2026 - 21:05:00: "Kevin [FR]<3><STEAM_1:0:12345><>" disconnected (reason "Disconnect")
L 10/12/2026 - 20:00:00: "SourceTV<2><BOT><>" disconnected (reason "Server shutting down")
Server is hibernating
L 10/12/2026 - 21:05:06: Started map "rd-res1forestentrance" (CRC "1229901337")
L 10/12/2026 - 20:08:41: server_message: "quit"
'''
ATTENDU_FILTRE = [
    "NET_GetBindAddresses found 172.17.0.34: 'eth0'",
    'Network: IP 0.0.0.0, mode MP, dedicated Yes, ports 27215 SV / 27006 CL',
    'Server is hibernating',
    'maxplayers set to 8',
    'Server logging enabled.',
    'L 10/12/2026 - 20:15:13: server_cvar: "sv_tags" "fr,teamkit"',
    '---- Host_NewGame ----',
    'L 10/12/2026 - 20:15:13: Loading map "lobby"',
    'L 10/12/2026 - 20:15:13: Started map "lobby" (CRC "-1874936839")',
    'Host_NewGame on map lobby',
    'Creating new save with filename: save/rd_research7_save_126_09_12_20_15_14.campaignsave',
    'New save created: save/rd_research7_save_126_09_12_20_15_14.campaignsave',
    '---- Host_Changelevel ----',
    'L 10/12/2026 - 20:15:14: Loading map "rd-res1forestentrance"',
    'L 10/12/2026 - 20:15:14: Started map "rd-res1forestentrance" (CRC "1229901337")',
    'TeamKit : serveur vide, rechargement de rd-res1forestentrance pour activer le defi one_hit.',
    '(console du jeu) changelevel rd-res1forestentrance',
    'Connection to Steam servers successful.',
    'TeamKit : serveur Alien Swarm: Reactive Drop pret (port 27215).',
    '   VAC secure mode is activated.',
    '---- Host_Changelevel ----',
    'L 10/12/2026 - 20:15:16: Started map "rd-res1forestentrance" (CRC "1229901337")',
    'Connection to Steam servers successful.',
    'L 10/12/2026 - 19:45:47: "SourceTV<2><BOT><>" connected, address "none"',
    'L 10/12/2026 - 19:45:47: "SourceTV<2><BOT><>" entered the game',
    'L 10/12/2026 - 19:54:07: rcon from "127.0.0.1:41408": command "status"',
    'L 10/12/2026 - 19:54:10: "Console<0><Console><Console>" say "Test RCON TeamKit"',
    'L 10/12/2026 - 21:00:01: "Kevin [FR]<3><STEAM_1:0:12345><>" connected, address "203.0.113.5:27005"',
    'L 10/12/2026 - 21:00:05: "Kevin [FR]<3><STEAM_1:0:12345><>" entered the game',
    'TeamKit : Kevin [FR] a rejoint la partie (SteamID STEAM_1:0:12345).',
    'L 10/12/2026 - 21:00:09: "Kevin [FR]<3><STEAM_1:0:12345><>" say "salut : "on" y va ?"',
    '[Chat] Kevin [FR] : salut : "on" y va ?',
    'L 10/12/2026 - 21:00:10: "Kevin [FR]<3><STEAM_1:0:12345><>" say_team "go"',
    '[Chat] Kevin [FR] : go',
    'L 10/12/2026 - 21:05:00: "Kevin [FR]<3><STEAM_1:0:12345><>" disconnected (reason "Disconnect")',
    'TeamKit : Kevin [FR] a quitte la partie (SteamID STEAM_1:0:12345).',
    'L 10/12/2026 - 20:00:00: "SourceTV<2><BOT><>" disconnected (reason "Server shutting down")',
    'Server is hibernating',
    'L 10/12/2026 - 21:05:06: Started map "rd-res1forestentrance" (CRC "1229901337")',
    'TeamKit : serveur vide, rechargement de rd-res1forestentrance pour activer le defi one_hit.',
    '(console du jeu) changelevel rd-res1forestentrance',
    'L 10/12/2026 - 20:08:41: server_message: "quit"',
]
obtenu = []
if bash:
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copy(os.path.join(ICI, LANCEUR), tmp)
        p = subprocess.run([bash, os.path.join(tmp, 'lancer-asrd.sh').replace('\\', '/'), 'filtre', '27215', 'one_hit'],
                           input=JOURNAL.replace('\n', '\r\n').encode('utf-8'), capture_output=True, timeout=60)
        obtenu = p.stdout.decode('utf-8').split('\n')[:-1]
        if obtenu != ATTENDU_FILTRE:
            diff = [(i, a, b) for i, (a, b) in enumerate(zip(obtenu + [''] * 99, ATTENDU_FILTRE + [''] * 99)) if a != b][:3]
            soucis.append('filtre du journal : premières différences %s\n%s' % (diff, p.stderr.decode('utf-8', 'replace')))
        else:
            ok('filtre du journal', '%d lignes réelles, %d gardées, « prêt » une fois, défi rechargé deux fois'
               % (JOURNAL.count('\n'), len(ATTENDU_FILTRE)))
        # sans défi : pas de rechargement
        p = subprocess.run([bash, os.path.join(tmp, 'lancer-asrd.sh').replace('\\', '/'), 'filtre', '27215', '0'],
                           input=JOURNAL.encode('utf-8'), capture_output=True, timeout=60)
        if 'changelevel' in p.stdout.decode('utf-8'):
            soucis.append('filtre : rechargement de carte alors qu’aucun défi n’est choisi')

# ── 10. regex de console ─────────────────────────────────────────────────────
ESSAIS = [
    ('Console.AppReadyRegex', 'TeamKit : serveur Alien Swarm: Reactive Drop pret (port 27215).', {}),
    ('Console.UserJoinRegex', 'TeamKit : Kevin [FR] a rejoint la partie (SteamID STEAM_1:0:12345).',
     {'username': 'Kevin [FR]', 'userid': 'STEAM_1:0:12345'}),
    ('Console.UserJoinRegex', 'TeamKit : a (b) a rejoint la partie (SteamID [U:1:24690]).',
     {'username': 'a (b)', 'userid': '[U:1:24690]'}),
    ('Console.UserLeaveRegex', 'TeamKit : Kevin [FR] a quitte la partie (SteamID STEAM_1:0:12345).',
     {'username': 'Kevin [FR]', 'userid': 'STEAM_1:0:12345'}),
    ('Console.UserChatRegex', '[Chat] Kevin [FR] : salut : "on" y va ?', {'username': 'Kevin [FR]', 'message': 'salut : "on" y va ?'}),
    ('Console.UpdateAvailableRegex',
     "TeamKit : une mise a jour du jeu est sortie. Le serveur s'arretera des qu'il sera vide : lance Update dans AMP, puis Start.", {}),
]
REFUS = [
    ('Console.AppReadyRegex', 'Connection to Steam servers successful.'),
    ('Console.AppReadyRegex', 'TeamKit : demarrage de srcds_console.exe sous Wine (sans affichage).'),
    ('Console.UserJoinRegex', 'L 10/12/2026 - 21:00:05: "Kevin<3><STEAM_1:0:12345><>" entered the game'),
    ('Console.UserJoinRegex', '[Chat] Bob : TeamKit : Faux a rejoint la partie (SteamID STEAM_1:0:1).'),
    ('Console.UserJoinRegex', 'TeamKit : Kevin [FR] a quitte la partie (SteamID STEAM_1:0:12345).'),
    ('Console.UserLeaveRegex', 'TeamKit : Kevin [FR] a rejoint la partie (SteamID STEAM_1:0:12345).'),
    ('Console.UserChatRegex', 'L 10/12/2026 - 19:54:10: "Console<0><Console><Console>" say "Test RCON TeamKit"'),
]
for cle, ligne, groupes in ESSAIS:
    m = py(cles[cle]).search(ligne)
    if not m or any(m.group(k) != v for k, v in groupes.items()):
        soucis.append('%s devrait reconnaître %r' % (cle, ligne))
for cle, ligne in REFUS:
    if py(cles[cle]).search(ligne):
        soucis.append('%s ne devrait pas reconnaître %r' % (cle, ligne))
# chaque ligne « TeamKit : » du filtre est reconnue par la bonne regex
for l in obtenu:
    if ' a rejoint la partie ' in l and not py(cles['Console.UserJoinRegex']).search(l):
        soucis.append('ligne d’arrivée du lanceur non reconnue : %s' % l)
    if ' a quitte la partie ' in l and not py(cles['Console.UserLeaveRegex']).search(l):
        soucis.append('ligne de départ du lanceur non reconnue : %s' % l)
    if l.startswith('[Chat] ') and not py(cles['Console.UserChatRegex']).search(l):
        soucis.append('ligne de chat du lanceur non reconnue : %s' % l)
if sum(1 for l in obtenu if py(cles['Console.AppReadyRegex']).search(l)) != 1:
    soucis.append('la ligne « prêt » doit sortir une seule fois du filtre')
ok('console', '%d lignes reconnues, %d refusées' % (len(ESSAIS), len(REFUS)))

print()
if soucis:
    print('%d problème(s) :' % len(soucis))
    print('\n'.join('  NON  ' + s for s in soucis))
    sys.exit(1)
print('Tout est bon.')
