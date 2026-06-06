"""Utilidades de scouting: llamadas a la API de Riot y análisis de datos."""

import json
import os
from collections import defaultdict

import requests
from django.conf import settings


# ── API helpers ───────────────────────────────────────────────────────────────

def get_api_key():
    return os.environ.get('RIOT_API_KEY') or getattr(settings, 'RIOT_API_KEY', None)


def resolve_puuid(riot_id: str, api_key: str, routing: str = 'europe') -> str | None:
    """Resuelve PUUID a partir de 'GameName#TAG'."""
    if '#' not in riot_id:
        return None
    game_name, tag_line = riot_id.split('#', 1)
    url = (
        f'https://{routing}.api.riotgames.com/riot/account/v1/accounts/'
        f'by-riot-id/{game_name}/{tag_line}?api_key={api_key}'
    )
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return r.json().get('puuid')
    except Exception:
        return None


def fetch_match_ids(puuid: str, api_key: str, routing: str = 'europe',
                    count: int = 100, queue: int = 420) -> list:
    """
    Devuelve hasta `count` match IDs ranked recientes.
    Se piden 100 por defecto para tener margen al filtrar por rol.
    queue=420 SoloQ, queue=440 Flex.
    """
    url = (
        f'https://{routing}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids'
        f'?type=ranked&queue={queue}&count={count}&api_key={api_key}'
    )
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []


# ── Clasificación de zonas del mapa ──────────────────────────────────────────

def classify_zone(x: float, y: float) -> str:
    # ── Bases (fountain) ─────────────────────────────────────────────────────
    if x < 1500 and y < 1500:
        return 'base_blue'
    if x > 13300 and y > 13300:
        return 'base_red'

    # ── Carriles ─────────────────────────────────────────────────────────────
    # Top: borde superior + tramo izquierdo pegado a la pared
    if y > 13200:
        return 'top_lane'
    if x < 1600 and y > 6500:
        return 'top_lane'
    # Bot: borde derecho + tramo inferior pegado a la pared
    if x > 13200:
        return 'bot_lane'
    if y < 1600 and x > 6500:
        return 'bot_lane'
    # Mid: corredor diagonal principal
    diag_dist = abs(x - y)
    mid_pos   = (x + y) / 2
    if diag_dist < 1500 and 4000 < mid_pos < 11500:
        return 'mid_lane'

    # ── Río (centro del mapa) ─────────────────────────────────────────────────
    if 6000 < x < 8800 and 6000 < y < 8800:
        return 'river'

    # ── Jungla: anti-diagonal x+y = 14820 separa ambos lados perfectamente ──
    # Todos los camps azules tienen x+y < 14820; todos los rojos x+y > 14820
    if x + y < 14820:
        return 'blue_jungle'
    return 'red_jungle'


ZONE_LABELS = {
    'base_blue':    'Base Azul',
    'base_red':     'Base Roja',
    'top_lane':     'Top',
    'bot_lane':     'Bot',
    'mid_lane':     'Mid',
    'river':        'Río',
    'own_jungle':   'Jungla Propia',
    'enemy_jungle': 'Jungla Enemiga',
    'other':        'Otro',
    # retrocompat con datos antiguos
    'blue_jungle':  'Jungla Azul',
    'red_jungle':   'Jungla Roja',
}

ZONE_COLORS = {
    'base_blue':    '#3b82f6',
    'base_red':     '#ef4444',
    'top_lane':     '#a78bfa',
    'bot_lane':     '#fb923c',
    'mid_lane':     '#facc15',
    'river':        '#22d3ee',
    'own_jungle':   '#60a5fa',
    'enemy_jungle': '#f87171',
    'other':        '#6b7280',
    # retrocompat
    'blue_jungle':  '#60a5fa',
    'red_jungle':   '#f87171',
}


# ── Extracción de datos ───────────────────────────────────────────────────────

def extract_match_summary(match_json_str: str, puuid: str) -> dict | None:
    """Extrae stats clave de una partida para un participante dado su PUUID."""
    try:
        match = json.loads(match_json_str)
    except Exception:
        return None

    participants = match.get('info', {}).get('participants', [])
    target = next((p for p in participants if p.get('puuid') == puuid), None)
    if not target:
        return None

    return {
        'champion_name': target.get('championName', ''),
        'role':          target.get('teamPosition', ''),
        'team_id':       target.get('teamId', 100),
        'win':           target.get('win', False),
        'kills':         target.get('kills', 0),
        'deaths':        target.get('deaths', 0),
        'assists':       target.get('assists', 0),
        'cs':            target.get('totalMinionsKilled', 0) + target.get('neutralMinionsKilled', 0),
        'vision_score':  target.get('visionScore', 0),
        'damage_dealt':  target.get('totalDamageDealtToChampions', 0),
        'gold_earned':   target.get('goldEarned', 0),
        'game_duration': match.get('info', {}).get('gameDuration', 0),
        'queue_id':      match.get('info', {}).get('queueId', 0),
        'game_start':    match.get('info', {}).get('gameStartTimestamp', 0),
        'participants': [
            {
                'puuid':    p.get('puuid', ''),
                'name':     p.get('riotIdGameName', ''),
                'champion': p.get('championName', ''),
                'team':     p.get('teamId', 100),
                'role':     p.get('teamPosition', ''),
                'win':      p.get('win', False),
            }
            for p in participants
        ],
    }


_JUNGLE_ZONES    = {'own_jungle', 'enemy_jungle', 'blue_jungle', 'red_jungle',
                    'river', 'base_blue', 'base_red'}
_GANK_LOOKBACK_MS = 90_000  # el jungla debe haber estado en zona jungla en los 90s previos


def _relative_zone(zone: str, team: int) -> str:
    """Convierte blue_jungle/red_jungle a own_jungle/enemy_jungle según el equipo."""
    if zone == 'blue_jungle':
        return 'own_jungle' if team == 100 else 'enemy_jungle'
    if zone == 'red_jungle':
        return 'own_jungle' if team == 200 else 'enemy_jungle'
    return zone


def _jungler_pos_at(positions: list, t: int) -> list | None:
    """Devuelve la posición [x, y] del jungla más cercana al instante t."""
    best, best_dt = None, float('inf')
    for pos in positions:
        pt = pos[2] if len(pos) >= 3 else 0
        dt = abs(pt - t)
        if dt < best_dt:
            best, best_dt = pos, dt
        if pt > t + 60_000:
            break
    return best


def _came_from_jungle(positions: list, kill_t: int) -> bool:
    """True si el jungla estuvo en zona de jungla/río en los 90s previos al kill."""
    start_t = kill_t - _GANK_LOOKBACK_MS
    for pos in positions:
        t = pos[2] if len(pos) >= 3 else 0
        if t < start_t:
            continue
        if t >= kill_t:
            break
        if classify_zone(pos[0], pos[1]) in _JUNGLE_ZONES:
            return True
    return False


def _victim_in_gankable_zone(x: float, y: float) -> bool:
    """True si la víctima estaba en carril o en la entrada al carril desde la jungla.
    Más amplio que classify_zone para capturar ganks en los accesos al carril."""
    # Bases no son gankables
    if x < 1500 and y < 1500:
        return False
    if x > 13300 and y > 13300:
        return False
    # Top: borde superior + acceso izquierdo ampliado
    if y > 11500:
        return True
    if x < 2800 and y > 4500:
        return True
    # Bot: borde derecho + acceso inferior ampliado
    if x > 11500:
        return True
    if y < 2800 and x > 4500:
        return True
    # Mid: diagonal con tolerancia ampliada
    diag_dist = abs(x - y)
    mid_pos = (x + y) / 2
    if diag_dist < 2500 and 3500 < mid_pos < 11500:
        return True
    return False


def extract_jungle_analysis(timeline_json: str, match_json: str, puuid: str) -> dict | None:
    """
    Extrae análisis de pathing del jungla para un participante identificado por PUUID.
    Devuelve {'positions': [[x,y,t],...], 'jungle_stats': {...}}.
    """
    try:
        timeline = json.loads(timeline_json)
        match    = json.loads(match_json)
    except Exception:
        return None

    participants = match.get('info', {}).get('participants', [])
    target_pid   = None
    target_team  = 100
    pid_to_info  = {}

    for p in participants:
        pid = str(p['participantId'])
        pid_to_info[pid] = {
            'name':     p.get('riotIdGameName', 'Unknown'),
            'team':     p.get('teamId', 100),
            'role':     p.get('teamPosition', ''),
            'champion': p.get('championName', ''),
        }
        if p.get('puuid') == puuid:
            target_pid  = pid
            target_team = p.get('teamId', 100)

    if not target_pid:
        return None

    EARLY_MS   = 600_000   # 10 min — distribución de early game
    INVASION_MS = 900_000  # 15 min — ventana para medir invasión

    frames     = timeline.get('info', {}).get('frames', [])
    positions  = []
    zone_counts    = defaultdict(int)
    early_zone     = defaultdict(int)
    invasion_zone  = defaultdict(int)
    kills_involving = []
    INTERP = 4

    prev = None
    for frame in frames:
        frame_t = frame.get('timestamp', 0)
        pdata   = frame.get('participantFrames', {}).get(target_pid, {})
        pos     = pdata.get('position', {})

        if pos:
            cx, cy = pos['x'], pos['y']
            if prev:
                px, py, pt = prev
                for step in range(1, INTERP + 1):
                    frac = step / (INTERP + 1)
                    ix = round(px + (cx - px) * frac)
                    iy = round(py + (cy - py) * frac)
                    it = round(pt + (frame_t - pt) * frac)
                    positions.append([ix, iy, it])
                    z = _relative_zone(classify_zone(ix, iy), target_team)
                    zone_counts[z] += 1
                    if it < EARLY_MS:
                        early_zone[z] += 1
                    if it < INVASION_MS:
                        invasion_zone[z] += 1
            positions.append([cx, cy, frame_t])
            z = _relative_zone(classify_zone(cx, cy), target_team)
            zone_counts[z] += 1
            if frame_t < EARLY_MS:
                early_zone[z] += 1
            if frame_t < INVASION_MS:
                invasion_zone[z] += 1
            prev = (cx, cy, frame_t)

        for ev in frame.get('events', []):
            if ev.get('type') != 'CHAMPION_KILL':
                continue
            killer  = ev.get('killerId', 0)
            victim  = ev.get('victimId', 0)
            assists = ev.get('assistingParticipantIds', [])
            pid_int = int(target_pid)
            if killer != pid_int and pid_int not in assists:
                continue
            ev_t        = ev.get('timestamp', 0)
            ev_pos      = ev.get('position', {})
            victim_x    = ev_pos.get('x', 0)
            victim_y    = ev_pos.get('y', 0)
            # Usar la posición del JUNGLA para la etiqueta de zona mostrada
            jpos        = _jungler_pos_at(positions, ev_t)
            if jpos:
                raw_zone = classify_zone(jpos[0], jpos[1])
            else:
                raw_zone = classify_zone(victim_x, victim_y)
            zone        = _relative_zone(raw_zone, target_team)
            victim_info = pid_to_info.get(str(victim), {})
            # Gank: víctima en/cerca del carril, jungla vino de jungla, y en los primeros 15 min
            is_gank     = (
                ev_t < INVASION_MS
                and _victim_in_gankable_zone(victim_x, victim_y)
                and _came_from_jungle(positions, ev_t)
            )
            kills_involving.append({
                't':               ev_t,
                'zone':            zone,
                'victim_champion': victim_info.get('champion', ''),
                'victim_team':     victim_info.get('team', 0),
                'is_gank':         is_gank,
                'kill':            killer == pid_int,
            })

    positions.sort(key=lambda p: p[2])

    early_pos   = [p for p in positions if p[2] < 180000]
    own_early   = sum(1 for p in early_pos if _relative_zone(classify_zone(p[0], p[1]), target_team) == 'own_jungle')
    enemy_early = sum(1 for p in early_pos if _relative_zone(classify_zone(p[0], p[1]), target_team) == 'enemy_jungle')
    starting_side = 'own' if own_early >= enemy_early else 'enemy'

    total     = sum(zone_counts.values()) or 1
    zone_pct  = {z: round(v / total * 100, 1) for z, v in zone_counts.items()}
    e_total   = sum(early_zone.values()) or 1
    early_pct = {z: round(v / e_total * 100, 1) for z, v in early_zone.items()}

    inv_total    = sum(invasion_zone.values()) or 1
    inv_pct      = {z: round(v / inv_total * 100, 1) for z, v in invasion_zone.items()}
    invasion_pct = inv_pct.get('enemy_jungle', 0.0)

    # Agrupar kills/assists consecutivos de la misma pelea como un único gank.
    # Si dos eventos están a menos de 20 s entre sí, pertenecen a la misma pelea.
    GANK_COOLDOWN_MS = 20_000
    gank_events = sorted([k for k in kills_involving if k['is_gank']], key=lambda k: k['t'])
    gank_count  = 0
    gank_kills  = 0
    last_t      = -GANK_COOLDOWN_MS
    for ev in gank_events:
        if ev['t'] - last_t > GANK_COOLDOWN_MS:
            gank_count += 1
            last_t = ev['t']
        if ev['kill']:
            gank_kills += 1

    return {
        'positions': positions,
        'jungle_stats': {
            'starting_side':   starting_side,
            'team':            target_team,
            'zone_pct':        zone_pct,
            'early_zone_pct':  early_pct,
            'invasion_pct':    invasion_pct,
            'kills_involving': kills_involving,
            'gank_count':      gank_count,
            'gank_kills':      gank_kills,
        },
    }


# ── Agregados ─────────────────────────────────────────────────────────────────

def _winrate(wins, games):
    return round(wins / games * 100, 1) if games else None


def compute_player_aggregates(matches):
    def empty_champ():
        return {
            'games': 0, 'wins': 0, 'kills': 0, 'deaths': 0, 'assists': 0,
            # Pathing: solo top y bot
            'top_sum': 0.0, 'bot_sum': 0.0,
            # Presencia en carril (top + bot) — métrica de actividad fiable
            'lane_presence_sum': 0.0,
            # Ganks normalizados (por 10 min)
            'gank10_sum': 0.0,
            'stat_games': 0,
            # Side breakdown
            'blue': {'games': 0, 'wins': 0},
            'red':  {'games': 0, 'wins': 0},
        }

    champ_stats = defaultdict(empty_champ)
    total = {'games': 0, 'wins': 0, 'kills': 0, 'deaths': 0, 'assists': 0}

    for m in matches:
        c = m.champion_name
        s = champ_stats[c]
        s['games']   += 1
        s['wins']    += int(m.win)
        s['kills']   += m.kills
        s['deaths']  += m.deaths
        s['assists'] += m.assists
        total['games']   += 1
        total['wins']    += int(m.win)
        total['kills']   += m.kills
        total['deaths']  += m.deaths
        total['assists'] += m.assists

        if m.jungle_stats:
            zone_pct     = m.jungle_stats.get('zone_pct', {})
            top_pct_val  = zone_pct.get('top_lane', 0)
            bot_pct_val  = zone_pct.get('bot_lane', 0)
            s['top_sum']            += top_pct_val
            s['bot_sum']            += bot_pct_val
            s['lane_presence_sum']  += top_pct_val + bot_pct_val

            ganks    = m.jungle_stats.get('gank_count', 0)
            duration = m.game_duration or 0
            if duration >= 300:
                s['gank10_sum'] += ganks / (duration / 600)
            else:
                s['gank10_sum'] += ganks
            s['stat_games']  += 1

            team = m.jungle_stats.get('team', 100)
            side = 'blue' if team == 100 else 'red'
            s[side]['games'] += 1
            s[side]['wins']  += int(m.win)

    def kda(k, d, a):
        return round((k + a) / max(1, d), 2)

    champs = []
    for name, s in sorted(champ_stats.items(), key=lambda x: -x[1]['games']):
        g = s['games']
        sg = s['stat_games']

        # Top vs Bot (normalizado entre sí, mid excluido)
        top_avg = s['top_sum'] / sg if sg else 0
        bot_avg = s['bot_sum'] / sg if sg else 0
        tb_total = (top_avg + bot_avg) or 1
        top_pct = round(top_avg / tb_total * 100)
        bot_pct = 100 - top_pct

        # Presencia en carril promedio: % de la partida en top/bot
        # Típico: Full Clear ~4-9%, Activo ~15-25%
        lane_presence = round(s['lane_presence_sum'] / sg, 1) if sg else None

        # Ganks por 10 minutos
        avg_ganks10 = round(s['gank10_sum'] / sg, 2) if sg else None

        # Estilo: Full Clear ↔ Activo según presencia en carril y ganks/10min
        style = None
        if lane_presence is not None and avg_ganks10 is not None:
            if lane_presence < 8 and avg_ganks10 < 0.8:
                style = ('Full Clear', '#fb923c')
            elif lane_presence > 16 or avg_ganks10 >= 1.4:
                style = ('Activo', '#4ade80')
            else:
                style = ('Equilibrado', '#9ca3af')

        blue_wr = _winrate(s['blue']['wins'], s['blue']['games'])
        red_wr  = _winrate(s['red']['wins'],  s['red']['games'])

        champs.append({
            'name':       name,
            'games':      g,
            'winrate':    round(s['wins'] / g * 100, 1),
            'kda':        kda(s['kills'], s['deaths'], s['assists']),
            'avg_k':      round(s['kills']   / g, 1),
            'avg_d':      round(s['deaths']  / g, 1),
            'avg_a':      round(s['assists'] / g, 1),
            'has_stats':  sg > 0,
            # Pathing Top vs Bot
            'top_pct':    top_pct,
            'bot_pct':    bot_pct,
            'top_favored': top_pct >= bot_pct,
            # Actividad
            'lane_presence': lane_presence,
            'avg_ganks10':   avg_ganks10,
            'style':         style,
            # Side
            'blue_games': s['blue']['games'],
            'blue_wr':    blue_wr,
            'red_games':  s['red']['games'],
            'red_wr':     red_wr,
        })

    g = total['games']
    return {
        'champions': champs,
        'total': {
            **total,
            'winrate': round(total['wins'] / g * 100, 1) if g else 0,
            'kda':     kda(total['kills'], total['deaths'], total['assists']),
        },
    }


def find_shared_games(player, all_matches):
    """Detecta partidas donde aparecen varias cuentas del mismo jugador."""
    account_puuids = {acc.puuid: acc for acc in player.accounts.all() if acc.puuid}
    shared = []
    seen   = set()

    for m in all_matches:
        if not m.participants or m.match_id in seen:
            continue
        seen.add(m.match_id)
        participant_puuids = {p['puuid'] for p in m.participants}
        co_accounts = [
            acc for puuid, acc in account_puuids.items()
            if puuid in participant_puuids and puuid != m.account.puuid
        ]
        if co_accounts:
            shared.append({'match': m, 'co_accounts': co_accounts})

    return shared
