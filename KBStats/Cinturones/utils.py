import json
from typing import Dict, Any

from django.db import transaction
from .models import Equipo, Jugador, Partida, StatsJugador


_NAME_ALIASES: dict[str, str] = {
    'Sr Leem0n#11235':      'CarryDoctor#112',
    'Lo siento#EUW2':       'MaikyG#EUW2',
    'Desu Zaa#KIDDO':       'Hikigaayaa#YUKNO',
    '身勝手の極意#T1F':     'LegendLegacyy#EUW',
    'Fumatusi#2103':        'Cuco#ESPÑA',
    'DBX#101':              'Torrente#ESPÑA',
    'CULIT0 SEDIENT0#QL0':  'De Tora Si Soy#Kbron',
    'sara x pauton#papis':  'angelowo#frost',
    'Awika Pump YaaaY#AWKPM': 'SτyłΣR#Pingu',
}


def _apply_name_alias(name: str) -> str:
    return _NAME_ALIASES.get(name, name)


def extract_match_data(json_data: str, equipo_azul_nombre: str, equipo_rojo_nombre: str) -> Dict[str, Any]:
    try:
        data = json.loads(json_data)
        info = data.get('info', {})
        match_id = data.get('metadata', {}).get('matchId')
        participants = info.get('participants', [])
        teams_data = info.get('teams', [])
        game_duration = info.get('gameDuration', 1)
        game_length_minutes = game_duration / 60

        team_id_map = {100: equipo_azul_nombre, 200: equipo_rojo_nombre}
        team_objectives = {100: {}, 200: {}}
        team_total_kills = {100: 0, 200: 0}
        team_total_gold = {100: 0, 200: 0}
        team_total_deaths = {100: 0, 200: 0}
        winning_team_riot_id = None

        for team in teams_data:
            team_id = team.get('teamId')
            objectives = team.get('objectives', {})
            if team.get('win'):
                winning_team_riot_id = team.get('teamId')
            team_total_kills[team_id] = objectives.get('champion', {}).get('kills', 0)
            void_grubs = objectives.get('horde', {}).get('kills', 0)
            herald = objectives.get('riftHerald', {}).get('kills', 0)
            nashor = objectives.get('baron', {}).get('kills', 0)
            dragon = objectives.get('dragon', {}).get('kills', 0)
            elder = objectives.get('elderDragon', {}).get('kills', 0)
            atakhan = objectives.get('atakhan', {}).get('kills', 0)

            team_objectives[team_id] = {
                "Larvas": void_grubs,
                "Heraldo": herald,
                "Barons": nashor,
                "Dragones": dragon,
                "Elders": elder,
                "Atakhan": atakhan,
            }

        if winning_team_riot_id is None and participants:
            if participants[0].get('win'):
                winning_team_riot_id = participants[0].get('teamId')

        # Primer pase: totales de equipo para shares
        for p in participants:
            tid = p.get('teamId')
            team_total_gold[tid]   = team_total_gold.get(tid, 0)  + p.get('goldEarned', 0)
            team_total_deaths[tid] = team_total_deaths.get(tid, 0) + p.get('deaths', 0)

        partida_data = {
            "match_id": match_id,
            "duracion_segundos": game_duration,
            "ganador_riot_id": winning_team_riot_id,
            "dragones_azul": team_objectives[100].get("Dragones", 0),
            "dragones_rojo": team_objectives[200].get("Dragones", 0),
            "heraldos_azul": team_objectives[100].get("Heraldo", 0),
            "heraldos_rojo": team_objectives[200].get("Heraldo", 0),
            "barones_azul": team_objectives[100].get("Barons", 0),
            "barones_rojo": team_objectives[200].get("Barons", 0),
            "elders_azul": team_objectives[100].get("Elders", 0),
            "elders_rojo": team_objectives[200].get("Elders", 0),
            "atakhan_azul": team_objectives[100].get("Atakhan", 0),
            "atakhan_rojo": team_objectives[200].get("Atakhan", 0),
        }

        player_stats_list = []
        for p in participants:
            kills = p.get('kills', 0)
            deaths = p.get('deaths', 0)
            assists = p.get('assists', 0)
            total_minions_killed = p.get('totalMinionsKilled', 0)
            neutral_minions_killed = p.get('neutralMinionsKilled', 0)
            team_riot_id = p.get('teamId')
            # Extraer rol/posición del participante (puede venir en 'teamPosition')
            team_position = (p.get('teamPosition') or '').upper()
            role_map = {
                'TOP': 'TOP',
                'JUNGLE': 'JGL',
                'MIDDLE': 'MID',
                'BOTTOM': 'ADC',
                'UTILITY': 'SUP',
                'SUPPORT': 'SUP',
            }
            mapped_role = role_map.get(team_position, '')
            oro_obtenido = p.get('goldEarned', 0)

            team_kills = team_total_kills.get(team_riot_id, 1)
            cs_total = total_minions_killed + neutral_minions_killed
            cs_min = cs_total / game_length_minutes if game_length_minutes > 0 else 0
            kda_val = (kills + assists) / deaths if deaths > 0 else (kills + assists)

            kp_val_raw = p.get('challenges', {}).get('killParticipation')
            if kp_val_raw is not None:
                kill_participation = round(kp_val_raw * 100, 2) if kp_val_raw <= 1.0 else round(kp_val_raw, 2)
            else:
                kill_participation = round(((kills + assists) / team_kills) * 100, 2) if team_kills > 0 else 0.0

            riot_id_name = p.get('riotIdGameName', 'Jugador')
            riot_id_tag = p.get('riotIdTagline', '000')
            nombre_tag = f"{riot_id_name}#{riot_id_tag}" if riot_id_name and riot_id_tag else 'N/A'

            total_damage_dealt_to_champions = p.get('totalDamageDealtToChampions', 0)
            game_time = game_length_minutes
            dano_min = total_damage_dealt_to_champions / game_length_minutes if game_length_minutes > 0 else 0
            team_damage_percentage = p.get('challenges', {}).get('teamDamagePercentage', 0)
            nombre_tag = _apply_name_alias(nombre_tag)
            

            oro_min = round(oro_obtenido / game_length_minutes, 2) if game_length_minutes > 0 else 0
            porcentaje_dano_equipo = round(team_damage_percentage * 100, 2)

            # Visión desglosada
            wpm  = round(p.get('wardsPlaced', 0)             / game_length_minutes, 3) if game_length_minutes > 0 else 0
            cwpm = round(p.get('visionWardsBoughtInGame', 0) / game_length_minutes, 3) if game_length_minutes > 0 else 0
            wcpm = round(p.get('wardsKilled', 0)             / game_length_minutes, 3) if game_length_minutes > 0 else 0

            # Shares de equipo
            t_gold   = team_total_gold.get(team_riot_id, 1) or 1
            t_deaths = team_total_deaths.get(team_riot_id, 1) or 1
            gold_pct    = round(oro_obtenido / t_gold   * 100, 2)
            death_share = round(deaths       / t_deaths * 100, 2)

            player_stats_list.append({
                "nombre_jugador": nombre_tag,
                "nombre_equipo": team_id_map.get(team_riot_id, "Desconocido"),
                "rol": mapped_role,
                "campeon": p.get('championName', 'N/A'),
                "kills": kills,
                "muertes": deaths,
                "asistencias": assists,
                "kda": round(kda_val, 2),
                "kp_porcentaje": kill_participation,
                "oro_min": oro_min,
                "dano_infligido": total_damage_dealt_to_champions,
                "porcentaje_dano_equipo": porcentaje_dano_equipo,
                "dano_min": round(dano_min, 2),
                "dano_recibido": p.get('totalDamageTaken', 0),
                "cs": cs_total,
                "cs_min": round(cs_min, 2),
                "vision_min": round(p.get('visionScore', 0) / game_length_minutes, 2) if game_length_minutes > 0 else 0,
                "double_kills": p.get('doubleKills', 0),
                "triple_kills": p.get('tripleKills', 0),
                "quadra_kills": p.get('quadraKills', 0),
                "penta_kills": p.get('pentaKills', 0),
                "game_time": game_time,
                "dano_oro": round(dano_min / oro_min, 2) if oro_min > 0 else 0,
                "wpm": wpm,
                "cwpm": cwpm,
                "wcpm": wcpm,
                "gold_pct": gold_pct,
                "death_share": death_share,
                "victoria": bool(p.get('win', False)),
            })

        return {"partida": partida_data, "stats_jugadores": player_stats_list}

    except Exception:
        return {}


def save_to_django(match_data: Dict[str, Any], jornada: str, numero_partida: str,
                   equipo_azul_nombre: str, equipo_rojo_nombre: str):
    if not match_data:
        return

    partida_data = match_data.get('partida', {})
    stats_list = match_data.get('stats_jugadores', [])

    with transaction.atomic():
        equipo_azul, _ = Equipo.objects.get_or_create(nombre=equipo_azul_nombre)
        equipo_rojo, _ = Equipo.objects.get_or_create(nombre=equipo_rojo_nombre)

        ganador_riot_id = partida_data.get('ganador_riot_id')
        riot_map = {100: equipo_azul, 200: equipo_rojo}
        ganador_equipo = riot_map.get(ganador_riot_id)

        match_id_riot = partida_data.get('match_id')
        partida_obj, created = Partida.objects.get_or_create(
            match_id=match_id_riot,
            defaults={
                'jornada': jornada,
                'numero_partida': numero_partida,
                'equipo_azul': equipo_azul,
                'equipo_rojo': equipo_rojo,
                'ganador_equipo': ganador_equipo,
                'duracion_segundos': partida_data.get('duracion_segundos', 0),
                'dragones_azul': partida_data.get('dragones_azul', 0),
                'dragones_rojo': partida_data.get('dragones_rojo', 0),
                'heraldos_azul': partida_data.get('heraldos_azul', 0),
                'heraldos_rojo': partida_data.get('heraldos_rojo', 0),
                'barones_azul': partida_data.get('barones_azul', 0),
                'barones_rojo': partida_data.get('barones_rojo', 0),
                'elders_azul': partida_data.get('elders_azul', 0),
                'elders_rojo': partida_data.get('elders_rojo', 0),
                'atakhan_azul': partida_data.get('atakhan_azul', 0),
                'atakhan_rojo': partida_data.get('atakhan_rojo', 0),
            }
        )

        if not created:
            partida_obj.jornada = jornada or partida_obj.jornada
            partida_obj.numero_partida = numero_partida or partida_obj.numero_partida
            partida_obj.duracion_segundos = partida_data.get('duracion_segundos', partida_obj.duracion_segundos)
            partida_obj.dragones_azul = partida_data.get('dragones_azul', partida_obj.dragones_azul)
            partida_obj.dragones_rojo = partida_data.get('dragones_rojo', partida_obj.dragones_rojo)
            partida_obj.heraldos_azul = partida_data.get('heraldos_azul', partida_obj.heraldos_azul)
            partida_obj.heraldos_rojo = partida_data.get('heraldos_rojo', partida_obj.heraldos_rojo)
            partida_obj.barones_azul = partida_data.get('barones_azul', partida_obj.barones_azul)
            partida_obj.barones_rojo = partida_data.get('barones_rojo', partida_obj.barones_rojo)
            partida_obj.elders_azul = partida_data.get('elders_azul', partida_obj.elders_azul)
            partida_obj.elders_rojo = partida_data.get('elders_rojo', partida_obj.elders_rojo)
            partida_obj.atakhan_azul = partida_data.get('atakhan_azul', partida_obj.atakhan_azul)
            partida_obj.atakhan_rojo = partida_data.get('atakhan_rojo', partida_obj.atakhan_rojo)
            if ganador_equipo:
                partida_obj.ganador_equipo = ganador_equipo
            partida_obj.save()

        for p_stats in stats_list:
            nombre_jugador = p_stats.get('nombre_jugador')
            nombre_equipo = p_stats.get('nombre_equipo')
            equipo_obj = equipo_azul if nombre_equipo == equipo_azul.nombre else equipo_rojo

            jugador_obj, _ = Jugador.objects.get_or_create(nombre=nombre_jugador, defaults={'equipo': equipo_obj})
            if jugador_obj.equipo is None and equipo_obj is not None:
                jugador_obj.equipo = equipo_obj
                jugador_obj.save()

            stats_defaults = {
                'campeon': p_stats.get('campeon'),
                'rol': p_stats.get('rol'),
                'equipo_nombre': p_stats.get('nombre_equipo'),
                'kills': p_stats.get('kills', 0),
                'muertes': p_stats.get('muertes', 0),
                'asistencias': p_stats.get('asistencias', 0),
                'kda': p_stats.get('kda', 0.0),
                'kp_porcentaje': p_stats.get('kp_porcentaje', 0.0),
                'oro_min': p_stats.get('oro_min', 0),
                'dano_infligido': p_stats.get('dano_infligido', 0),
                'porcentaje_dano_equipo': p_stats.get('porcentaje_dano_equipo', 0.0),
                'dano_min': p_stats.get('dano_min', 0.0),
                'dano_recibido': p_stats.get('dano_recibido', 0),
                'cs': p_stats.get('cs', 0),
                'cs_min': p_stats.get('cs_min', 0.0),
                'vision_min': p_stats.get('vision_min', 0),
                'double_kills': p_stats.get('double_kills', 0),
                'triple_kills': p_stats.get('triple_kills', 0),
                'quadra_kills': p_stats.get('quadra_kills', 0),
                'penta_kills': p_stats.get('penta_kills', 0),
                'game_time': p_stats.get('game_time', 0.0),
                'dano_oro': p_stats.get('dano_oro', 0.0),
                'wpm': p_stats.get('wpm', 0.0),
                'cwpm': p_stats.get('cwpm', 0.0),
                'wcpm': p_stats.get('wcpm', 0.0),
                'gold_pct': p_stats.get('gold_pct', 0.0),
                'death_share': p_stats.get('death_share', 0.0),
                'victoria': p_stats.get('victoria', False),
            }

            StatsJugador.objects.update_or_create(
                partida=partida_obj,
                jugador=jugador_obj,
                defaults=stats_defaults,
            )



def calculate_jungler_proximity(position_data: dict, team_roles: dict) -> dict:
    """
    Calcula la proximidad del jungler a cada compañero de carril (top/mid/adc/sup)
    midiendo distancia euclídea en coordenadas LoL frame a frame.

    team_roles : {100: {'top': 'Alias', 'jgl': 'Alias', 'mid': ..., 'adc': ..., 'sup': ...},
                  200: {...}}

    Retorna:
    {
      'blue': {'name': str, 'all': {top,mid,adc,sup}, 'early': {...}, 'mid': {...}, 'late': {...}},
      'red' : {...},
    }
    """
    EARLY_MS          = 900_000
    MID_MS            = 1_800_000
    PROXIMITY_THRESH  = 3500   # unidades LoL (~1.5 pantallas)
    LANES             = ('top', 'mid', 'adc', 'sup')

    players = position_data.get('players', {})

    # Construir alias→pid: aplicar _apply_name_alias al nombre raw del position_data
    aliased_to_pid: dict[str, str] = {}
    for pid, pdata in players.items():
        raw = pdata.get('name', '')
        aliased = _apply_name_alias(raw)
        aliased_to_pid[aliased.lower()] = pid
        aliased_to_pid[aliased.split('#')[0].lower()] = pid

    def find_pid(name: str) -> str | None:
        return (aliased_to_pid.get(name.lower())
                or aliased_to_pid.get(name.split('#')[0].lower()))

    def pos_at_time(pid: str, t: int):
        """Posición del jugador en el instante más cercano a t."""
        pts = players.get(pid, {}).get('positions', [])
        if not pts:
            return None
        best, best_dt = pts[0], float('inf')
        for p in pts:
            pt = p[2] if len(p) >= 3 else 0
            dt = abs(pt - t)
            if dt < best_dt:
                best, best_dt = p, dt
            if pt > t + 120_000:   # 2 min de margen, parar pronto
                break
        return best[:2]

    def compute_pcts(jgl_pid: str, lane_pids: dict, t_min=0, t_max=float('inf')) -> dict:
        counts = {role: 0 for role in LANES}
        total  = 0
        for pos in players[jgl_pid]['positions']:
            t = pos[2] if len(pos) >= 3 else 0
            if t < t_min or t >= t_max:
                continue
            jx, jy = pos[0], pos[1]
            min_dist, closest = float('inf'), None
            for role in LANES:
                lpid = lane_pids.get(role)
                if not lpid:
                    continue
                lp = pos_at_time(lpid, t)
                if not lp:
                    continue
                d = ((jx - lp[0]) ** 2 + (jy - lp[1]) ** 2) ** 0.5
                if d < min_dist:
                    min_dist, closest = d, role
            if closest and min_dist < PROXIMITY_THRESH:
                counts[closest] += 1
            total += 1

        lane_total = sum(counts.values())
        if not lane_total:
            return {k: 0.0 for k in LANES}
        return {k: round(counts[k] / lane_total * 100, 1) for k in LANES}

    team_keys = {100: 'blue', 200: 'red'}
    result = {}

    for team_id, roles in team_roles.items():
        jgl_name = roles.get('jgl')
        if not jgl_name:
            continue
        jgl_pid = find_pid(jgl_name)
        if not jgl_pid:
            continue

        lane_pids = {role: find_pid(roles[role]) for role in LANES if roles.get(role)}

        result[team_keys[team_id]] = {
            'name':  jgl_name,
            'all':   compute_pcts(jgl_pid, lane_pids),
            'early': compute_pcts(jgl_pid, lane_pids, 0,        EARLY_MS),
            'mid':   compute_pcts(jgl_pid, lane_pids, EARLY_MS, MID_MS),
            'late':  compute_pcts(jgl_pid, lane_pids, MID_MS),
        }

    return result


def extract_positions_from_timeline(timeline_json: str, match_json: str) -> dict | None:
    """
    Extrae posiciones de todos los participantes frame a frame del timeline.

    Retorna:
    {
      "players": {
        "1": {"name": "Player#TAG", "team": 100, "positions": [[x,y], ...]},
        ...
      },
      "kills": [{"killer": pid, "victim": pid, "x": int, "y": int, "t": ms}, ...]
    }
    Los kills incluyen posición exacta de cada muerte (útil para heatmap de peleas).
    Coordenadas LoL: x/y de 0 a ~14820. El eje Y debe invertirse para mostrar en pantalla.
    """
    try:
        timeline = json.loads(timeline_json)
        match    = json.loads(match_json)
    except Exception:
        return None

    participants = match.get('info', {}).get('participants', [])
    pid_to_name: dict[str, str] = {}
    pid_to_team: dict[str, int] = {}
    for p in participants:
        pid = str(p['participantId'])
        name = p.get('riotIdGameName', 'Unknown') + '#' + p.get('riotIdTagline', '000')
        pid_to_name[pid] = name
        pid_to_team[pid] = p.get('teamId', 100)

    frames = timeline.get('info', {}).get('frames', [])

    # Tipos de evento que tienen posición + participantId
    EVENT_TYPES_WITH_POS = {
        'WARD_PLACED', 'WARD_KILL', 'ITEM_PURCHASED', 'ITEM_SOLD',
        'SKILL_LEVEL_UP', 'LEVEL_UP', 'CHAMPION_SPECIAL_KILL',
        'BUILDING_KILL', 'ELITE_MONSTER_KILL',
    }
    INTERP_STEPS = 9  # 9 puntos intermedios entre frames → posición cada ~6 s

    positions:  dict[str, list] = {str(i): [] for i in range(1, 11)}
    prev_frame: dict[str, tuple] = {}  # pid -> (x, y, t)
    kills:      list[dict] = []
    objectives: list[dict] = []

    for frame in frames:
        frame_t = frame.get('timestamp', 0)
        pf = frame.get('participantFrames', {})

        for pid_str, pdata in pf.items():
            pos = pdata.get('position', {})
            if not pos:
                continue
            cx, cy = pos['x'], pos['y']

            # Interpolar desde el frame anterior
            if pid_str in prev_frame:
                px, py, pt = prev_frame[pid_str]
                for step in range(1, INTERP_STEPS + 1):
                    frac = step / (INTERP_STEPS + 1)
                    positions[pid_str].append([
                        round(px + (cx - px) * frac),
                        round(py + (cy - py) * frac),
                        round(pt + (frame_t - pt) * frac),
                    ])

            positions[pid_str].append([cx, cy, frame_t])
            prev_frame[pid_str] = (cx, cy, frame_t)

        for ev in frame.get('events', []):
            ev_type = ev.get('type', '')
            ev_pos  = ev.get('position', {})
            ev_t    = ev.get('timestamp', 0)

            if ev_type == 'CHAMPION_KILL':
                kills.append({
                    'killer': ev.get('killerId', 0),
                    'victim': ev.get('victimId', 0),
                    'x': ev_pos.get('x', 0),
                    'y': ev_pos.get('y', 0),
                    't': ev_t,
                })
                for pid_key in ('killerId', 'victimId'):
                    pid_str = str(ev.get(pid_key, 0))
                    if pid_str in positions and ev_pos:
                        positions[pid_str].append([ev_pos['x'], ev_pos['y'], ev_t])

            elif ev_type == 'ELITE_MONSTER_KILL':
                objectives.append({
                    'type':    ev.get('monsterType', ''),
                    'subtype': ev.get('monsterSubType', ''),
                    'team':    ev.get('killerTeamId', 0),
                    'x': ev_pos.get('x', 0) if ev_pos else 0,
                    'y': ev_pos.get('y', 0) if ev_pos else 0,
                    't': ev_t,
                })
                pid_str = str(ev.get('participantId', 0))
                if ev_pos and pid_str in positions:
                    positions[pid_str].append([ev_pos['x'], ev_pos['y'], ev_t])

            elif ev_type == 'BUILDING_KILL' and ev_pos:
                objectives.append({
                    'type':      'TOWER',
                    'subtype':   ev.get('towerType', ''),
                    'lane':      ev.get('laneType', ''),
                    'team_lost': ev.get('teamId', 0),
                    'x': ev_pos['x'],
                    'y': ev_pos['y'],
                    't': ev_t,
                })

            elif ev_type in EVENT_TYPES_WITH_POS and ev_pos:
                pid_str = str(ev.get('participantId', 0))
                if pid_str in positions:
                    positions[pid_str].append([ev_pos['x'], ev_pos['y'], ev_t])

    # Ordenar por timestamp para que el filtro de fase funcione correctamente
    for pid_str in positions:
        positions[pid_str].sort(key=lambda p: p[2])

    return {
        'players': {
            pid: {
                'name':      pid_to_name.get(pid, pid),
                'team':      pid_to_team.get(pid, 100),
                'positions': positions[pid],
            }
            for pid in positions
        },
        'kills':      kills,
        'objectives': objectives,
    }


def update_early_game_stats(timeline_json: str, match_json: str, match_id_str: str) -> None:
    """
    Extrae métricas de early game del timeline y las guarda en StatsJugador.

    Campos actualizados por jugador:
      gd15  : diferencia de oro vs rival de mismo rol al min 15
      csd15 : diferencia de CS vs rival de mismo rol al min 15
      xpd15 : diferencia de XP vs rival de mismo rol al min 15
      cs15  : CS absoluto al min 15
      ka15  : kills + assists antes del min 15
      fb    : participó en First Blood (kill o assist)
      fbv   : fue la primera víctima del juego
    """
    try:
        timeline = json.loads(timeline_json)
        match    = json.loads(match_json)
    except Exception:
        return

    frames     = timeline.get('info', {}).get('frames', [])
    TARGET_MS  = 15 * 60 * 1000

    participants = match.get('info', {}).get('participants', [])

    # pid → nombre normalizado
    pid_to_name: dict[int, str] = {}
    for p in participants:
        raw = f"{p.get('riotIdGameName','Jugador')}#{p.get('riotIdTagline','000')}"
        pid_to_name[p['participantId']] = _apply_name_alias(raw)

    # Rival de mismo rol: pid100 ↔ pid200 (misma teamPosition)
    role_to_pids: dict[str, list[int]] = {}
    for p in participants:
        pos = p.get('teamPosition', 'UNKNOWN')
        role_to_pids.setdefault(pos, []).append(p['participantId'])

    rival_de: dict[int, int] = {}
    for pids in role_to_pids.values():
        if len(pids) == 2:
            rival_de[pids[0]] = pids[1]
            rival_de[pids[1]] = pids[0]

    # Frame más cercano al min 15
    frame_15 = min(frames, key=lambda f: abs(f['timestamp'] - TARGET_MS), default=None)
    if frame_15 is None:
        return

    pf = frame_15.get('participantFrames', {})

    def cs(f: dict) -> int:
        return f.get('minionsKilled', 0) + f.get('jungleMinionsKilled', 0)

    # Eventos pre-15 para KA@15 y First Blood
    ka15: dict[int, int] = {}
    fb_killer  = 0
    fb_victim  = 0
    fb_assists: list[int] = []

    for frame in frames:
        if frame['timestamp'] > TARGET_MS:
            break
        for ev in frame.get('events', []):
            if ev['type'] != 'CHAMPION_KILL':
                continue
            if fb_killer == 0:
                fb_killer  = ev.get('killerId', 0)
                fb_victim  = ev.get('victimId', 0)
                fb_assists = ev.get('assistingParticipantIds', [])
            k = ev.get('killerId', 0)
            if k > 0:
                ka15[k] = ka15.get(k, 0) + 1
            for a in ev.get('assistingParticipantIds', []):
                ka15[a] = ka15.get(a, 0) + 1

    # Recuperar Partida y actualizar cada StatsJugador
    try:
        partida_obj = Partida.objects.get(match_id=match_id_str)
    except Partida.DoesNotExist:
        return

    for pid in range(1, 11):
        nombre = pid_to_name.get(pid)
        if not nombre:
            continue
        my   = pf.get(str(pid), {})
        opp  = pf.get(str(rival_de.get(pid, -1)), {})

        early = {
            'gd15':  my.get('totalGold', 0)  - opp.get('totalGold', 0),
            'csd15': cs(my)                   - cs(opp),
            'xpd15': my.get('xp', 0)         - opp.get('xp', 0),
            'cs15':  cs(my),
            'ka15':  ka15.get(pid, 0),
            'fb':    pid == fb_killer or pid in fb_assists,
            'fbv':   pid == fb_victim,
        }

        StatsJugador.objects.filter(
            partida=partida_obj,
            jugador__nombre=nombre,
        ).update(**early)
