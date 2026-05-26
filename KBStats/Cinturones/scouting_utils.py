"""Utilidades de scouting: llamadas a la API de Riot y análisis de datos."""

import json
import os
import time
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
                    count: int = 50, queue: int = 420) -> list:
    """Devuelve lista de match IDs ranked recientes (queue 420 = SoloQ, 440 = Flex)."""
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
    if x < 2500 and y < 2500:
        return 'base_blue'
    if x > 12300 and y > 12300:
        return 'base_red'
    if y > 12500 or (x < 2000 and y > 9500):
        return 'top_lane'
    if x > 12500 or (y < 2000 and x > 9500):
        return 'bot_lane'
    diag_dist = abs(x - y)
    mid_pos   = (x + y) / 2
    if diag_dist < 1500 and 4500 < mid_pos < 10500:
        return 'mid_lane'
    if 5800 < x < 8700 and 5800 < y < 8700:
        return 'river'
    if x < 7200 and y < 7200:
        return 'blue_jungle'
    if x > 7600 and y > 7600:
        return 'red_jungle'
    return 'other'


ZONE_LABELS = {
    'base_blue':  'Base Azul',
    'base_red':   'Base Roja',
    'top_lane':   'Top',
    'bot_lane':   'Bot',
    'mid_lane':   'Mid',
    'river':      'Río',
    'blue_jungle': 'Jungla Azul',
    'red_jungle':  'Jungla Roja',
    'other':      'Otro',
}

ZONE_COLORS = {
    'base_blue':   '#3b82f6',
    'base_red':    '#ef4444',
    'top_lane':    '#a78bfa',
    'bot_lane':    '#fb923c',
    'mid_lane':    '#facc15',
    'river':       '#22d3ee',
    'blue_jungle': '#60a5fa',
    'red_jungle':  '#f87171',
    'other':       '#6b7280',
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


def extract_jungle_analysis(timeline_json: str, match_json: str, puuid: str) -> dict | None:
    """
    Extrae análisis completo del jungla para un participante identificado por PUUID.
    Devuelve {'positions': [[x,y,t],...], 'jungle_stats': {...}}.
    """
    try:
        timeline = json.loads(timeline_json)
        match    = json.loads(match_json)
    except Exception:
        return None

    participants = match.get('info', {}).get('participants', [])
    target_pid  = None
    target_team = 100
    pid_to_info = {}

    for p in participants:
        pid = str(p['participantId'])
        pid_to_info[pid] = {
            'name':    p.get('riotIdGameName', 'Unknown'),
            'team':    p.get('teamId', 100),
            'role':    p.get('teamPosition', ''),
            'champion': p.get('championName', ''),
        }
        if p.get('puuid') == puuid:
            target_pid  = pid
            target_team = p.get('teamId', 100)

    if not target_pid:
        return None

    frames      = timeline.get('info', {}).get('frames', [])
    positions   = []
    zone_counts = defaultdict(int)
    early_zone  = defaultdict(int)   # 0-10 min
    kills_involving = []
    INTERP = 4

    prev = None
    for frame in frames:
        frame_t = frame.get('timestamp', 0)
        pf      = frame.get('participantFrames', {})
        pdata   = pf.get(target_pid, {})
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
                    z = classify_zone(ix, iy)
                    zone_counts[z] += 1
                    if it < 600000:
                        early_zone[z] += 1

            positions.append([cx, cy, frame_t])
            z = classify_zone(cx, cy)
            zone_counts[z] += 1
            if frame_t < 600000:
                early_zone[z] += 1
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
            ev_pos  = ev.get('position', {})
            zone    = classify_zone(ev_pos.get('x', 0), ev_pos.get('y', 0))
            victim_info = pid_to_info.get(str(victim), {})
            kills_involving.append({
                't':               ev.get('timestamp', 0),
                'zone':            zone,
                'victim_champion': victim_info.get('champion', ''),
                'victim_team':     victim_info.get('team', 0),
                'is_gank':         zone in ('top_lane', 'mid_lane', 'bot_lane'),
                'kill':            killer == pid_int,
            })

    positions.sort(key=lambda p: p[2])

    # Lado de inicio: mayoría de posiciones en los primeros 3 min
    early_pos  = [p for p in positions if p[2] < 180000]
    blue_early = sum(1 for p in early_pos if classify_zone(p[0], p[1]) == 'blue_jungle')
    red_early  = sum(1 for p in early_pos if classify_zone(p[0], p[1]) == 'red_jungle')
    starting_side = 'blue' if blue_early >= red_early else 'red'

    total      = sum(zone_counts.values()) or 1
    zone_pct   = {z: round(v / total * 100, 1) for z, v in zone_counts.items()}
    e_total    = sum(early_zone.values()) or 1
    early_pct  = {z: round(v / e_total * 100, 1) for z, v in early_zone.items()}

    enemy_key     = 'red_jungle' if target_team == 100 else 'blue_jungle'
    invasion_pct  = zone_pct.get(enemy_key, 0.0)
    ganks         = [k for k in kills_involving if k['is_gank']]

    return {
        'positions': positions,
        'jungle_stats': {
            'starting_side':   starting_side,
            'team':            target_team,
            'zone_pct':        zone_pct,
            'early_zone_pct':  early_pct,
            'invasion_pct':    invasion_pct,
            'kills_involving': kills_involving,
            'gank_count':      len(ganks),
            'gank_kills':      sum(1 for g in ganks if g['kill']),
        },
    }


# ── Agregados de estadísticas ─────────────────────────────────────────────────

def compute_player_aggregates(matches):
    """Calcula stats agregados por campeón y totales."""
    champ_stats = defaultdict(lambda: {'games': 0, 'wins': 0, 'kills': 0, 'deaths': 0, 'assists': 0})
    total = {'games': 0, 'wins': 0, 'kills': 0, 'deaths': 0, 'assists': 0}

    for m in matches:
        c = m.champion_name
        champ_stats[c]['games']   += 1
        champ_stats[c]['wins']    += int(m.win)
        champ_stats[c]['kills']   += m.kills
        champ_stats[c]['deaths']  += m.deaths
        champ_stats[c]['assists'] += m.assists
        total['games']   += 1
        total['wins']    += int(m.win)
        total['kills']   += m.kills
        total['deaths']  += m.deaths
        total['assists'] += m.assists

    def kda(k, d, a):
        return round((k + a) / max(1, d), 2)

    champs = []
    for name, s in sorted(champ_stats.items(), key=lambda x: -x[1]['games']):
        champs.append({
            'name':    name,
            'games':   s['games'],
            'winrate': round(s['wins'] / s['games'] * 100, 1),
            'kda':     kda(s['kills'], s['deaths'], s['assists']),
            'avg_k':   round(s['kills']   / s['games'], 1),
            'avg_d':   round(s['deaths']  / s['games'], 1),
            'avg_a':   round(s['assists'] / s['games'], 1),
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
    """
    Detecta partidas donde aparecen varias cuentas del mismo jugador
    o cuentas de otros jugadores scouted en la misma partida.
    """
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
