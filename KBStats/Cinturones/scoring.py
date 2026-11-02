"""
Nota de rendimiento por partida (0-100).

  · Cada estadística da puntos dentro de 5 bloques: Global, vs Rival, Objetivos, Equipo y el bloque del rol.
  · Las estadísticas que se cuentan (kills, muertes, dragones, torres...) dan puntos fijos por unidad.
  · Las estadísticas por minuto (CS, oro, daño, visión, CS a los 10 min) se comparan con la media
    del mismo rol en la liga.
  · Nota = 15 + 0,97 × suma de puntos + 6 si se gana, entre 0 y 100.
  · Ajuste por rol: el support no suma CS, daño a objetivos ni ventaja de CS, así que de media
    saca menos puntos. Cada rol recibe la diferencia entre su media y la media de los 5 roles,
    para que la nota media de todos los roles sea la misma y se puedan comparar.
"""
import math
from collections import defaultdict

from django.db.models import Max

from .models import StatsJugador

ROLES = ('TOP', 'JGL', 'MID', 'ADC', 'SUP')
ROL_TXT = {'TOP': 'Top', 'JGL': 'Jungla', 'MID': 'Mid', 'ADC': 'ADC', 'SUP': 'Support'}

NOTA_BASE = 15.0
NOTA_PENDIENTE = 0.97
NOTA_VICTORIA = 6.0

# Escala de puntos de las estadísticas por minuto: (puntos medios, puntos por desviación típica, mínimo, máximo).
ESCALAS = {
    'cs_min': {'TOP': (6, 3, 0, 12), 'MID': (6, 3, 0, 12), 'ADC': (6, 3, 0, 12), 'JGL': (3, 2, 0, 8)},
    'oro_min': {'TOP': (6, 3, -3, 10), 'MID': (6, 3, -3, 10), 'ADC': (6, 3, -3, 10), 'JGL': (6, 3, -3, 10), 'SUP': (2.5, 1.5, -2, 6)},
    'dano_min': {'TOP': (6.5, 2.5, 0, 10), 'MID': (6.5, 2.5, 0, 10), 'ADC': (6.5, 2.5, 0, 10), 'JGL': (6, 2.5, 0, 10), 'SUP': (2, 1.5, 0, 6)},
    'vision_min': {'TOP': (3.5, 2, 0, 8), 'MID': (3.5, 2, 0, 8), 'ADC': (3, 1.5, 0, 7), 'JGL': (5, 2.5, 0, 9), 'SUP': (8, 2, 2, 12)},
    'cs10': {'TOP': (8, 4, -2, 16), 'MID': (8, 4, -2, 16), 'ADC': (7, 3.5, -2, 14)},
    'jcs10': {'JGL': (7, 2.5, 0, 10)},
}

# Puntos fijos por unidad
KILL = {'TOP': 0.8}                       # el resto, 0,75
ASIST = {'TOP': 0.8, 'SUP': 0.9}          # el resto, 0,75
MUERTE = {'SUP': -1.25}                   # el resto, -1,5
SIN_MUERTES = 4.0
FIRST_BLOOD = 5.0
DANO_OBJ_DIVISOR = {'TOP': 4000, 'MID': 4000, 'ADC': 8200, 'JGL': 20000}   # support: 0
DANO_RECIBIDO_PCT = {'TOP': 0.07, 'JGL': 0.05, 'MID': 0.05, 'ADC': 0.03, 'SUP': 0.0625}
DANO_CAUSADO_PCT = {'TOP': 0.09, 'JGL': 0.05, 'MID': 0.07, 'ADC': 0.10, 'SUP': 0.05}

# Referencia de "partida buena" de cada bloque para ponerle letra (S+ ... D)
REF_BLOQUE = {'global': 28, 'rival': 7, 'objetivos': 9, 'equipo': 6.5, 'rol': 13}
LETRAS = ((1.4, 'S+'), (1.2, 'S'), (1.0, 'A'), (0.75, 'B'), (0.5, 'C'))


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def letra(ratio):
    for umbral, l in LETRAS:
        if ratio >= umbral:
            return l
    return 'D'


def _num(v, defecto=0.0):
    try:
        return float(v) if v is not None else defecto
    except (TypeError, ValueError):
        return defecto


# ─────────────────────────── referencias de la liga ───────────────────────────

_cache_ref = {'clave': None, 'datos': None}


def _valores_por_minuto(s):
    ex = s.riot_extra or {}
    ch = ex.get('challenges') or {}
    vals = {
        'cs_min': _num(s.cs_min),
        'oro_min': _num(s.oro_min),
        'dano_min': _num(s.dano_min),
        'vision_min': _num(s.vision_min),
    }
    if ch.get('laneMinionsFirst10Minutes') is not None:
        vals['cs10'] = _num(ch.get('laneMinionsFirst10Minutes'))
    elif s.cs15 is not None:
        vals['cs10'] = s.cs15 * 10 / 15
    if ch.get('jungleCsBefore10Minutes') is not None:
        vals['jcs10'] = _num(ch.get('jungleCsBefore10Minutes'))
    return vals


def referencias():
    """Media y desviación típica de cada estadística por minuto, por rol, en toda la liga."""
    agg = StatsJugador.objects.aggregate(n=Max('id'))
    clave = (agg['n'], StatsJugador.objects.count())
    if _cache_ref['clave'] == clave:
        return _cache_ref['datos']

    muestras = defaultdict(lambda: defaultdict(list))
    for s in StatsJugador.objects.only('rol', 'cs_min', 'oro_min', 'dano_min', 'vision_min', 'cs15', 'riot_extra'):
        rol = (s.rol or '').upper()
        if rol not in ROLES:
            continue
        for k, v in _valores_por_minuto(s).items():
            muestras[rol][k].append(v)

    datos = {}
    for rol, stats in muestras.items():
        for k, vals in stats.items():
            if len(vals) < 2:
                continue
            media = sum(vals) / len(vals)
            sd = math.sqrt(sum((v - media) ** 2 for v in vals) / (len(vals) - 1)) or 1.0
            datos[(rol, k)] = (media, sd)

    _cache_ref.update(clave=clave, datos=datos)
    return datos


def _puntos_relativos(stat, rol, valor, refs):
    escala = ESCALAS.get(stat, {}).get(rol)
    ref = refs.get((rol, stat))
    if not escala or not ref or valor is None:
        return 0.0
    media_pts, sd_pts, lo, hi = escala
    media, sd = ref
    return _clamp(media_pts + sd_pts * (valor - media) / sd, lo, hi)


# ─────────────────────────── nota de un jugador en una partida ───────────────────────────

def _fila(etiqueta, valor, puntos, ayuda=''):
    return {'etiqueta': etiqueta, 'valor': valor, 'puntos': round(puntos, 1), 'ayuda': ayuda}


def _fmt(v, dec=1):
    if v is None:
        return '—'
    if isinstance(v, float):
        return f'{v:.{dec}f}'
    return str(v)


def puntuar_jugador(s, rival, compis, minutos, refs):
    """Devuelve los 5 bloques de puntos de un jugador (s) frente a su rival de rol."""
    rol = (s.rol or '').upper()
    ex = s.riot_extra or {}
    ch = ex.get('challenges') or {}
    rex = (rival.riot_extra or {}) if rival else {}
    rch = rex.get('challenges') or {}
    vals = _valores_por_minuto(s)
    largo = minutos >= 20

    # ── Global ──
    k, d, a = s.kills or 0, s.muertes or 0, s.asistencias or 0
    pts_muertes = SIN_MUERTES if d == 0 else d * MUERTE.get(rol, -1.5)
    fb_kill = bool(ex.get('firstBloodKill'))
    glob = [
        _fila('Kills', k, k * KILL.get(rol, 0.75)),
        _fila('Muertes', d, pts_muertes, 'Sin morir: +4'),
        _fila('Asistencias', a, a * ASIST.get(rol, 0.75)),
        _fila('CS/min', _fmt(vals['cs_min']), _puntos_relativos('cs_min', rol, vals['cs_min'], refs)),
        _fila('Oro/min', _fmt(vals['oro_min'], 0), _puntos_relativos('oro_min', rol, vals['oro_min'], refs)),
        _fila('Daño/min', _fmt(vals['dano_min'], 0), _puntos_relativos('dano_min', rol, vals['dano_min'], refs)),
        _fila('Visión/min', _fmt(vals['vision_min'], 2), _puntos_relativos('vision_min', rol, vals['vision_min'], refs)),
        _fila('First blood', 'Sí' if fb_kill else 'No', FIRST_BLOOD if fb_kill else 0),
    ]

    # ── vs Rival ──
    riv = []
    if rival:
        dif_xp = _num(ex.get('champExperience')) - _num(rex.get('champExperience'))
        dif_oro = _num(ex.get('goldEarned'), _num(s.oro_min) * minutos) - _num(rex.get('goldEarned'), _num(rival.oro_min) * minutos)
        dif_vis = _num(s.vision_min) - _num(rival.vision_min)
        por_min = max(minutos, 1)
        riv = [
            _fila('Dif. experiencia', f'{dif_xp:+.0f}', _clamp(dif_xp / por_min / 25, -6, 7)),
            _fila('Dif. oro', f'{dif_oro:+.0f}', _clamp(dif_oro / por_min / 25, -6, 10)),
            _fila('Dif. visión/min', f'{dif_vis:+.2f}', _clamp(dif_vis * 2.5, -2, 6)),
        ]
    if rol not in ('JGL', 'SUP'):
        max_cs = _num(ch.get('maxCsAdvantageOnLaneOpponent'))
        riv.append(_fila('Máx. ventaja de CS', _fmt(max_cs, 0), _clamp(max_cs * 0.08, 0, 8)))

    # ── Objetivos ──
    dragones = int(_num(ch.get('dragonTakedowns')))
    dano_obj = _num(ex.get('damageDealtToObjectives'))
    div = DANO_OBJ_DIVISOR.get(rol)
    obj = [
        _fila('Heraldo', int(_num(ch.get('riftHeraldTakedowns'))), 3 * _num(ch.get('riftHeraldTakedowns'))),
        _fila('Dragones', dragones, dragones * (2 if largo else 4), 'Valen el doble en partidas de menos de 20 min'),
        _fila('Barones', int(_num(ch.get('baronTakedowns'))), 2 * _num(ch.get('baronTakedowns'))),
        _fila('Larvas', int(_num(ch.get('voidMonsterKill'))), 0.5 * _num(ch.get('voidMonsterKill'))),
        _fila('Daño a objetivos', _fmt(dano_obj, 0), _clamp(dano_obj / div, 0, 4) if div else 0),
        _fila('Robos de objetivo', int(_num(ch.get('epicMonsterSteals'))), 3.5 * _num(ch.get('epicMonsterSteals'))),
    ]

    # ── Equipo ──
    kp = _num(s.kp_porcentaje)
    recibido = ch.get('damageTakenOnTeamPercentage')
    if recibido is None:
        total_rec = sum(_num(c.dano_recibido) for c in compis) or 1
        recibido = _num(s.dano_recibido) / total_rec
    recibido = _num(recibido) * 100
    causado = _num(s.porcentaje_dano_equipo)
    equipo = [
        _fila('Participación en kills', f'{kp:.0f}%', _clamp(0.125 * kp - 3.2, -2, 9)),
        _fila('% daño recibido', f'{recibido:.1f}%', recibido * DANO_RECIBIDO_PCT.get(rol, 0.05)),
        _fila('% daño causado', f'{causado:.1f}%', causado * DANO_CAUSADO_PCT.get(rol, 0.07)),
    ]

    # ── Bloque del rol ──
    if rol == 'SUP':
        picks = _num(ch.get('pickKillWithAlly'))
        rolb = [
            _fila('Pinks colocados', int(_num(ch.get('controlWardsPlaced'))), _clamp(0.5 * _num(ch.get('controlWardsPlaced')), 0, 3.5)),
            _fila('Wards destruidos', int(_num(ex.get('wardsKilled'))), _clamp(0.35 * _num(ex.get('wardsKilled')), 0, 3.5)),
            _fila('Wards colocados', int(_num(ex.get('wardsPlaced'))), _clamp(0.15 * _num(ex.get('wardsPlaced')), 0, 3.5)),
            _fila('Kills con aliado', int(picks), _clamp(6 * picks / max(minutos, 1), 0, 5)),
            _fila('Aliados salvados', int(_num(ch.get('saveAllyFromDeath'))), _clamp(_num(ch.get('saveAllyFromDeath')), 0, 3.5)),
        ]
    elif rol == 'JGL':
        picks = _num(ch.get('pickKillWithAlly'))
        cangrejo_ini = ch.get('initialCrabCount')
        rolb = [
            _fila('Cangrejo inicial', int(_num(cangrejo_ini)), (1.5 if _num(cangrejo_ini) >= 1 else -2.5) if cangrejo_ini is not None else 0),
            _fila('Cangrejos', int(_num(ch.get('scuttleCrabKills'))), _clamp(0.5 * _num(ch.get('scuttleCrabKills')), 0, 2)),
            _fila('CS de jungla a los 10', _fmt(vals.get('jcs10'), 0), _puntos_relativos('jcs10', rol, vals.get('jcs10'), refs)),
            _fila('Kills con aliado', int(picks), _clamp(7.5 * picks / max(minutos, 1), 0, 5)),
        ]
    else:
        # Placas que rompe el propio jugador (eventos del timeline). Sin datos, no puntúa.
        placas = ex.get('placas')
        rolb = [
            _fila('Kills en solitario', int(_num(ch.get('soloKills'))), _clamp(_num(ch.get('soloKills')) * (1.5 if rol == 'ADC' else 0.75), 0, 6)),
            _fila('Placas de torre', int(placas) if placas is not None else '—', _clamp(0.9 + 0.8 * placas, 0, 2.5) if placas is not None else 0),
            _fila('CS a los 10 min', _fmt(vals.get('cs10'), 0), _puntos_relativos('cs10', rol, vals.get('cs10'), refs)),
            _fila('Torres', int(_num(ch.get('turretTakedowns'))), _clamp(0.85 * _num(ch.get('turretTakedowns')), 0, 6)),
        ]

    bloques = [
        ('global', 'Global', glob),
        ('rival', 'vs Rival', riv),
        ('objetivos', 'Objetivos', obj),
        ('equipo', 'Equipo', equipo),
        ('rol', ROL_TXT.get(rol, 'Rol'), rolb),
    ]
    salida = []
    total = 0.0
    for clave, nombre, filas in bloques:
        pts = sum(f['puntos'] for f in filas)
        total += pts
        salida.append({
            'clave': clave, 'nombre': nombre, 'puntos': round(pts, 1),
            'letra': letra(pts / REF_BLOQUE[clave]), 'filas': filas,
        })
    return {'total': total, 'bloques': salida, 'victoria': bool(s.victoria), 'rol': rol}


def _nota(total, victoria):
    return _clamp(NOTA_BASE + NOTA_PENDIENTE * total + (NOTA_VICTORIA if victoria else 0), 0, 100)


_cache_aj = {'clave': None, 'datos': None}


def ajustes_rol():
    """Puntos que se suman a cada rol para que todos tengan la misma media en la liga."""
    agg = StatsJugador.objects.aggregate(n=Max('id'))
    clave = (agg['n'], StatsJugador.objects.count())
    if _cache_aj['clave'] == clave:
        return _cache_aj['datos']
    todas = list(StatsJugador.objects.all())
    crudos = puntuar_stats(todas, ajustar=False)
    por_rol = defaultdict(list)
    for r in crudos.values():
        if r['rol'] in ROLES:
            por_rol[r['rol']].append(r['total'])
    medias = {rol: sum(v) / len(v) for rol, v in por_rol.items() if v}
    media_roles = sum(medias.values()) / len(medias) if medias else 0
    datos = {rol: round(media_roles - m, 1) for rol, m in medias.items()}
    _cache_aj.update(clave=clave, datos=datos)
    return datos


def puntuar_stats(stats, ajustar=True):
    """
    Puntúa una lista de StatsJugador (de una o varias partidas).
    Devuelve {stats.id: resultado}, con nota, puesto en la partida (1-10) e insignia MVP / ACE.
    """
    refs = referencias()
    ajustes = ajustes_rol() if ajustar else {}
    por_partida = defaultdict(list)
    for s in stats:
        por_partida[s.partida_id].append(s)

    resultados = {}
    for _, jugadores in por_partida.items():
        minutos = max((_num(j.game_time) for j in jugadores), default=0) or 1
        for s in jugadores:
            rol = (s.rol or '').upper()
            compis = [j for j in jugadores if j.equipo_nombre == s.equipo_nombre]
            rival = next((j for j in jugadores if j.equipo_nombre != s.equipo_nombre and (j.rol or '').upper() == rol), None)
            r = puntuar_jugador(s, rival, compis, minutos, refs)
            r['ajuste'] = ajustes.get(rol, 0.0)
            r['nota'] = round(_nota(r['total'] + r['ajuste'], r['victoria']), 1)
            r['total'] = round(r['total'], 1)
            resultados[s.id] = r

        # Puesto en la partida, MVP (mejor del equipo ganador) y ACE (mejor del perdedor)
        orden = sorted(jugadores, key=lambda j: -resultados[j.id]['nota'])
        for i, j in enumerate(orden, start=1):
            resultados[j.id]['puesto'] = i
            resultados[j.id]['insignia'] = None
        ganadores = [j for j in orden if j.victoria]
        perdedores = [j for j in orden if not j.victoria]
        if ganadores:
            resultados[ganadores[0].id]['insignia'] = 'MVP'
        if perdedores:
            resultados[perdedores[0].id]['insignia'] = 'ACE'
    return resultados


def puntuar_partida(partida):
    stats = list(StatsJugador.objects.filter(partida=partida).select_related('jugador'))
    return puntuar_stats(stats)


# ─────────────────────────── tier list ───────────────────────────

# Cortes de cada tier por decenas de nota: S+ desde 90, S desde 80, A desde 70, B desde 60, C desde 50
TIERS = (('S+', 90), ('S', 80), ('A', 70), ('B', 60), ('C', 50))   # por debajo: D
PARTIDAS_PRIOR = 2.0   # peso de la media del rol para jugadores con pocas partidas


def tier_de(nota):
    for t, umbral in TIERS:
        if nota >= umbral:
            return t
    return 'D'


def ranking_jugadores(stats, resultados=None):
    """
    Agrega las notas por jugador en su rol principal.
    Devuelve una lista de dicts ordenada por nota, con tier, partidas, victorias, MVP/ACE y
    los puntos medios de cada bloque.

    Con pocas partidas la media es poco fiable, así que se mezcla con la media del rol como si
    el jugador tuviera PARTIDAS_PRIOR partidas más «normales». Con 1 partida su nota cuenta un
    tercio; con 6, tres cuartos.
    """
    stats = list(stats)
    if resultados is None:
        resultados = puntuar_stats(stats)

    por_jugador = defaultdict(list)
    for s in stats:
        if s.id in resultados:
            por_jugador[s.jugador_id].append(s)

    # Rol principal: el más jugado
    filas = []
    for jid, lista in por_jugador.items():
        conteo = defaultdict(int)
        for s in lista:
            conteo[(s.rol or '').upper()] += 1
        rol = max(conteo, key=lambda r: (conteo[r], r in ROLES))
        del_rol = [s for s in lista if (s.rol or '').upper() == rol]
        notas = [resultados[s.id]['nota'] for s in del_rol]
        bloques = defaultdict(float)
        for s in del_rol:
            for b in resultados[s.id]['bloques']:
                bloques[b['clave']] += b['puntos'] / len(del_rol)
        filas.append({
            'jugador_id': jid,
            'jugador_nombre': lista[0].jugador.nombre,
            'equipo': lista[-1].equipo_nombre,
            'rol': rol,
            'partidas': len(del_rol),
            'partidas_total': len(lista),
            'victorias': sum(1 for s in del_rol if s.victoria),
            'mvp': sum(1 for s in del_rol if resultados[s.id].get('insignia') == 'MVP'),
            'ace': sum(1 for s in del_rol if resultados[s.id].get('insignia') == 'ACE'),
            'media': sum(notas) / len(notas),
            'mejor': max(notas),
            'bloques': {k: round(v, 1) for k, v in bloques.items()},
            'kills': sum(s.kills or 0 for s in del_rol),
            'muertes': sum(s.muertes or 0 for s in del_rol),
            'asistencias': sum(s.asistencias or 0 for s in del_rol),
            'campeones': sorted({s.campeon for s in del_rol if s.campeon}),
            'perfil': next(((s.riot_extra or {}).get('profileIcon') for s in sorted(lista, key=lambda x: -x.partida_id)
                            if (s.riot_extra or {}).get('profileIcon') is not None), None),
        })

    medias_rol = defaultdict(list)
    for f in filas:
        medias_rol[f['rol']].append(f['media'])
    media_de_rol = {r: sum(v) / len(v) for r, v in medias_rol.items()}

    for f in filas:
        prior = media_de_rol.get(f['rol'], f['media'])
        f['nota'] = round((f['media'] * f['partidas'] + prior * PARTIDAS_PRIOR) / (f['partidas'] + PARTIDAS_PRIOR), 1)
        f['media'] = round(f['media'], 1)
        f['tier'] = tier_de(f['nota'])
        f['winrate'] = round(100 * f['victorias'] / f['partidas']) if f['partidas'] else 0
        m = f['muertes']
        f['kda'] = round((f['kills'] + f['asistencias']) / m, 2) if m else float(f['kills'] + f['asistencias'])
    filas.sort(key=lambda f: -f['nota'])
    return filas


def color_nota(nota):
    """Clase de color para una nota (para las insignias de la interfaz)."""
    if nota is None:
        return 'n-sin'
    if nota >= 90:
        return 'n-top'
    if nota >= 70:
        return 'n-alta'
    if nota >= 60:
        return 'n-media'
    if nota >= 50:
        return 'n-baja'
    return 'n-mala'
