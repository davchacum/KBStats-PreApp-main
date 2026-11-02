"""
Recalcula las posiciones interpoladas del mapa de calor: de un punto cada ~6 s a uno cada 10 s.

Riot da una posición real por minuto (frame). Al importar, se guardaban 9 puntos intermedios
en línea recta entre cada par de frames, más la posición de eventos (kills, wards...).
Aquí se quitan esos 9 puntos y se ponen 5 (cada 10 s), sin tocar frames ni eventos,
así que no hace falta volver a pedir nada a la API de Riot.
"""
from django.db import migrations


def _interpolados(a, b, steps):
    """Puntos intermedios entre dos frames, calculados igual que en extract_positions_from_timeline."""
    (px, py, pt), (cx, cy, ft) = a, b
    out = []
    for step in range(1, steps + 1):
        frac = step / (steps + 1)
        out.append([
            round(px + (cx - px) * frac),
            round(py + (cy - py) * frac),
            round(pt + (ft - pt) * frac),
        ])
    return out


def reinterpolar(position_data, pasos_antes, pasos_despues):
    players = (position_data or {}).get('players') or {}
    listas = [p.get('positions') or [] for p in players.values()]
    if not listas or any(not pts or len(pts[0]) < 3 for pts in listas):
        return None  # sin datos o formato antiguo [x, y]: no se toca

    # Los frames y sus puntos interpolados caen en el mismo instante para los 10 jugadores
    # (los eventos no), y van en bloques: frame, N interpolados, frame, ... El último frame
    # es el final de la partida, que no cae en un minuto exacto.
    bloque = pasos_antes + 1
    comunes = sorted(set.intersection(*({pt[2] for pt in pts} for pts in listas)))
    if len(comunes) < 2 or len(comunes) % bloque != 1:
        return None  # no encaja con el patrón esperado: mejor no tocarla
    tiempos_frame = set(comunes[::bloque])

    nuevas = {}
    for pid, p in players.items():
        pts = p['positions']
        por_tiempo = {}
        for x, y, t in pts:
            if t in tiempos_frame:
                por_tiempo.setdefault(t, (x, y, t))
        frames = [por_tiempo[t] for t in sorted(tiempos_frame) if t in por_tiempo]
        if len(frames) != len(tiempos_frame):
            return None

        # Puntos interpolados antiguos: tienen que estar todos, si no algo no cuadra
        viejos = [tuple(q) for a, b in zip(frames, frames[1:]) for q in _interpolados(a, b, pasos_antes)]
        actuales = {tuple(pt) for pt in pts}
        if not all(q in actuales for q in viejos):
            return None
        viejos = set(viejos)

        conservados = [pt for pt in pts if tuple(pt) not in viejos]
        nuevos = [q for a, b in zip(frames, frames[1:]) for q in _interpolados(a, b, pasos_despues)]
        nuevas[pid] = sorted(conservados + nuevos, key=lambda q: q[2])

    for pid, pts in nuevas.items():
        players[pid]['positions'] = pts
    return position_data


def a_10s(apps, schema_editor):
    Partida = apps.get_model('Cinturones', 'Partida')
    for partida in Partida.objects.exclude(position_data__isnull=True).iterator():
        nuevo = reinterpolar(partida.position_data, pasos_antes=9, pasos_despues=5)
        if nuevo is not None:
            partida.position_data = nuevo
            partida.save(update_fields=['position_data'])


def a_6s(apps, schema_editor):
    Partida = apps.get_model('Cinturones', 'Partida')
    for partida in Partida.objects.exclude(position_data__isnull=True).iterator():
        nuevo = reinterpolar(partida.position_data, pasos_antes=5, pasos_despues=9)
        if nuevo is not None:
            partida.position_data = nuevo
            partida.save(update_fields=['position_data'])


class Migration(migrations.Migration):

    dependencies = [
        ('Cinturones', '0008_statsjugador_early_game'),
    ]

    operations = [
        migrations.RunPython(a_10s, a_6s),
    ]
