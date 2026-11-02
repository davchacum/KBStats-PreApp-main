"""
Páginas de la app: portada, buscador, perfil de jugador y perfil de equipo.
"""
from collections import Counter, defaultdict

from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from . import scoring
from .models import Equipo, Jugador, Partida, StatsJugador, Temporada
from .temporadas import temporada_de
from .templatetags.kb import icono_campeon, icono_perfil, jornada_txt, nota_clase, rol_corto
from .views import calcular_clasificacion, orden_partida, partidas_de


# ─────────────────────────── utilidades ───────────────────────────

def iniciales_equipo(nombre):
    """'KB KAIJU' → 'KAI'; 'Team Rocket' → 'TR'."""
    palabras = [p for p in (nombre or '').split() if p.upper() != 'KB']
    if not palabras:
        return (nombre or '?')[:3].upper()
    if len(palabras) == 1:
        return palabras[0][:3].upper()
    return ''.join(p[0] for p in palabras[:3]).upper()


def _ladder(nombres):
    """Rango de SoloQ de cada jugador, si está en el ladder."""
    try:
        from KBStats.Kblix.models import LadderPlayer
    except ImportError:
        return {}
    return {p.nombre: p for p in LadderPlayer.objects.filter(nombre__in=list(nombres))}


def _kda(k, d, a):
    return round((k + a) / d, 2) if d else float(k + a)


def _resumen_partidas(partidas, resultados, stats_por_partida):
    """Datos para las filas de partidas: kills de cada lado, MVP y enlace."""
    filas = []
    for p in partidas:
        stats = stats_por_partida.get(p.id, [])
        azul = p.equipo_azul.nombre if p.equipo_azul else ''
        rojo = p.equipo_rojo.nombre if p.equipo_rojo else ''
        k_azul = sum(s.kills or 0 for s in stats if s.equipo_nombre == azul)
        k_rojo = sum(s.kills or 0 for s in stats if s.equipo_nombre == rojo)
        mvp = next((s for s in stats if resultados.get(s.id, {}).get('insignia') == 'MVP'), None)
        filas.append({
            'p': p,
            'azul': azul, 'rojo': rojo,
            'ini_azul': iniciales_equipo(azul), 'ini_rojo': iniciales_equipo(rojo),
            'k_azul': k_azul, 'k_rojo': k_rojo,
            'gana_azul': bool(p.ganador_equipo_id and p.ganador_equipo_id == p.equipo_azul_id),
            'gana_rojo': bool(p.ganador_equipo_id and p.ganador_equipo_id == p.equipo_rojo_id),
            'duracion': f'{p.duracion_segundos // 60}:{p.duracion_segundos % 60:02}',
            'mvp': mvp,
            'mvp_nota': resultados[mvp.id]['nota'] if mvp else None,
            'url': reverse('detalle_partida', args=[p.match_id]),
        })
    return filas


def _puntuar_partidas(partidas):
    """Puntúa todas las partidas dadas. Devuelve (resultados, stats agrupadas por partida)."""
    stats = list(StatsJugador.objects.filter(partida__in=partidas).select_related('jugador'))
    por_partida = defaultdict(list)
    for s in stats:
        por_partida[s.partida_id].append(s)
    return scoring.puntuar_stats(stats), por_partida


def _temporada_perfil(request, partidas_qs):
    """
    Qué temporada enseña un perfil (jugador o equipo): la que se está viendo si jugó en ella; si no, la última
    en la que jugó. Con ?temporada=todas, todas (devuelve None).
    Devuelve (temporada o None, temporadas en las que jugó de la más reciente a la más antigua, ver_todas).
    """
    ids = set(partidas_qs.exclude(temporada__isnull=True).values_list('temporada_id', flat=True))
    propias = list(Temporada.objects.filter(id__in=ids).order_by('-orden'))
    if request.GET.get('temporada') == 'todas' and len(propias) > 1:
        return None, propias, True
    vista = temporada_de(request)
    if vista and vista.id in ids:
        return vista, propias, False
    return (propias[0] if propias else None), propias, False


# ─────────────────────────── portada ───────────────────────────

def inicio(request):
    partidas = sorted(partidas_de(request).select_related('equipo_azul', 'equipo_rojo', 'ganador_equipo', 'temporada'), key=orden_partida)
    resultados, por_partida = _puntuar_partidas(partidas)

    ultima_jornada = partidas[-1].jornada if partidas else None
    recientes = [p for p in partidas if p.jornada == ultima_jornada]

    todas = [s for lista in por_partida.values() for s in lista]
    ranking = scoring.ranking_jugadores(todas, resultados)
    ranking_fiable = [f for f in ranking if f['partidas'] >= 3] or ranking
    mejores_por_rol = []
    for rol in scoring.ROLES:
        del_rol = [f for f in ranking_fiable if f['rol'] == rol]
        if del_rol:
            mejores_por_rol.append(del_rol[0])

    # Campeón más jugado de cada jugador, para el icono
    campeon_fav = {}
    for jid, c in _campeones_favoritos(todas).items():
        campeon_fav[jid] = c

    ladder = []
    try:
        from KBStats.Kblix.models import LadderPlayer
        jugadores_ladder = sorted(
            LadderPlayer.objects.exclude(riot_id='').exclude(tier='').exclude(tier='UNRANKED'),
            key=lambda p: -p.rank_score,
        )[:6]
        con_stats = set(Jugador.objects.filter(nombre__in=[p.nombre for p in jugadores_ladder]).values_list('nombre', flat=True))
        for p in jugadores_ladder:
            ladder.append({'p': p, 'tiene_perfil': p.nombre in con_stats})
    except ImportError:
        pass

    clasificacion = calcular_clasificacion(temporada_de(request))
    for grupo in clasificacion:
        for i, eq in enumerate(grupo['equipos'], start=1):
            eq['pos'] = i
            eq['ini'] = iniciales_equipo(eq['equipo'])

    for f in mejores_por_rol + ranking_fiable[:8]:
        f['campeon_fav'] = campeon_fav.get(f['jugador_id'])

    return render(request, 'Cinturones/index.html', {
        'total_partidas': len(partidas),
        'total_jugadores': len({s.jugador_id for s in todas}),
        'total_equipos': len({p.equipo_azul_id for p in partidas} | {p.equipo_rojo_id for p in partidas}),
        'total_jornadas': len({p.jornada for p in partidas}),
        'ultima_jornada': ultima_jornada,
        'recientes': _resumen_partidas(recientes, resultados, por_partida),
        'mejores_por_rol': mejores_por_rol,
        'top': ranking_fiable[:8],
        'ladder': ladder,
        'clasificacion': clasificacion,
    })


def _campeones_favoritos(stats):
    conteo = defaultdict(Counter)
    for s in stats:
        if s.campeon:
            conteo[s.jugador_id][s.campeon] += 1
    return {jid: c.most_common(1)[0][0] for jid, c in conteo.items()}


# ─────────────────────────── buscador ───────────────────────────

def buscar(request):
    q = (request.GET.get('q') or '').strip()
    jugadores, equipos = [], []
    if q:
        candidatos = list(Jugador.objects.filter(nombre__icontains=q, stats__isnull=False).distinct()[:40])
        # Primero los que empiezan por lo buscado
        candidatos.sort(key=lambda j: (not j.nombre.lower().startswith(q.lower()), j.nombre.lower()))
        candidatos = candidatos[:8]
        stats = StatsJugador.objects.filter(jugador__in=candidatos).select_related('partida__temporada')
        info = defaultdict(lambda: {'roles': Counter(), 'campeones': Counter(), 'equipo': '', 'orden': None, 'perfil': None})
        for s in stats:
            d = info[s.jugador_id]
            if s.rol:
                d['roles'][s.rol] += 1
            if s.campeon:
                d['campeones'][s.campeon] += 1
            clave = orden_partida(s.partida)
            if d['orden'] is None or clave > d['orden']:
                d['orden'], d['equipo'] = clave, s.equipo_nombre
                d['perfil'] = (s.riot_extra or {}).get('profileIcon')
        for j in candidatos:
            d = info[j.id]
            nombre, _, tag = j.nombre.partition('#')
            jugadores.append({
                'nombre': nombre, 'tag': f'#{tag}' if tag else '',
                'equipo': d['equipo'],
                'rol': rol_corto(d['roles'].most_common(1)[0][0]) if d['roles'] else '',
                'rol_clave': d['roles'].most_common(1)[0][0] if d['roles'] else '',
                'icono': icono_perfil(d['perfil']) if d['perfil'] is not None else (icono_campeon(d['campeones'].most_common(1)[0][0]) if d['campeones'] else ''),
                'url': reverse('jugador', args=[j.nombre]),
            })
        for e in Equipo.objects.filter(nombre__icontains=q).order_by('nombre')[:6]:
            n = Partida.objects.filter(Q(equipo_azul=e) | Q(equipo_rojo=e)).count()
            if not n:
                continue
            equipos.append({
                'nombre': e.nombre, 'ini': iniciales_equipo(e.nombre),
                'sub': f'{n} partida{"s" if n != 1 else ""}',
                'url': reverse('equipo', args=[e.nombre]),
            })

    if request.GET.get('format') == 'json':
        return JsonResponse({'jugadores': jugadores, 'equipos': equipos})

    # Un único resultado: directo a su página
    if len(jugadores) + len(equipos) == 1:
        return redirect((jugadores or equipos)[0]['url'])
    return render(request, 'Cinturones/busqueda.html', {'q': q, 'jugadores': jugadores, 'equipos': equipos})


# ─────────────────────────── perfil de jugador ───────────────────────────

def jugador(request, nombre):
    j = get_object_or_404(Jugador, nombre=nombre)
    t, temporadas_propias, ver_todas = _temporada_perfil(request, Partida.objects.filter(stats_jugadores__jugador=j))
    qs_propias = StatsJugador.objects.filter(jugador=j)
    if t:
        qs_propias = qs_propias.filter(partida__temporada=t)
    propias = list(qs_propias.select_related('partida__equipo_azul', 'partida__equipo_rojo', 'partida__ganador_equipo', 'partida__temporada'))
    propias.sort(key=lambda s: orden_partida(s.partida))
    partidas = [s.partida for s in propias]
    resultados, por_partida = _puntuar_partidas(partidas)

    # Posición en la tier list de la temporada (o de todas)
    todas = list((StatsJugador.objects.filter(partida__temporada=t) if t else StatsJugador.objects).select_related('jugador'))
    resultados_liga = scoring.puntuar_stats(todas)
    ranking = scoring.ranking_jugadores(todas, resultados_liga)
    fila_rank = next((f for f in ranking if f['jugador_id'] == j.id), None)
    puesto_rol = None
    if fila_rank:
        del_rol = [f for f in ranking if f['rol'] == fila_rank['rol']]
        puesto_rol = (del_rol.index(fila_rank) + 1, len(del_rol))

    n = len(propias)
    k = sum(s.kills or 0 for s in propias)
    d = sum(s.muertes or 0 for s in propias)
    a = sum(s.asistencias or 0 for s in propias)
    victorias = sum(1 for s in propias if s.victoria)

    def media(campo):
        vals = [getattr(s, campo) or 0 for s in propias]
        return sum(vals) / len(vals) if vals else 0

    notas = [resultados[s.id]['nota'] for s in propias]
    resumen = {
        'partidas': n, 'victorias': victorias, 'derrotas': n - victorias,
        'winrate': round(100 * victorias / n) if n else 0,
        'k': k / n if n else 0, 'd': d / n if n else 0, 'a': a / n if n else 0,
        'kda': _kda(k, d, a),
        'kp': media('kp_porcentaje'), 'cs_min': media('cs_min'), 'dano_min': media('dano_min'),
        'oro_min': media('oro_min'), 'vision_min': media('vision_min'), 'pct_dano': media('porcentaje_dano_equipo'),
        'nota': sum(notas) / len(notas) if notas else None,
        'mvp': sum(1 for s in propias if resultados[s.id].get('insignia') == 'MVP'),
        'ace': sum(1 for s in propias if resultados[s.id].get('insignia') == 'ACE'),
    }

    # Campeones
    por_campeon = defaultdict(list)
    for s in propias:
        por_campeon[s.campeon or '?'].append(s)
    campeones = []
    for camp, lista in por_campeon.items():
        ck = sum(s.kills or 0 for s in lista)
        cd = sum(s.muertes or 0 for s in lista)
        ca = sum(s.asistencias or 0 for s in lista)
        cv = sum(1 for s in lista if s.victoria)
        campeones.append({
            'campeon': camp, 'partidas': len(lista), 'victorias': cv,
            'winrate': round(100 * cv / len(lista)),
            'kda': _kda(ck, cd, ca),
            'k': ck / len(lista), 'd': cd / len(lista), 'a': ca / len(lista),
            'cs_min': sum(s.cs_min or 0 for s in lista) / len(lista),
            'nota': sum(resultados[s.id]['nota'] for s in lista) / len(lista),
        })
    campeones.sort(key=lambda c: (-c['partidas'], -c['nota']))

    roles = Counter((s.rol or '').upper() for s in propias)
    rol_principal = roles.most_common(1)[0][0] if roles else ''

    # Historial (más reciente primero)
    historial = []
    for s in reversed(propias):
        p = s.partida
        r = resultados[s.id]
        rival = p.equipo_rojo.nombre if s.equipo_nombre == (p.equipo_azul.nombre if p.equipo_azul else None) else (p.equipo_azul.nombre if p.equipo_azul else '')
        compis_kills = sum(x.kills or 0 for x in por_partida[p.id] if x.equipo_nombre == s.equipo_nombre)
        historial.append({
            's': s, 'p': p, 'r': r, 'rival': rival,
            'duracion': f'{p.duracion_segundos // 60}:{p.duracion_segundos % 60:02}',
            'kda': _kda(s.kills or 0, s.muertes or 0, s.asistencias or 0),
            'kills_equipo': compis_kills,
            'url': reverse('detalle_partida', args=[p.match_id]),
        })

    # Evolución de la nota: línea en SVG y un punto por partida con su ficha al pasar el ratón.
    # El SVG se estira al ancho de la tarjeta, así que los puntos van en HTML (en %) para que sigan redondos.
    evolucion = None
    if len(notas) >= 2:
        ancho, alto, mx, my = 300, 64, 6, 6   # márgenes para que los puntos de los extremos no se corten
        paso = (ancho - 2 * mx) / (len(notas) - 1)
        y_de = lambda v: round(alto - my - (v / 100) * (alto - 2 * my), 1)
        puntos = [(round(mx + i * paso, 1), y_de(v)) for i, v in enumerate(notas)]
        hist_de = {h['s'].id: h for h in historial}
        fichas = []
        for s, (x, y), v in zip(propias, puntos, notas):
            r = resultados[s.id]
            h = hist_de[s.id]
            fichas.append({
                'id': s.id, 'x': round(100 * x / ancho, 2), 'y': round(100 * y / alto, 2),
                'nota': round(v), 'clase': nota_clase(v), 'url': h['url'],
                'temporada': s.partida.temporada.nombre if s.partida.temporada else '',
                'jornada': jornada_txt(s.partida.jornada), 'g': s.partida.numero_partida,
                'campeon': s.campeon or '', 'rival': h['rival'], 'victoria': bool(s.victoria),
                'kda': f'{s.kills or 0}/{s.muertes or 0}/{s.asistencias or 0}',
                'insignia': r.get('insignia') or '', 'puesto': r.get('puesto'),
            })
        evolucion = {
            'ancho': ancho, 'alto': alto,
            'linea': ' '.join(f'{x},{y}' for x, y in puntos),
            'area': f'{mx},{alto} ' + ' '.join(f'{x},{y}' for x, y in puntos) + f' {ancho - mx},{alto}',
            'puntos': fichas,
            'media_y': y_de(sum(notas) / len(notas)),
        }

    equipo_actual = propias[-1].equipo_nombre if propias else ''
    ultimo_extra = (propias[-1].riot_extra or {}) if propias else {}
    nombre_juego, _, tag = j.nombre.partition('#')
    ladder = _ladder([j.nombre]).get(j.nombre)

    return render(request, 'Cinturones/jugador.html', {
        'j': j, 'nombre_juego': nombre_juego, 'tag': f'#{tag}' if tag else '',
        'perfil_icono': ultimo_extra.get('profileIcon'), 'nivel': ultimo_extra.get('summonerLevel'),
        'equipo_actual': equipo_actual, 'ini_equipo': iniciales_equipo(equipo_actual),
        'rol_principal': rol_principal, 'roles': roles.most_common(),
        'resumen': resumen, 'campeones': campeones, 'historial': historial,
        'campeon_fav': campeones[0]['campeon'] if campeones else None,
        'fila_rank': fila_rank, 'puesto_rol': puesto_rol,
        'evolucion': evolucion, 'ladder': ladder,
        'desgloses': {s.id: {**resultados[s.id], 'nombre': j.nombre, 'campeon': s.campeon} for s in propias},
        'temporada_vista': t, 'temporadas_propias': temporadas_propias, 'ver_todas': ver_todas,
    })


# ─────────────────────────── perfil de equipo ───────────────────────────

def equipo(request, nombre):
    e = get_object_or_404(Equipo, nombre=nombre)
    del_equipo = Partida.objects.filter(Q(equipo_azul=e) | Q(equipo_rojo=e))
    t, temporadas_propias, ver_todas = _temporada_perfil(request, del_equipo)
    if t:
        del_equipo = del_equipo.filter(temporada=t)
    partidas = sorted(del_equipo.select_related('equipo_azul', 'equipo_rojo', 'ganador_equipo', 'temporada'), key=orden_partida)
    resultados, por_partida = _puntuar_partidas(partidas)

    victorias = sum(1 for p in partidas if p.ganador_equipo_id == e.id)
    n = len(partidas)

    # Plantilla: jugadores que han jugado con este equipo
    propias = [s for p in partidas for s in por_partida[p.id] if s.equipo_nombre == e.nombre]
    por_jug = defaultdict(list)
    for s in propias:
        por_jug[s.jugador_id].append(s)
    orden_rol = {r: i for i, r in enumerate(scoring.ROLES)}
    plantilla = []
    for jid, lista in por_jug.items():
        roles = Counter((s.rol or '').upper() for s in lista)
        rol = roles.most_common(1)[0][0]
        k = sum(s.kills or 0 for s in lista)
        d = sum(s.muertes or 0 for s in lista)
        a = sum(s.asistencias or 0 for s in lista)
        camps = Counter(s.campeon for s in lista if s.campeon)
        plantilla.append({
            'nombre': lista[0].jugador.nombre, 'rol': rol, 'partidas': len(lista),
            'kda': _kda(k, d, a), 'k': k / len(lista), 'd': d / len(lista), 'a': a / len(lista),
            'nota': sum(resultados[s.id]['nota'] for s in lista) / len(lista),
            'mvp': sum(1 for s in lista if resultados[s.id].get('insignia') == 'MVP'),
            'campeones': [c for c, _ in camps.most_common(3)],
        })
    plantilla.sort(key=lambda f: (orden_rol.get(f['rol'], 9), -f['partidas']))

    # Medias del equipo
    def lado(p):
        return 'azul' if p.equipo_azul_id == e.id else 'rojo'

    duraciones = [p.duracion_segundos for p in partidas]
    dragones = [p.dragones_azul if lado(p) == 'azul' else p.dragones_rojo for p in partidas]
    barones = [p.barones_azul if lado(p) == 'azul' else p.barones_rojo for p in partidas]
    kills_eq = [sum(s.kills or 0 for s in por_partida[p.id] if s.equipo_nombre == e.nombre) for p in partidas]
    kills_riv = [sum(s.kills or 0 for s in por_partida[p.id] if s.equipo_nombre != e.nombre) for p in partidas]
    medias = {
        'duracion': (lambda s: f'{s // 60}:{s % 60:02}')(int(sum(duraciones) / n)) if n else '—',
        'dragones': sum(dragones) / n if n else 0,
        'barones': sum(barones) / n if n else 0,
        'kills': sum(kills_eq) / n if n else 0,
        'kills_riv': sum(kills_riv) / n if n else 0,
        'lado_azul': sum(1 for p in partidas if lado(p) == 'azul'),
        'lado_azul_v': sum(1 for p in partidas if lado(p) == 'azul' and p.ganador_equipo_id == e.id),
        'lado_rojo_v': sum(1 for p in partidas if lado(p) == 'rojo' and p.ganador_equipo_id == e.id),
    }
    medias['lado_rojo'] = n - medias['lado_azul']

    # Posición en su grupo (de la temporada que se enseña)
    posicion = None
    for grupo in (calcular_clasificacion(t) if t else []):
        for i, eq in enumerate(grupo['equipos'], start=1):
            if eq['equipo'] == e.nombre:
                posicion = {'grupo': grupo['grupo'], 'pos': i, 'de': len(grupo['equipos'])}

    filas = _resumen_partidas(list(reversed(partidas)), resultados, por_partida)
    for f in filas:
        f['gana'] = f['p'].ganador_equipo_id == e.id
        f['es_azul'] = f['p'].equipo_azul_id == e.id
        f['rival'] = f['rojo'] if f['es_azul'] else f['azul']
        f['k_propias'] = f['k_azul'] if f['es_azul'] else f['k_rojo']
        f['k_rival'] = f['k_rojo'] if f['es_azul'] else f['k_azul']
        mvp_eq = max((s for s in por_partida[f['p'].id] if s.equipo_nombre == e.nombre), key=lambda s: resultados[s.id]['nota'], default=None)
        f['mejor'] = mvp_eq
        f['mejor_nota'] = resultados[mvp_eq.id]['nota'] if mvp_eq else None

    return render(request, 'Cinturones/equipo.html', {
        'e': e, 'ini': iniciales_equipo(e.nombre),
        'partidas': n, 'victorias': victorias, 'derrotas': n - victorias,
        'winrate': round(100 * victorias / n) if n else 0,
        'racha': ['v' if p.ganador_equipo_id == e.id else 'd' for p in partidas][-5:],
        'plantilla': plantilla, 'medias': medias, 'posicion': posicion,
        'filas': filas,
        'temporada_vista': t, 'temporadas_propias': temporadas_propias, 'ver_todas': ver_todas,
    })
