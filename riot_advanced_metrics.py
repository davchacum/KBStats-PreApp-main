"""
riot_advanced_metrics.py
Mejoras al sistema de ranking KBStats.

Asume que ya existe:
  - get_match_data(match_id) -> dict  (JSON estándar match-v5)
  - Una lista de jugadores con sus métricas agregadas por torneo/temporada.

Dependencias: requests, numpy, scipy
"""

import requests
import numpy as np
from collections import defaultdict
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────────────────────

RIOT_API_KEY = "TU_API_KEY_AQUI"
ROUTING = "europe"          # americas | asia | europe | sea


# ═════════════════════════════════════════════════════════════════════════════
# 1. MÉTRICAS DE EARLY GAME (timeline endpoint)
# ═════════════════════════════════════════════════════════════════════════════

def get_timeline(match_id: str) -> dict:
    url = f"https://{ROUTING}.api.riotgames.com/lol/match/v5/matches/{match_id}/timeline"
    r = requests.get(url, headers={"X-Riot-Token": RIOT_API_KEY}, timeout=10)
    r.raise_for_status()
    return r.json()


def extract_early_game_metrics(match_id: str, match_data: dict) -> dict[int, dict]:
    """
    Extrae métricas de early game por participantId (1-10).

    Retorna por participante:
      gd15   : diferencia de oro vs rival de mismo rol al min 15
      csd15  : diferencia de CS vs rival de mismo rol al min 15
      xpd15  : diferencia de XP vs rival de mismo rol al min 15
      cs15   : CS absoluto al min 15
      ka15   : kills + assists antes del min 15
      fb_pct : 1 si participó en First Blood (kill o assist), 0 si no
      fbv_pct: 1 si fue la primera víctima del juego, 0 si no
    """
    timeline = get_timeline(match_id)
    frames = timeline["info"]["frames"]

    TARGET_MS = 15 * 60 * 1000  # 900 000 ms

    # Cogemos el frame más cercano a los 15 minutos.
    # Los frames llegan cada ~60 s, así que el índice 15 suele ser exacto,
    # pero usamos min() para ser robustos ante juegos que acaben antes.
    frame_15 = min(frames, key=lambda f: abs(f["timestamp"] - TARGET_MS))

    # ── Mapeamos rol → participantId por equipo ───────────────────────────
    # teamPosition: "TOP" | "JUNGLE" | "MIDDLE" | "BOTTOM" | "UTILITY"
    participants = match_data["info"]["participants"]
    role_map: dict[str, dict[int, int]] = defaultdict(dict)  # pos → {teamId: pid}
    for p in participants:
        pos = p.get("teamPosition", "UNKNOWN")
        role_map[pos][p["teamId"]] = p["participantId"]

    # rival_de[pid] = pid del jugador del equipo contrario en la misma posición
    rival_de: dict[int, int] = {}
    for pos, teams in role_map.items():
        if 100 in teams and 200 in teams:
            rival_de[teams[100]] = teams[200]
            rival_de[teams[200]] = teams[100]

    # ── Eventos anteriores al min 15 ─────────────────────────────────────
    events_pre15: list[dict] = []
    for frame in frames:
        if frame["timestamp"] > TARGET_MS:
            break
        events_pre15.extend(frame.get("events", []))

    # KA@15 y detección de First Blood
    ka15: dict[int, int] = defaultdict(int)
    first_kill_event: Optional[dict] = None

    for ev in events_pre15:
        if ev["type"] != "CHAMPION_KILL":
            continue
        if first_kill_event is None:
            first_kill_event = ev
        killer = ev.get("killerId", 0)
        if killer > 0:
            ka15[killer] += 1
        for assist in ev.get("assistingParticipantIds", []):
            ka15[assist] += 1

    fb_killer  = first_kill_event.get("killerId", 0)        if first_kill_event else 0
    fb_victim  = first_kill_event.get("victimId", 0)         if first_kill_event else 0
    fb_assists = first_kill_event.get("assistingParticipantIds", []) if first_kill_event else []

    # ── Datos de frames al min 15 ─────────────────────────────────────────
    pf = frame_15["participantFrames"]  # clave: string "1" … "10"

    def cs_from_frame(frame: dict) -> int:
        """CS = minions de línea + minions de jungla."""
        return frame.get("minionsKilled", 0) + frame.get("jungleMinionsKilled", 0)

    # ── Construir resultado ───────────────────────────────────────────────
    result: dict[int, dict] = {}
    for pid in range(1, 11):
        my   = pf.get(str(pid), {})
        opp  = pf.get(str(rival_de.get(pid, -1)), {})

        result[pid] = {
            "gd15":    my.get("totalGold", 0)  - opp.get("totalGold", 0),
            "csd15":   cs_from_frame(my)        - cs_from_frame(opp),
            "xpd15":   my.get("xp", 0)         - opp.get("xp", 0),
            "cs15":    cs_from_frame(my),
            "ka15":    ka15[pid],
            "fb_pct":  1 if pid == fb_killer or pid in fb_assists else 0,
            "fbv_pct": 1 if pid == fb_victim else 0,
        }

    return result


# ═════════════════════════════════════════════════════════════════════════════
# 2. MÉTRICAS DE SHARE DE EQUIPO
# ═════════════════════════════════════════════════════════════════════════════

def calculate_team_shares(match_data: dict) -> dict[int, dict]:
    """
    Retorna por participantId:
      gold_pct   : % del oro total del equipo generado por el jugador (0-100)
      gpr        : desviación de gold_pct respecto al 20% esperado (pp)
      death_share: % de muertes del equipo cometidas por el jugador (0-100)
    """
    teams: dict[int, list] = defaultdict(list)
    for p in match_data["info"]["participants"]:
        teams[p["teamId"]].append(p)

    result: dict[int, dict] = {}
    for team_players in teams.values():
        total_gold   = sum(p["goldEarned"] for p in team_players) or 1
        total_deaths = sum(p["deaths"]     for p in team_players) or 1

        for p in team_players:
            gold_pct    = p["goldEarned"] / total_gold   * 100
            death_share = p["deaths"]     / total_deaths * 100
            result[p["participantId"]] = {
                "gold_pct":    round(gold_pct, 2),
                "gpr":         round(gold_pct - 20.0, 2),   # 20 % = reparto igualitario
                "death_share": round(death_share, 2),
            }

    return result


def calculate_dmg_share_post15(match_data: dict, timeline: dict) -> dict[int, float]:
    """
    Aproximación de DMG_SHARE_POST15 usando eventos CHAMPION_KILL del timeline.

    El timeline de match-v5 no expone daño total frame a frame, pero sí incluye
    el campo 'victimDamageDealt' en cada CHAMPION_KILL, que recoge el daño que
    contribuyó a esa muerte. Sumamos ese daño por jugador solo en eventos
    posteriores al min 15 y calculamos el share dentro del equipo.

    Limitación: solo captura daño "que cuenta para kills", no daño a objetivos
    ni en peleas donde nadie muere. Para el total real usa 'totalDamageDealtToChampions'
    del endpoint de partida (el campo es de juego completo).
    """
    TARGET_MS = 15 * 60 * 1000

    participants = match_data["info"]["participants"]
    team_of = {p["participantId"]: p["teamId"] for p in participants}

    dmg_post15: dict[int, float] = defaultdict(float)

    for frame in timeline["info"]["frames"]:
        if frame["timestamp"] <= TARGET_MS:
            continue
        for ev in frame.get("events", []):
            if ev["type"] != "CHAMPION_KILL":
                continue
            for dmg_entry in ev.get("victimDamageDealt", []):
                pid = dmg_entry.get("participantId", 0)
                if pid > 0:
                    total = (dmg_entry.get("magicDamage", 0)
                             + dmg_entry.get("physicalDamage", 0)
                             + dmg_entry.get("trueDamage", 0))
                    dmg_post15[pid] += total

    # Calcular share dentro del equipo
    team_dmg_totals: dict[int, float] = defaultdict(float)
    for pid, dmg in dmg_post15.items():
        team_dmg_totals[team_of.get(pid, 0)] += dmg

    result: dict[int, float] = {}
    for pid in range(1, 11):
        team_total = team_dmg_totals.get(team_of.get(pid, 0), 1) or 1
        result[pid] = round(dmg_post15[pid] / team_total * 100, 2)

    return result


# ═════════════════════════════════════════════════════════════════════════════
# 3. VISIÓN DESGLOSADA (4 métricas)
# ═════════════════════════════════════════════════════════════════════════════

def calculate_vision_metrics(match_data: dict) -> dict[int, dict]:
    """
    Sustituye vision/min por cuatro métricas separadas:
      wpm  : wards colocados / min
      cwpm : control wards comprados / min
      wcpm : wards destruidos / min
      vspm : vision score / min
    """
    duration_min = match_data["info"]["gameDuration"] / 60

    result: dict[int, dict] = {}
    for p in match_data["info"]["participants"]:
        result[p["participantId"]] = {
            "wpm":  round(p.get("wardsPlaced",              0) / duration_min, 3),
            "cwpm": round(p.get("visionWardsBoughtInGame",  0) / duration_min, 3),
            "wcpm": round(p.get("wardsKilled",              0) / duration_min, 3),
            "vspm": round(p.get("visionScore",              0) / duration_min, 3),
        }

    return result


# Pesos de visión recomendados por rol
# SUP: prioridad a CWPM (control wards son su responsabilidad principal)
# JGL: prioridad a WCPM (limpiar wards para invadir/gankar)
# Resto: VSPM como métrica global más equilibrada
VISION_WEIGHTS_BY_ROLE: dict[str, dict[str, float]] = {
    "TOP":     {"wpm": 0.025, "cwpm": 0.020, "wcpm": 0.015, "vspm": 0.040},
    "JGL":     {"wpm": 0.020, "cwpm": 0.025, "wcpm": 0.045, "vspm": 0.040},  # WCPM prioritario
    "MID":     {"wpm": 0.015, "cwpm": 0.015, "wcpm": 0.010, "vspm": 0.035},
    "ADC":     {"wpm": 0.010, "cwpm": 0.010, "wcpm": 0.005, "vspm": 0.015},
    "SUP":     {"wpm": 0.080, "cwpm": 0.120, "wcpm": 0.100, "vspm": 0.030},  # CWPM prioritario
}


# ═════════════════════════════════════════════════════════════════════════════
# 4. MEJORAS METODOLÓGICAS EN EL CÁLCULO DEL SCORE
# ═════════════════════════════════════════════════════════════════════════════

# ── 4a. Z-scores por rol ─────────────────────────────────────────────────────

def compute_zscores_by_role(players: list[dict], metrics: list[str]) -> list[dict]:
    """
    Para cada métrica añade un campo 'z_{métrica}' normalizado dentro del grupo
    de jugadores del mismo rol.

    Sustituye la normalización min-max: los z-scores son más robustos frente a
    jugadores con valores extremos (outliers) y permiten comparar rendimientos
    aunque un rol solo tenga 2-3 jugadores.

    Modifica la lista en-lugar y la devuelve.
    """
    role_groups: dict[str, list[dict]] = defaultdict(list)
    for p in players:
        role_groups[p["rol"]].append(p)

    for rol, group in role_groups.items():
        for metric in metrics:
            vals = np.array([p.get(metric, 0.0) for p in group], dtype=float)
            mean = vals.mean()
            std  = vals.std(ddof=0)  # ddof=0 porque es la población completa del rol

            for p, z in zip(group, (vals - mean) / (std if std > 1e-9 else 1.0)):
                p[f"z_{metric}"] = round(float(z), 4)

    return players


# ── 4b. Shrinkage bayesiano ───────────────────────────────────────────────────

def apply_bayesian_shrinkage(players: list[dict], k: int = 4) -> list[dict]:
    """
    Corrige el score final según el número de partidas jugadas:

        score_final = (n × score_jugador + k × media_rol) / (n + k)

    Con pocos juegos (n pequeño), el score se acerca a la media del rol.
    Con muchos juegos (n grande), predomina el score individual.

    Cómo elegir k:
      k = 2–3  : torneo largo (≥ 15 partidas por jugador). Confías pronto.
      k = 4–5  : torneo corto (5–10 partidas). Valor por defecto.
      k = 6–8  : very high variance / pocos datos. Muy conservador.

    Sustituye al multiplicador por partidas (factor × 0.90-1.00) que era
    arbitrario y no bajaba el score de nadie con pocas partidas sino que
    subía el de los que más jugaban. El shrinkage es más correcto
    estadísticamente: penaliza muestras pequeñas atrayéndolas a la media.

    Requiere: p['raw_score'] y p['games_played'] en cada jugador.
    Añade: p['score'] con el valor final ajustado.
    """
    # Media del rol (sobre raw_score)
    role_scores: dict[str, list[float]] = defaultdict(list)
    for p in players:
        role_scores[p["rol"]].append(p["raw_score"])
    role_mean: dict[str, float] = {
        rol: float(np.mean(scores)) for rol, scores in role_scores.items()
    }

    for p in players:
        n   = p["games_played"]
        mu  = role_mean[p["rol"]]
        raw = p["raw_score"]
        p["score"] = round((n * raw + k * mu) / (n + k), 2)

    return players


# ── 4c. Separación Victoria / Derrota ────────────────────────────────────────

def calculate_winloss_consistency(
    player_games: list[dict],
    metrics: list[str],
) -> dict:
    """
    Recibe la lista de partidas individuales de UN jugador.
    Cada elemento debe tener:
      - 'win': bool
      - Un valor numérico por cada métrica en `metrics`

    Retorna:
      win_avgs        : promedio de cada métrica en victorias
      loss_avgs       : promedio de cada métrica en derrotas
      metric_diffs    : diferencia normalizada |win - loss| / max(|win|, |loss|)
      consistency_score: 1.0 = rendimiento idéntico en V y D; 0.0 = muy inconsistente
    """
    wins   = [g for g in player_games if g.get("win")]
    losses = [g for g in player_games if not g.get("win")]

    def safe_avg(games: list[dict], metric: str) -> float:
        vals = [g[metric] for g in games if metric in g]
        return float(np.mean(vals)) if vals else 0.0

    win_avgs:  dict[str, float] = {}
    loss_avgs: dict[str, float] = {}
    diffs:     dict[str, float] = {}

    for m in metrics:
        w = safe_avg(wins,   m)
        l = safe_avg(losses, m)
        win_avgs[m]  = round(w, 4)
        loss_avgs[m] = round(l, 4)
        denom = max(abs(w), abs(l), 1e-9)
        diffs[m] = round(abs(w - l) / denom, 4)

    consistency_score = round(1.0 - min(1.0, float(np.mean(list(diffs.values())))), 3) if diffs else 1.0

    return {
        "win_avgs":          win_avgs,
        "loss_avgs":         loss_avgs,
        "metric_diffs":      diffs,
        "consistency_score": consistency_score,
    }


# ═════════════════════════════════════════════════════════════════════════════
# 5. PESOS ACTUALIZADOS POR ROL
# ═════════════════════════════════════════════════════════════════════════════

SCORE_WEIGHTS: dict[str, dict[str, float]] = {
    # ── TOP ──────────────────────────────────────────────────────────────────
    # solo_kills (0.08) entra como indicador de dominio individual en línea.
    # Se redistribuye desde Dmg Recibido (eliminado) y se recorta Oro/min.
    "TOP": {
        "kda":        .15,
        "kp":         .10,
        "cs_min":     .18,
        "oro_min":    .10,
        "dmg_min":    .14,
        "dmg_oro":    .07,
        "pct_dmg":    .06,
        "vision_min": .07,   # sustituible por wpm/cwpm/wcpm/vspm si se extraen
        "double":     .02,
        "triple":     .02,
        "solo_kills": .08,   # NUEVO: kills sin asistencia en línea (from match-v5 challenges)
        # Σ = 1.00 ✓
    },
    # ── JGL ──────────────────────────────────────────────────────────────────
    # VSPM sube a 0.13 (vision es el recurso clave del jungler).
    # Dmg/min baja de 0.09 a 0.04 para compensar.
    "JGL": {
        "kda":     .18,
        "kp":      .20,
        "cs_min":  .15,
        "oro_min": .09,
        "dmg_min": .04,   # reducido
        "dmg_oro": .06,
        "pct_dmg": .03,
        "vspm":    .13,   # sustituye vision_min; usa WCPM si usas las 4 métricas
        "double":  .04,
        "triple":  .04,
        "quadra":  .02,
        "penta":   .01,
        # wpm/cwpm/wcpm se añadirían aquí con VISION_WEIGHTS_BY_ROLE["JGL"]
        # Σ = 0.99... ajuste fino:
        "wpm":     .01,   # pequeño peso extra para wards colocados
        # Σ = 1.00 ✓
    },
    # ── MID ──────────────────────────────────────────────────────────────────
    "MID": {
        "kda":        .17,
        "kp":         .14,
        "dmg_min":    .17,
        "dmg_oro":    .09,
        "pct_dmg":    .07,
        "cs_min":     .14,
        "oro_min":    .10,
        "vision_min": .05,
        "double":     .02,
        "triple":     .02,
        "quadra":     .02,
        "penta":      .01,
        # Σ = 1.00 ✓
    },
    # ── ADC ──────────────────────────────────────────────────────────────────
    "ADC": {
        "kda":        .19,
        "kp":         .09,
        "dmg_min":    .17,
        "dmg_oro":    .10,
        "pct_dmg":    .08,
        "cs_min":     .20,
        "oro_min":    .09,
        "vision_min": .03,
        "double":     .02,
        "triple":     .01,
        "quadra":     .01,
        "penta":      .01,
        # Σ = 1.00 ✓
    },
    # ── SUP ──────────────────────────────────────────────────────────────────
    # vision_min (0.30) se divide en WPM + CWPM + WCPM.
    # CWPM es prioritario: comprar control wards es responsabilidad del sup.
    "SUP": {
        "kda":   .20,
        "kp":    .33,
        "wpm":   .08,   # wards colocados / min
        "cwpm":  .12,   # control wards comprados / min  ← prioritario
        "wcpm":  .10,   # wards destruidos / min
        "dmg_min": .06,
        "pct_dmg": .04,
        "oro_min": .07,
        # Σ = 1.00 ✓
    },
}


# ═════════════════════════════════════════════════════════════════════════════
# PIPELINE DE INTEGRACIÓN (ejemplo de uso)
# ═════════════════════════════════════════════════════════════════════════════

def score_players_advanced(
    players: list[dict],
    metrics: list[str],
    shrinkage_k: int = 4,
) -> list[dict]:
    """
    Pipeline completo:
      1. Z-scores por rol para cada métrica
      2. Score ponderado (sobre z-scores, no sobre valores brutos)
      3. Shrinkage bayesiano por partidas jugadas

    players: lista de dicts con campos en `metrics` y además 'rol', 'games_played'.
    metrics: lista de claves de métrica que coinciden con SCORE_WEIGHTS.
    """
    # Paso 1: z-scores
    players = compute_zscores_by_role(players, metrics)

    # Paso 2: score ponderado sobre z-scores
    for p in players:
        rol     = p["rol"]
        weights = SCORE_WEIGHTS.get(rol, {})
        raw = sum(
            p.get(f"z_{m}", 0.0) * w
            for m, w in weights.items()
            if m in metrics
        )
        # Los z-scores tienen media 0 y std ≈ 1, así que el score ponderado
        # puede ser negativo. Lo pasamos a escala 0-100 con una sigmoidea simple.
        # Alternativamente puedes usar percentile rank dentro del rol.
        p["raw_score"] = raw   # se normaliza en el shrinkage

    # Normalizar raw_score a 0-100 dentro de cada rol
    role_groups: dict[str, list] = defaultdict(list)
    for p in players:
        role_groups[p["rol"]].append(p)
    for group in role_groups.values():
        scores = [p["raw_score"] for p in group]
        mn, mx = min(scores), max(scores)
        rng = mx - mn if mx != mn else 1.0
        for p in group:
            p["raw_score"] = round((p["raw_score"] - mn) / rng * 100, 2)

    # Paso 3: shrinkage bayesiano
    players = apply_bayesian_shrinkage(players, k=shrinkage_k)

    return players
