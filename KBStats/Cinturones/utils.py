import json
from typing import Dict, Any
import requests

from django.db import transaction
from .models import Equipo, Jugador, Partida, StatsJugador


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
            if nombre_tag == 'Sr Leem0n#11235':
                nombre_tag = 'CarryDoctor#112'
            elif nombre_tag == 'Lo siento#EUW2':
                nombre_tag = 'MaikyG#EUW2'
            if nombre_tag == 'Desu Zaa#KIDDO':
                nombre_tag = 'Hikigaayaa#YUKNO'
            if nombre_tag == '身勝手の極意#T1F':
                nombre_tag = 'LegendLegacyy#EUW'
            if nombre_tag == 'Fumatusi#2103':
                nombre_tag = 'Cuco#ESPÑA'
            if nombre_tag == 'DBX#101':
                nombre_tag = 'Torrente#ESPÑA'

            oro_min = round(oro_obtenido / game_length_minutes, 2) if game_length_minutes > 0 else 0
                            
            porcentaje_dano_equipo = round(team_damage_percentage * 100, 2)
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
            }

            StatsJugador.objects.update_or_create(
                partida=partida_obj,
                jugador=jugador_obj,
                defaults=stats_defaults,
            )
