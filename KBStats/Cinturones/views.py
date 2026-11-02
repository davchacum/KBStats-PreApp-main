import csv
from functools import cmp_to_key
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.db.models import Avg, Count, Sum
# from django.contrib.auth.decorators import user_passes_test  # DESACTIVADO
# from django.contrib import messages  # DESACTIVADO

from .models import Partida, StatsJugador
from .temporadas import temporada_de
from .utils import calculate_jungler_proximity, annotate_player_roles
# from .forms import AddPartidaForm  # DESACTIVADO
# from .utils import extract_match_data, save_to_django  # DESACTIVADO


def partidas_de(request):
	"""Partidas de la temporada que se está viendo (todas si aún no hay temporadas)."""
	t = temporada_de(request)
	return Partida.objects.filter(temporada=t) if t else Partida.objects.all()


def stats_de(request):
	"""Estadísticas de jugador de la temporada que se está viendo."""
	t = temporada_de(request)
	return StatsJugador.objects.filter(partida__temporada=t) if t else StatsJugador.objects.all()


def es_playoff(jornada):
	"""Rondas eliminatorias (no cuentan para la clasificación)."""
	j = (jornada or '').strip().upper()
	return j.startswith('PLAYOFF') or j in ('FINAL', 'SEMIFINAL', 'CUARTOS')


def orden_jornada(j):
	"""Orden cronológico de una jornada: 1, 2, ... · SUIZO 1, 2, ... · cuartos · semifinal · final."""
	j = (j or '').strip().upper()
	if j.isdigit():
		return (0, int(j))
	if j.startswith('SUIZO'):
		resto = j.replace('SUIZO', '').strip()
		return (1, int(resto) if resto.isdigit() else 0)
	for i, clave in enumerate(('CUARTOS', 'SEMIFINAL', 'FINAL')):
		if j.endswith(clave):
			return (2, i)
	return (3, 0)


def orden_partida(p):
	"""Clave de orden cronológico de una partida: temporada, jornada y game.
	Conviene traer la temporada con select_related('temporada') para no hacer una consulta por partida."""
	n = (p.numero_partida or '').strip()
	temporada = p.temporada.orden if p.temporada_id else 0
	return (temporada, orden_jornada(p.jornada), int(n) if n.isdigit() else 0, p.id)


def clasificacion_grupos(request):
	"""Muestra clasificación por grupo: PJ, V, D, % de victorias y racha de las últimas partidas."""
	temporada = temporada_de(request)
	clasificaciones = calcular_clasificacion(temporada)

	# Racha: resultados de cada equipo en orden cronológico (las 5 últimas).
	# Solo cuentan las mismas partidas que la clasificación: las de equipos que están en algún grupo.
	en_grupos = {eq['equipo'] for g in clasificaciones for eq in g['equipos']}
	resultados = {}
	for p in sorted(partidas_de(request).select_related('equipo_azul', 'equipo_rojo', 'ganador_equipo', 'temporada'), key=orden_partida):
		if not p.ganador_equipo or not p.equipo_azul or not p.equipo_rojo or es_playoff(p.jornada):
			continue
		if p.equipo_azul.nombre not in en_grupos or p.equipo_rojo.nombre not in en_grupos:
			continue
		for eq in (p.equipo_azul, p.equipo_rojo):
			if eq:
				resultados.setdefault(eq.nombre, []).append('v' if eq.id == p.ganador_equipo_id else 'd')
	for grupo in clasificaciones:
		for i, eq in enumerate(grupo['equipos'], start=1):
			eq['pos'] = i
			eq['racha'] = resultados.get(eq['equipo'], [])[-5:]
			eq['winrate'] = round(100 * eq['victorias'] / eq['jugados']) if eq['jugados'] else 0

	return render(request, 'Cinturones/clasificacion_grupos.html', {
		'clasificaciones': clasificaciones, 'con_grupos': bool(temporada and temporada.grupos),
	})


def calcular_clasificacion(temporada=None):
	"""
	Clasificación de cada grupo de la temporada, con los desempates de la liga. Sin contar los playoffs.
	Si la temporada no tiene grupos, una sola tabla con todos sus equipos.
	"""
	partidas = Partida.objects.filter(temporada=temporada) if temporada else Partida.objects.all()
	partidas = [p for p in partidas.select_related('equipo_azul', 'equipo_rojo', 'ganador_equipo') if not es_playoff(p.jornada)]
	grupos = list(temporada.grupos) if temporada and temporada.grupos else []
	if not grupos:
		equipos = sorted({p.equipo_azul.nombre for p in partidas} | {p.equipo_rojo.nombre for p in partidas})
		grupos = [{'nombre': 'Liga', 'equipos': equipos}] if equipos else []

	if not grupos:
		return []

	# Índice rápido para saber en qué grupo está cada equipo.
	equipo_a_grupo = {}
	for grupo in grupos:
		for equipo in grupo['equipos']:
			equipo_a_grupo[equipo] = grupo['nombre']

	clasificaciones = {
		grupo['nombre']: {
			'grupo': grupo['nombre'],
			'equipos': {
				equipo: {'equipo': equipo, 'jugados': 0, 'victorias': 0, 'derrotas': 0}
				for equipo in grupo['equipos']
			},
		}
		for grupo in grupos
	}
	# h2h_wins[grupo][equipo_a][equipo_b] = veces que A ganó a B
	h2h_wins = {
		grupo['nombre']: {
			equipo: {}
			for equipo in grupo['equipos']
		}
		for grupo in grupos
	}
	# Duraciones para desempates sin enfrentamiento directo.
	# Se guarda por separado para victorias y derrotas.
	duraciones = {
		grupo['nombre']: {
			equipo: {
				'victorias_seg_total': 0,
				'victorias_count': 0,
				'derrotas_seg_total': 0,
				'derrotas_count': 0,
			}
			for equipo in grupo['equipos']
		}
		for grupo in grupos
	}
	# Duración acumulada de enfrentamientos directos por pareja de equipos.
	# h2h_duracion_total[grupo][equipo][rival] = segundos totales jugados entre ambos.
	h2h_duracion_total = {
		grupo['nombre']: {
			equipo: {}
			for equipo in grupo['equipos']
		}
		for grupo in grupos
	}

	for partida in partidas:
		nombre_azul = partida.equipo_azul.nombre if partida.equipo_azul else None
		nombre_rojo = partida.equipo_rojo.nombre if partida.equipo_rojo else None
		if not nombre_azul or not nombre_rojo:
			continue

		grupo_azul = equipo_a_grupo.get(nombre_azul)
		grupo_rojo = equipo_a_grupo.get(nombre_rojo)

		# Solo ignorar partidas con equipos que no están en ningún grupo.
		if not grupo_azul or not grupo_rojo:
			continue

		stats_azul = clasificaciones[grupo_azul]['equipos'][nombre_azul]
		stats_rojo = clasificaciones[grupo_rojo]['equipos'][nombre_rojo]
		stats_azul['jugados'] += 1
		stats_rojo['jugados'] += 1

		if grupo_azul == grupo_rojo:
			duracion = partida.duracion_segundos or 0
			h2h_duracion_total[grupo_azul][nombre_azul][nombre_rojo] = (
				h2h_duracion_total[grupo_azul][nombre_azul].get(nombre_rojo, 0) + duracion
			)
			h2h_duracion_total[grupo_rojo][nombre_rojo][nombre_azul] = (
				h2h_duracion_total[grupo_rojo][nombre_rojo].get(nombre_azul, 0) + duracion
			)

		nombre_ganador = partida.ganador_equipo.nombre if partida.ganador_equipo else None
		if nombre_ganador == nombre_azul:
			stats_azul['victorias'] += 1
			stats_rojo['derrotas'] += 1
			duraciones[grupo_azul][nombre_azul]['victorias_seg_total'] += (partida.duracion_segundos or 0)
			duraciones[grupo_azul][nombre_azul]['victorias_count'] += 1
			duraciones[grupo_rojo][nombre_rojo]['derrotas_seg_total'] += (partida.duracion_segundos or 0)
			duraciones[grupo_rojo][nombre_rojo]['derrotas_count'] += 1
			if grupo_azul == grupo_rojo:
				h2h_wins[grupo_azul][nombre_azul][nombre_rojo] = h2h_wins[grupo_azul][nombre_azul].get(nombre_rojo, 0) + 1
		elif nombre_ganador == nombre_rojo:
			stats_rojo['victorias'] += 1
			stats_azul['derrotas'] += 1
			duraciones[grupo_rojo][nombre_rojo]['victorias_seg_total'] += (partida.duracion_segundos or 0)
			duraciones[grupo_rojo][nombre_rojo]['victorias_count'] += 1
			duraciones[grupo_azul][nombre_azul]['derrotas_seg_total'] += (partida.duracion_segundos or 0)
			duraciones[grupo_azul][nombre_azul]['derrotas_count'] += 1
			if grupo_rojo == grupo_azul:
				h2h_wins[grupo_rojo][nombre_rojo][nombre_azul] = h2h_wins[grupo_rojo][nombre_rojo].get(nombre_azul, 0) + 1

	clasificaciones_render = []
	for grupo in grupos:
		nombre_grupo = grupo['nombre']
		equipos_grupo = list(clasificaciones[nombre_grupo]['equipos'].values())

		# Detectar bloques de triple empate por (victorias, derrotas).
		triple_empate_por_equipo = {}
		ties = {}
		for eq in equipos_grupo:
			key = (eq['victorias'], eq['derrotas'])
			ties.setdefault(key, []).append(eq['equipo'])
		for _, nombres in ties.items():
			if len(nombres) == 3:
				bloque = set(nombres)
				for nombre in nombres:
					triple_empate_por_equipo[nombre] = bloque

		def comparar_equipos(eq_a, eq_b):
			# 1) Más victorias primero.
			if eq_a['victorias'] != eq_b['victorias']:
				return -1 if eq_a['victorias'] > eq_b['victorias'] else 1

			# 2) Con mismas victorias, menos derrotas (menos partidos jugados) primero.
			if eq_a['derrotas'] != eq_b['derrotas']:
				return -1 if eq_a['derrotas'] < eq_b['derrotas'] else 1

			# 3) En triple empate, comparar duración acumulada contra el tercer equipo.
			bloque_a = triple_empate_por_equipo.get(eq_a['equipo'])
			if bloque_a and eq_b['equipo'] in bloque_a:
				terceros = [t for t in bloque_a if t not in (eq_a['equipo'], eq_b['equipo'])]
				if terceros:
					tercero = terceros[0]
					total_a = h2h_duracion_total[nombre_grupo].get(eq_a['equipo'], {}).get(tercero, 0)
					total_b = h2h_duracion_total[nombre_grupo].get(eq_b['equipo'], {}).get(tercero, 0)
					if total_a and total_b and total_a != total_b:
						return -1 if total_a < total_b else 1

			# 4) Desempate por enfrentamiento directo (head-to-head).
			a_vs_b = h2h_wins[nombre_grupo].get(eq_a['equipo'], {}).get(eq_b['equipo'], 0)
			b_vs_a = h2h_wins[nombre_grupo].get(eq_b['equipo'], {}).get(eq_a['equipo'], 0)
			if a_vs_b != b_vs_a:
				return -1 if a_vs_b > b_vs_a else 1

			# 5) Si no hay enfrentamiento directo, desempatar por duración media.
			# En victorias gana quien tarda menos; en derrotas gana quien aguanta más.
			if a_vs_b == 0 and b_vs_a == 0:
				dur_a = duraciones[nombre_grupo][eq_a['equipo']]
				dur_b = duraciones[nombre_grupo][eq_b['equipo']]

				avg_win_a = (dur_a['victorias_seg_total'] / dur_a['victorias_count']) if dur_a['victorias_count'] else None
				avg_win_b = (dur_b['victorias_seg_total'] / dur_b['victorias_count']) if dur_b['victorias_count'] else None
				if avg_win_a is not None and avg_win_b is not None and avg_win_a != avg_win_b:
					return -1 if avg_win_a < avg_win_b else 1

				avg_loss_a = (dur_a['derrotas_seg_total'] / dur_a['derrotas_count']) if dur_a['derrotas_count'] else None
				avg_loss_b = (dur_b['derrotas_seg_total'] / dur_b['derrotas_count']) if dur_b['derrotas_count'] else None
				if avg_loss_a is not None and avg_loss_b is not None and avg_loss_a != avg_loss_b:
					return -1 if avg_loss_a > avg_loss_b else 1

			# 6) Si persiste el empate, ordenar por nombre.
			if eq_a['equipo'] < eq_b['equipo']:
				return -1
			if eq_a['equipo'] > eq_b['equipo']:
				return 1
			return 0

		equipos_ordenados = sorted(equipos_grupo, key=cmp_to_key(comparar_equipos))
		clasificaciones_render.append({
			'grupo': nombre_grupo,
			'equipos': equipos_ordenados,
		})

	return clasificaciones_render


def buscar_partidos_por_jornada(request):
	"""Devuelve todas las partidas (con sus stats de jugadores) para una `jornada` dada.

	Parámetros GET:
	- jornada: valor exacto de la columna `jornada` de `Partida`.

	Respuesta JSON con la lista de partidas y, para cada una, un array `stats_jugadores`.
	"""
	jornada = request.GET.get('jornada')
	wants_html = request.GET.get('format') == 'html' or 'text/html' in request.META.get('HTTP_ACCEPT', '')
	if not jornada:
		if wants_html:
			# Renderizar el formulario de búsqueda si se solicita HTML y no se pasó la jornada
			return render(request, 'Cinturones/buscar_partidos_form.html')
		return JsonResponse({'error': 'Parámetro "jornada" requerido.'}, status=400)

	partidas = (partidas_de(request)
				.filter(jornada=jornada)
				.select_related('equipo_azul', 'equipo_rojo', 'ganador_equipo')
				.prefetch_related('stats_jugadores__jugador'))

	resultado = []
	for p in partidas:
		stats = []
		for s in p.stats_jugadores.all():
			stats.append({
				'jugador_id': s.jugador.id,
				'jugador_nombre': s.jugador.nombre,
				'campeon': s.campeon,
				'kills': s.kills,
				'muertes': s.muertes,
				'asistencias': s.asistencias,
				'kda': float(s.kda) if s.kda is not None else 0.0,
				'kp_porcentaje': float(s.kp_porcentaje) if s.kp_porcentaje is not None else 0.0,
				'oro_min': float(s.oro_min or 0.0),
				'dano_infligido': int(s.dano_infligido or 0),
				'porcentaje_dano_equipo': float(s.porcentaje_dano_equipo or 0.0),
				'dano_min': float(s.dano_min or 0.0),
				'dano_recibido': int(s.dano_recibido or 0),
				'cs': s.cs,
				'cs_min': float(s.cs_min or 0.0),
				'vision_min': float(s.vision_min or 0.0),
				'double_kills': s.double_kills,
				'triple_kills': s.triple_kills,
				'quadra_kills': s.quadra_kills,
				'penta_kills': s.penta_kills,
				'game_time': float(s.game_time or 0.0),
			})

		resultado.append({
			'id': p.id,
			'match_id': p.match_id,
			'jornada': p.jornada,
			'numero_partida': p.numero_partida,
			'equipo_azul': p.equipo_azul.nombre if p.equipo_azul else None,
			'equipo_rojo': p.equipo_rojo.nombre if p.equipo_rojo else None,
			'ganador_equipo': p.ganador_equipo.nombre if p.ganador_equipo else None,
			'duracion_segundos': f"{p.duracion_segundos//60}:{p.duracion_segundos%60:02}",
			'dragones_azul': p.dragones_azul,
			'dragones_rojo': p.dragones_rojo,
			'heraldos_azul': p.heraldos_azul,
			'heraldos_rojo': p.heraldos_rojo,
			'barones_azul': p.barones_azul,
			'barones_rojo': p.barones_rojo,
			'elders_azul': p.elders_azul,
			'elders_rojo': p.elders_rojo,
			'atakhan_azul': p.atakhan_azul,
			'atakhan_rojo': p.atakhan_rojo,
			'stats_jugadores': stats,
		})

	# Si se solicita HTML, renderizar la plantilla
	wants_html = request.GET.get('format') == 'html' or 'text/html' in request.META.get('HTTP_ACCEPT', '')
	if wants_html:
		return render(request, 'Cinturones/partidas_list.html', {'partidas': resultado, 'jornada': jornada})

	return JsonResponse({'partidas': resultado})


def buscar_partidos_form(request):
	"""Lista de partidas agrupadas por jornada (la más reciente primero), con filtro por jornada y equipo."""
	from .views_app import _puntuar_partidas, _resumen_partidas

	jornada = request.GET.get('jornada') or ''
	equipo = request.GET.get('equipo') or ''

	todas = sorted(partidas_de(request).select_related('equipo_azul', 'equipo_rojo', 'ganador_equipo', 'temporada'), key=orden_partida)
	jornadas = []
	for p in todas:
		if p.jornada not in jornadas:
			jornadas.append(p.jornada)
	equipos = sorted({p.equipo_azul.nombre for p in todas if p.equipo_azul} | {p.equipo_rojo.nombre for p in todas if p.equipo_rojo})

	partidas = [p for p in todas if not jornada or p.jornada == jornada]
	if equipo:
		partidas = [p for p in partidas if equipo in ((p.equipo_azul.nombre if p.equipo_azul else ''), (p.equipo_rojo.nombre if p.equipo_rojo else ''))]

	resultados, por_partida = _puntuar_partidas(partidas)
	filas = _resumen_partidas(partidas, resultados, por_partida)

	grupos = []
	for f in reversed(filas):
		if not grupos or grupos[-1]['jornada'] != f['p'].jornada:
			grupos.append({'jornada': f['p'].jornada, 'partidas': []})
		grupos[-1]['partidas'].append(f)
	for g in grupos:
		g['partidas'].reverse()   # dentro de la jornada, en orden de game

	return render(request, 'Cinturones/buscar_partidos_form.html', {
		'grupos': grupos, 'jornadas': jornadas, 'jornada': jornada,
		'equipos': equipos, 'equipo': equipo,
		'total': len(partidas), 'total_partidas': len(todas),
	})


def _grafica_oro(stats_azul, stats_rojo, extras, nombre_azul, nombre_rojo):
	"""
	Oro de cada equipo y de cada jugador minuto a minuto (sale del timeline, ver cargar_datos_avanzados).
	`extras` es {jugador_id: riot_extra}. Devuelve None si a algún jugador le faltan los datos.
	"""
	curvas = {s['jugador_id']: extras.get(s['jugador_id']) or {} for s in stats_azul + stats_rojo}
	if len(curvas) != 10 or not all(c.get('oro_t') and c.get('frames_s') for c in curvas.values()):
		return None
	segundos = next(iter(curvas.values()))['frames_s']
	n = min([len(segundos)] + [len(c['oro_t']) for c in curvas.values()])
	datos = {'t': segundos[:n], 'equipos': {}, 'roles': {}}
	for lado, lista, nombre in (('azul', stats_azul, nombre_azul), ('rojo', stats_rojo, nombre_rojo)):
		datos['equipos'][lado] = {'nombre': nombre, 'oro': [sum(curvas[s['jugador_id']]['oro_t'][i] for s in lista) for i in range(n)]}
		for s in lista:
			datos['roles'].setdefault((s.get('rol') or '').upper(), {})[lado] = {
				'nombre': s['jugador_nombre'].split('#')[0], 'campeon': s['campeon'],
				'oro': curvas[s['jugador_id']]['oro_t'][:n],
			}
	# Solo los roles con un jugador en cada lado, en el orden de siempre
	datos['roles'] = {r: datos['roles'][r] for r in ('TOP', 'JGL', 'MID', 'ADC', 'SUP') if len(datos['roles'].get(r, {})) == 2}
	return datos


def detalle_partida(request, match_id=None):
	"""Devuelve los detalles de una partida (incluyendo stats de jugadores).

	- match_id: puede venir como path param o GET `match_id`.
	"""
	if match_id is None:
		match_id = request.GET.get('match_id')
	if not match_id:
		return JsonResponse({'error': 'Parámetro "match_id" requerido.'}, status=400)

	partida = get_object_or_404(Partida.objects.select_related('equipo_azul', 'equipo_rojo', 'ganador_equipo').prefetch_related('stats_jugadores__jugador'), match_id=match_id)

	stats = []
	for s in partida.stats_jugadores.all():
		stats.append({
			'jugador_id': s.jugador.id,
			'jugador_nombre': s.jugador.nombre,
			'campeon': s.campeon,
			'kills': s.kills,
			'muertes': s.muertes,
			'asistencias': s.asistencias,
			'kda': float(s.kda or 0.0),
			'kp_porcentaje': float(s.kp_porcentaje or 0.0),
			'oro_min': float(s.oro_min or 0.0),
			'dano_infligido': int(s.dano_infligido or 0),
			'porcentaje_dano_equipo': float(s.porcentaje_dano_equipo or 0.0),
			'dano_min': float(s.dano_min or 0.0),
			'dano_recibido': int(s.dano_recibido or 0),
			'cs': s.cs,
			'cs_min': float(s.cs_min or 0.0),
			'vision_min': float(s.vision_min or 0.0),
			'double_kills': s.double_kills,
			'triple_kills': s.triple_kills,
			'quadra_kills': s.quadra_kills,
			'penta_kills': s.penta_kills,
			'rol': s.rol,
			'nombre_equipo': s.equipo_nombre,
			'gd15':  s.gd15,
			'csd15': s.csd15,
			'xpd15': s.xpd15,
			'cs15':  s.cs15,
			'ka15':  s.ka15,
			'fb':    s.fb,
			'fbv':   s.fbv,
		})

	data = {
		'id': partida.id,
		'match_id': partida.match_id,
		'jornada': partida.jornada,
		'numero_partida': partida.numero_partida,
		'equipo_azul': partida.equipo_azul.nombre if partida.equipo_azul else None,
		'equipo_rojo': partida.equipo_rojo.nombre if partida.equipo_rojo else None,
		'ganador_equipo': partida.ganador_equipo.nombre if partida.ganador_equipo else None,
		'duracion_segundos': f"{partida.duracion_segundos//60}:{partida.duracion_segundos%60:02}",
		'stats_jugadores': stats,
	}
	wants_html = request.GET.get('format') == 'html' or 'text/html' in request.META.get('HTTP_ACCEPT', '')
	if wants_html:
		# Separar stats por equipo y ordenar por rol: top,jgl,mid,adc,sup
		roles_order = {'top': 0, 'jgl': 1, 'mid': 2, 'adc': 3, 'sup': 4}
		equipo_azul_nombre = partida.equipo_azul.nombre if partida.equipo_azul else None
		equipo_rojo_nombre = partida.equipo_rojo.nombre if partida.equipo_rojo else None
		stats_azul = [s for s in stats if s.get('nombre_equipo') == equipo_azul_nombre]
		stats_rojo = [s for s in stats if s.get('nombre_equipo') == equipo_rojo_nombre]
		stats_azul = sorted(stats_azul, key=lambda x: roles_order.get((x.get('rol') or '').lower(), 99))
		stats_rojo = sorted(stats_rojo, key=lambda x: roles_order.get((x.get('rol') or '').lower(), 99))

		# Proximidad del jungler
		team_roles: dict[int, dict] = {100: {}, 200: {}}
		for s in stats:
			role = (s.get('rol') or '').lower()
			team_id = 100 if s.get('nombre_equipo') == equipo_azul_nombre else 200
			if role in ('top', 'jgl', 'mid', 'adc', 'sup'):
				team_roles[team_id][role] = s['jugador_nombre']

		proximity = {}
		if partida.position_data and any(team_roles.values()):
			proximity = calculate_jungler_proximity(partida.position_data, team_roles)

		# Nota de rendimiento de cada jugador
		from . import scoring
		from .views_app import iniciales_equipo
		objs = {s.id: s for s in partida.stats_jugadores.all()}
		resultados = scoring.puntuar_stats(list(objs.values()))
		desgloses = {}
		for lista in (stats_azul, stats_rojo):
			for st in lista:
				obj = next((o for o in objs.values() if o.jugador_id == st['jugador_id']), None)
				r = resultados.get(obj.id) if obj else None
				if not r:
					continue
				st['stats_id'] = obj.id
				st['nota'] = r['nota']
				st['puesto'] = r.get('puesto')
				st['insignia'] = r.get('insignia')
				ex = obj.riot_extra or {}
				st['extra'] = ex
				st['oro'] = ex.get('goldEarned') or round((st['oro_min'] or 0) * (obj.game_time or 0))
				st['vision'] = ex.get('visionScore')
				st['victoria'] = obj.victoria
				desgloses[obj.id] = {
					'nombre': st['jugador_nombre'], 'campeon': st['campeon'], 'rol': st['rol'],
					'nota': r['nota'], 'total': r['total'], 'ajuste': r['ajuste'], 'victoria': r['victoria'],
					'puesto': r.get('puesto'), 'insignia': r.get('insignia'), 'bloques': r['bloques'],
				}

		def resumen_equipo(lista, nombre, lado):
			gana = bool(partida.ganador_equipo and partida.ganador_equipo.nombre == nombre)
			suf = 'azul' if lado == 'azul' else 'rojo'
			return {
				'nombre': nombre, 'ini': iniciales_equipo(nombre), 'gana': gana, 'lado': lado,
				'kills': sum(s['kills'] for s in lista), 'muertes': sum(s['muertes'] for s in lista),
				'asistencias': sum(s['asistencias'] for s in lista),
				'oro': sum(s.get('oro') or 0 for s in lista),
				'dano': sum(s['dano_infligido'] for s in lista),
				'dragones': getattr(partida, f'dragones_{suf}'), 'barones': getattr(partida, f'barones_{suf}'),
				'heraldos': getattr(partida, f'heraldos_{suf}'), 'elders': getattr(partida, f'elders_{suf}'),
				'atakhan': getattr(partida, f'atakhan_{suf}'),
			}

		oro_grafica = _grafica_oro(stats_azul, stats_rojo, {o.jugador_id: o.riot_extra for o in objs.values()},
								   equipo_azul_nombre, equipo_rojo_nombre)

		equipo_az = resumen_equipo(stats_azul, equipo_azul_nombre, 'azul')
		equipo_ro = resumen_equipo(stats_rojo, equipo_rojo_nombre, 'rojo')
		max_dano = max([s['dano_infligido'] for s in stats_azul + stats_rojo] or [1]) or 1

		return render(
			request,
			'Cinturones/partida_detail.html',
			{
				'partida': data,
				'partida_obj': partida,
				'equipo_azul': equipo_azul_nombre,
				'equipo_rojo': equipo_rojo_nombre,
				'ganador_equipo': partida.ganador_equipo.nombre if partida.ganador_equipo else None,
				'stats_azul': stats_azul,
				'stats_rojo': stats_rojo,
				'eq_azul': equipo_az,
				'eq_rojo': equipo_ro,
				'max_dano': max_dano,
				'desgloses': desgloses,
				'oro_grafica': oro_grafica,
				'proximity': proximity,
			},
		)

	return JsonResponse(data)


def heatmap_data(request, match_id):
	"""Devuelve los datos de posición almacenados para una partida como JSON."""
	partida = get_object_or_404(Partida, match_id=match_id)
	if not partida.position_data:
		return JsonResponse({'error': 'No hay datos de posición para esta partida. Reimporta la partida con seed_partidas.'}, status=404)
	stats = StatsJugador.objects.filter(partida=partida).select_related('jugador')
	data = dict(partida.position_data)
	data['players'] = annotate_player_roles(data.get('players', {}), stats)
	return JsonResponse(data)


# Columnas de la página Jugadores: (clave, cabecera, título, formato, vistas en las que sale, sentido)
# sentido: 1 = más es mejor, -1 = menos es mejor, 0 = sin colorear
VISTAS_JUGADORES = [
	('resumen', 'Resumen'), ('combate', 'Combate'), ('farmeo', 'Farmeo'), ('dano', 'Daño'),
	('vision', 'Visión'), ('early', 'Early game'), ('equipo', 'Equipo'),
]
COLUMNAS_JUGADORES = [
	{'clave': 'win_rate', 'cab': '% WR', 'titulo': 'Porcentaje de victorias', 'fmt': 'pct0', 'vistas': 'resumen equipo', 'sentido': 1},
	{'clave': 'mvp', 'cab': 'MVP', 'titulo': 'Veces mejor jugador del equipo ganador', 'fmt': 'f0', 'vistas': 'equipo', 'sentido': 2},
	{'clave': 'ace', 'cab': 'ACE', 'titulo': 'Veces mejor jugador del equipo perdedor', 'fmt': 'f0', 'vistas': 'equipo', 'sentido': 2},
	{'clave': 'avg_kda', 'cab': 'KDA', 'titulo': 'KDA medio', 'fmt': 'f2', 'vistas': 'resumen combate', 'sentido': 1},
	{'clave': 'k_pg', 'cab': 'K', 'titulo': 'Kills por partida', 'fmt': 'f1', 'vistas': 'combate', 'sentido': 1},
	{'clave': 'd_pg', 'cab': 'D', 'titulo': 'Muertes por partida', 'fmt': 'f1', 'vistas': 'combate', 'sentido': -1},
	{'clave': 'a_pg', 'cab': 'A', 'titulo': 'Asistencias por partida', 'fmt': 'f1', 'vistas': 'combate', 'sentido': 1},
	{'clave': 'avg_kp', 'cab': 'KP', 'titulo': 'Participación en kills', 'fmt': 'pct0', 'vistas': 'resumen combate', 'sentido': 1},
	{'clave': 'fb_rate', 'cab': 'First blood', 'titulo': 'Partidas con participación en la primera sangre', 'fmt': 'pct0', 'vistas': 'combate early', 'sentido': 1},
	{'clave': 'avg_double', 'cab': '2K', 'titulo': 'Dobles kills (total)', 'fmt': 'f0', 'vistas': 'combate', 'sentido': 1},
	{'clave': 'avg_triple', 'cab': '3K', 'titulo': 'Triples kills (total)', 'fmt': 'f0', 'vistas': 'combate', 'sentido': 1},
	{'clave': 'avg_quadra', 'cab': '4K', 'titulo': 'Cuádruples kills (total)', 'fmt': 'f0', 'vistas': 'combate', 'sentido': 1},
	{'clave': 'avg_penta', 'cab': '5K', 'titulo': 'Pentakills (total)', 'fmt': 'f0', 'vistas': 'combate', 'sentido': 1},
	{'clave': 'avg_cs', 'cab': 'CS', 'titulo': 'CS por partida', 'fmt': 'f0', 'vistas': 'farmeo', 'sentido': 1},
	{'clave': 'avg_cs_min', 'cab': 'CS/min', 'titulo': 'CS por minuto', 'fmt': 'f1', 'vistas': 'resumen farmeo', 'sentido': 1},
	{'clave': 'avg_oro_min', 'cab': 'Oro/min', 'titulo': 'Oro por minuto', 'fmt': 'f0', 'vistas': 'resumen farmeo', 'sentido': 1},
	{'clave': 'avg_gold_pct', 'cab': '% oro', 'titulo': 'Porcentaje del oro del equipo', 'fmt': 'pct1', 'vistas': 'farmeo equipo', 'sentido': 1},
	{'clave': 'avg_cs15', 'cab': 'CS @15', 'titulo': 'CS al minuto 15', 'fmt': 'f1', 'vistas': 'farmeo early', 'sentido': 1},
	{'clave': 'avg_dano_min', 'cab': 'Daño/min', 'titulo': 'Daño a campeones por minuto', 'fmt': 'f0', 'vistas': 'resumen dano', 'sentido': 1},
	{'clave': 'avg_porcentaje_dano_equipo', 'cab': '% daño', 'titulo': 'Porcentaje del daño del equipo', 'fmt': 'pct1', 'vistas': 'resumen dano', 'sentido': 1},
	{'clave': 'avg_dano_recibido', 'cab': 'Recibido', 'titulo': 'Daño recibido por partida', 'fmt': 'miles', 'vistas': 'dano', 'sentido': 0},
	{'clave': 'avg_dano_oro', 'cab': 'Daño/oro', 'titulo': 'Daño por cada unidad de oro', 'fmt': 'f2', 'vistas': 'dano', 'sentido': 1},
	{'clave': 'avg_vision_min', 'cab': 'Visión/min', 'titulo': 'Puntuación de visión por minuto', 'fmt': 'f2', 'vistas': 'resumen vision', 'sentido': 1},
	{'clave': 'avg_wpm', 'cab': 'Wards/min', 'titulo': 'Wards colocados por minuto', 'fmt': 'f2', 'vistas': 'vision', 'sentido': 1},
	{'clave': 'avg_cwpm', 'cab': 'Pinks/min', 'titulo': 'Pinks comprados por minuto', 'fmt': 'f2', 'vistas': 'vision', 'sentido': 1},
	{'clave': 'avg_wcpm', 'cab': 'Destruidos/min', 'titulo': 'Wards destruidos por minuto', 'fmt': 'f2', 'vistas': 'vision', 'sentido': 1},
	{'clave': 'avg_gd15', 'cab': 'Dif. oro @15', 'titulo': 'Diferencia de oro con el rival al minuto 15', 'fmt': 'signo0', 'vistas': 'early', 'sentido': 1},
	{'clave': 'avg_csd15', 'cab': 'Dif. CS @15', 'titulo': 'Diferencia de CS con el rival al minuto 15', 'fmt': 'signo1', 'vistas': 'early', 'sentido': 1},
	{'clave': 'avg_xpd15', 'cab': 'Dif. XP @15', 'titulo': 'Diferencia de experiencia con el rival al minuto 15', 'fmt': 'signo0', 'vistas': 'early', 'sentido': 1},
	{'clave': 'avg_ka15', 'cab': 'K+A @15', 'titulo': 'Kills y asistencias antes del minuto 15', 'fmt': 'f1', 'vistas': 'early', 'sentido': 1},
	{'clave': 'avg_death_share', 'cab': '% muertes', 'titulo': 'Porcentaje de las muertes del equipo', 'fmt': 'pct1', 'vistas': 'equipo', 'sentido': -1},
	{'clave': 'avg_game_time', 'cab': 'Duración', 'titulo': 'Duración media de sus partidas', 'fmt': 'min', 'vistas': 'equipo', 'sentido': 0},
]
# Los multikills son totales y casi siempre 0: solo se destaca el máximo (sentido 2)
for _c in COLUMNAS_JUGADORES:
	if _c['clave'] in ('avg_double', 'avg_triple', 'avg_quadra', 'avg_penta'):
		_c['sentido'] = 2


def _formato_celda(v, fmt):
	if v is None:
		return '—'
	if fmt == 'pct0':
		return f'{v:.0f}%'
	if fmt == 'pct1':
		return f'{v:.1f}%'
	if fmt == 'f0':
		return f'{v:.0f}'
	if fmt == 'f1':
		return f'{v:.1f}'
	if fmt == 'f2':
		return f'{v:.2f}'
	if fmt == 'signo0':
		return f'{v:+.0f}' if round(v) else '0'
	if fmt == 'signo1':
		return f'{v:+.1f}' if round(v, 1) else '0'
	if fmt == 'miles':
		from .templatetags.kb import miles
		return miles(v)
	if fmt == 'min':
		m, s = divmod(int(round(v * 60)), 60)
		return f'{m}:{s:02d}'
	return str(v)


def _clasificador(resultados, col):
	"""Devuelve una función valor → clase según su puesto en la columna:
	p-mejor (el mejor), p-alto (20 % mejor), p-bajo (20 % peor), p-peor (el peor) o ''.
	El mejor y el peor solo se marcan si no están empatados con más de MAX_EMPATE_EXTREMO jugadores
	(p. ej. muchos con 0 % de first blood): si no, se quedan en p-alto / p-bajo."""
	sentido, k = col['sentido'], col['clave']
	signo = -1 if sentido == -1 else 1
	vals = sorted(r[k] * signo for r in resultados if r.get(k) is not None)
	if not sentido or len(vals) < 5 or vals[0] == vals[-1]:
		return lambda v: ''
	unico_mejor = vals.count(vals[-1]) <= MAX_EMPATE_EXTREMO
	unico_peor = vals.count(vals[0]) <= MAX_EMPATE_EXTREMO
	if sentido == 2:
		return lambda v: 'p-mejor' if v == vals[-1] and unico_mejor else ('p-cero' if not v else '')
	n = len(vals)
	alto, bajo = vals[min(n - 1, int(n * 0.8))], vals[max(0, int(n * 0.2) - 1)]
	if alto <= bajo:
		return lambda v: ''

	def clase(v):
		x = v * signo
		if x == vals[-1] and unico_mejor:
			return 'p-mejor'
		if x == vals[0] and unico_peor:
			return 'p-peor'
		if x >= alto:
			return 'p-alto'
		if x <= bajo:
			return 'p-bajo'
		return ''
	return clase


MAX_EMPATE_EXTREMO = 2


def jugadores_html(request):
	"""Página de Jugadores (tabla de promedios) siempre en HTML."""
	return promedios_jugadores(request, forzar_html=True)


def promedios_jugadores(request, jugador_nombre=None, campeon=None, forzar_html=False):
	"""Devuelve el promedio de las estadísticas por jugador.

	Parámetros GET opcionales:
	- jornada: filtrar stats por `partida__jornada` antes de agregar
	- jugador: nombre (contiene) para filtrar jugadores específicos
	"""
	if jugador_nombre:
		# Las rutas antiguas por jugador llevan a su perfil
		from django.shortcuts import redirect
		return redirect('jugador', nombre=jugador_nombre)
	# Obtener las jornadas directamente desde la tabla Partida (evita duplicados nulos/vacíos)
	jornadas_disponibles = sorted(
		set(partidas_de(request).exclude(jornada__isnull=True).exclude(jornada__exact='').values_list('jornada', flat=True)),
		key=orden_jornada)
	jornada = request.GET.get('jornada')
	numero_partida = request.GET.get('numero_partida')
	jugador_q = request.GET.get('jugador')
	rol_q = request.GET.get('rol')
	sort = request.GET.get('sort') or 'nota'   # por defecto, los de mejor nota primero
	order = request.GET.get('order', 'desc')

	numeros_qs = partidas_de(request).exclude(numero_partida__isnull=True).exclude(numero_partida__exact='')
	if jornada:
		numeros_qs = numeros_qs.filter(jornada=jornada)
	numeros_disponibles = list(numeros_qs.values_list('numero_partida', flat=True).distinct().order_by('numero_partida'))

	qs = stats_de(request)
	if jornada:
		qs = qs.filter(partida__jornada=jornada)
	if numero_partida:
		qs = qs.filter(partida__numero_partida=numero_partida)
	if jugador_q:
		qs = qs.filter(jugador__nombre__icontains=jugador_q)
	if rol_q:
		qs = qs.filter(rol=rol_q)

	# Rol más jugado por jugador: ordenamos por count desc y nos quedamos el primero por jugador
	roles_qs = qs.values('jugador__id', 'rol').annotate(rol_count=Count('rol')).order_by('jugador__id', '-rol_count')
	rol_principal = {}
	for r in roles_qs:
		jid = r['jugador__id']
		if jid not in rol_principal:
			rol_principal[jid] = r['rol'] or ''

	agregados = qs.values('jugador__id', 'jugador__nombre').annotate(
		avg_kills=Sum('kills'),
		avg_muertes=Sum('muertes'),
		avg_asistencias=Sum('asistencias'),
		avg_kda=Avg('kda'),
		avg_kp=Avg('kp_porcentaje'),
		avg_oro_min=Avg('oro_min'),
		avg_dano_oro=Avg('dano_oro'),
		avg_dano_infligido=Avg('dano_infligido'),
		avg_porcentaje_dano_equipo=Avg('porcentaje_dano_equipo'),
		avg_dano_min=Avg('dano_min'),
		avg_dano_recibido=Avg('dano_recibido'),
		avg_cs=Avg('cs'),
		avg_cs_min=Avg('cs_min'),
		avg_vision_min=Avg('vision_min'),
		avg_wpm=Avg('wpm'),
		avg_cwpm=Avg('cwpm'),
		avg_wcpm=Avg('wcpm'),
		avg_gold_pct=Avg('gold_pct'),
		avg_death_share=Avg('death_share'),
		win_rate=Avg('victoria'),
		avg_gd15=Avg('gd15'),
		avg_csd15=Avg('csd15'),
		avg_xpd15=Avg('xpd15'),
		avg_cs15=Avg('cs15'),
		avg_ka15=Avg('ka15'),
		fb_rate=Avg('fb'),
		fbv_rate=Avg('fbv'),
		avg_double=Sum('double_kills'),
		avg_triple=Sum('triple_kills'),
		avg_quadra=Sum('quadra_kills'),
		avg_penta=Sum('penta_kills'),
		avg_game_time=Avg('game_time'),
		games_played=Count('partida__id'),
	)
	# Orden dinámico sobre los aliases generados
	sort_map = {
		'nombre': 'jugador__nombre',
		'kills': 'avg_kills',
		'muertes': 'avg_muertes',
		'asistencias': 'avg_asistencias',
		'kda': 'avg_kda',
		'kp': 'avg_kp',
		'oro_min': 'avg_oro_min',
		'dano_oro': 'avg_dano_oro',
		'dano': 'avg_dano_infligido',
		'dano_min': 'avg_dano_min',
		'dano_recibido': 'avg_dano_recibido',
		'porcentaje_dano_equipo': 'avg_porcentaje_dano_equipo',
		'cs': 'avg_cs',
		'cs_min': 'avg_cs_min',
		'vision_min': 'avg_vision_min',
		'wpm': 'avg_wpm',
		'cwpm': 'avg_cwpm',
		'wcpm': 'avg_wcpm',
		'gold_pct': 'avg_gold_pct',
		'death_share': 'avg_death_share',
		'win_rate':   'win_rate',
		'gd15':       'avg_gd15',
		'csd15':      'avg_csd15',
		'xpd15':      'avg_xpd15',
		'cs15':       'avg_cs15',
		'ka15':       'avg_ka15',
		'fb_rate':    'fb_rate',
		'double_kills': 'avg_double',
		'triple_kills': 'avg_triple',
		'quadra_kills': 'avg_quadra',
		'penta_kills': 'avg_penta',
        'game_time': 'avg_game_time',
		'games': 'games_played',
	}
	if sort in sort_map:
		field = sort_map[sort]
		if order == 'desc':
			field = f'-{field}'
		agregados = agregados.order_by(field)
	else:
		agregados = agregados.order_by('jugador__nombre')

	# Nota media de rendimiento (cada partida se puntúa con sus 10 jugadores)
	from . import scoring
	stats_filtradas = list(qs.only('id', 'jugador_id', 'partida_id'))
	todas = list(StatsJugador.objects.filter(partida_id__in={s.partida_id for s in stats_filtradas}))
	notas_res = scoring.puntuar_stats(todas)
	notas_jug = {}
	insignias_jug = {}   # {jugador_id: {'MVP': n, 'ACE': n}}
	for s in stats_filtradas:
		if s.id in notas_res:
			notas_jug.setdefault(s.jugador_id, []).append(notas_res[s.id]['nota'])
			ins = notas_res[s.id].get('insignia')
			if ins in ('MVP', 'ACE'):
				d = insignias_jug.setdefault(s.jugador_id, {})
				d[ins] = d.get(ins, 0) + 1
	perfil = {}
	for jid, extra in qs.order_by('partida_id').values_list('jugador_id', 'riot_extra'):
		if extra and extra.get('profileIcon') is not None:
			perfil[jid] = extra['profileIcon']
	campeon_fav = {}
	for jid, camp in (qs.values_list('jugador_id', 'campeon')):
		if camp:
			campeon_fav.setdefault(jid, {}).setdefault(camp, 0)
			campeon_fav[jid][camp] += 1

	resultados = []
	for a in agregados:
		resultados.append({
			'jugador_id': a['jugador__id'],
			'jugador_nombre': a['jugador__nombre'],
			'avg_kills': int(a['avg_kills'] or 0.0),
			'avg_muertes': int(a['avg_muertes'] or 0.0),
			'avg_asistencias': int(a['avg_asistencias'] or 0.0),
			'avg_kda': float(a['avg_kda'] or 0.0),
			'avg_kp': float(a['avg_kp'] or 0.0),
			'avg_oro_min': float(a['avg_oro_min'] or 0.0),
			'avg_dano_oro': float(a['avg_dano_oro'] or 0.0),
			'avg_dano_infligido': float(a['avg_dano_infligido'] or 0.0),
			'avg_porcentaje_dano_equipo': float(a['avg_porcentaje_dano_equipo'] or 0.0),
			'avg_dano_min': float(a['avg_dano_min'] or 0.0),
			'avg_dano_recibido': float(a['avg_dano_recibido'] or 0.0),
			'avg_cs': float(a['avg_cs'] or 0.0),
			'avg_cs_min': float(a['avg_cs_min'] or 0.0),
			'avg_vision_min': float(a['avg_vision_min'] or 0.0),
			'avg_wpm': float(a['avg_wpm'] or 0.0),
			'avg_cwpm': float(a['avg_cwpm'] or 0.0),
			'avg_wcpm': float(a['avg_wcpm'] or 0.0),
			'avg_gold_pct': float(a['avg_gold_pct'] or 0.0),
			'avg_death_share': float(a['avg_death_share'] or 0.0),
			'win_rate': round(float(a['win_rate'] or 0.0) * 100, 1),
			'avg_gd15':  round(float(a['avg_gd15']  or 0.0), 0) if a['avg_gd15']  is not None else None,
			'avg_csd15': round(float(a['avg_csd15'] or 0.0), 1) if a['avg_csd15'] is not None else None,
			'avg_xpd15': round(float(a['avg_xpd15'] or 0.0), 0) if a['avg_xpd15'] is not None else None,
			'avg_cs15':  round(float(a['avg_cs15']  or 0.0), 1) if a['avg_cs15']  is not None else None,
			'avg_ka15':  round(float(a['avg_ka15']  or 0.0), 1) if a['avg_ka15']  is not None else None,
			'fb_rate':   round(float(a['fb_rate']   or 0.0) * 100, 1) if a['fb_rate']  is not None else None,
			'fbv_rate':  round(float(a['fbv_rate']  or 0.0) * 100, 1) if a['fbv_rate'] is not None else None,
			'avg_double': int(a['avg_double'] or 0.0),
			'avg_triple': int(a['avg_triple'] or 0.0),
			'avg_quadra': int(a['avg_quadra'] or 0.0),
			'avg_penta': int(a['avg_penta'] or 0.0),
			'avg_game_time': float(a['avg_game_time'] or 0.0),
			'games_played': a['games_played'],
			'rol_principal': rol_principal.get(a['jugador__id'], ''),
			'nota': round(sum(notas_jug[a['jugador__id']]) / len(notas_jug[a['jugador__id']]), 1) if notas_jug.get(a['jugador__id']) else None,
			'campeon_fav': max(campeon_fav[a['jugador__id']], key=campeon_fav[a['jugador__id']].get) if campeon_fav.get(a['jugador__id']) else None,
			'perfil': perfil.get(a['jugador__id']),
			'mvp': insignias_jug.get(a['jugador__id'], {}).get('MVP', 0),
			'ace': insignias_jug.get(a['jugador__id'], {}).get('ACE', 0),
		})

	if sort == 'nota':
		resultados.sort(key=lambda r: (r['nota'] is None, -(r['nota'] or 0) if order == 'desc' else (r['nota'] or 0)))

	wants_html = forzar_html or request.GET.get('format') == 'html' or 'text/html' in request.META.get('HTTP_ACCEPT', '')
	if wants_html:
		# K / D / A por partida (los agregados son totales)
		for r in resultados:
			n = r['games_played'] or 1
			r['k_pg'] = r['avg_kills'] / n
			r['d_pg'] = r['avg_muertes'] / n
			r['a_pg'] = r['avg_asistencias'] / n

		# Mínimo de partidas
		try:
			minimo = max(1, int(request.GET.get('min') or 1))
		except ValueError:
			minimo = 1
		resultados = [r for r in resultados if r['games_played'] >= minimo]

		# Orden por cualquier columna (los valores vacíos, al final)
		validas = {c['clave'] for c in COLUMNAS_JUGADORES} | {'nota', 'games_played', 'jugador_nombre', 'rol_principal'}
		clave = {'nombre': 'jugador_nombre', 'games': 'games_played'}.get(sort, sort)
		clave = clave if clave in validas else sort_map.get(sort, 'nota')
		if clave not in validas:
			clave = 'nota'
		con_valor = [r for r in resultados if r.get(clave) is not None]
		sin_valor = [r for r in resultados if r.get(clave) is None]
		if clave in ('jugador_nombre', 'rol_principal'):
			con_valor.sort(key=lambda r: r[clave].lower(), reverse=(order == 'desc'))
		else:
			con_valor.sort(key=lambda r: r[clave], reverse=(order == 'desc'))
		resultados = con_valor + sin_valor

		# Celdas ya formateadas y coloreadas según su puesto en la columna, comparando con los de su rol
		# (un support no sale en rojo por farmear poco); con menos de 5 en el rol, con todos
		columnas = [dict(c, vcls=' '.join('v-' + v for v in c['vistas'].split())) for c in COLUMNAS_JUGADORES]
		por_rol = {}
		for r in resultados:
			por_rol.setdefault(r['rol_principal'], []).append(r)
		clasificadores = {
			rol: [_clasificador(grupo if len(grupo) >= 5 else resultados, c) for c in columnas]
			for rol, grupo in por_rol.items()
		}
		for r in resultados:
			r['celdas'] = [{
				'txt': _formato_celda(r.get(c['clave']), c['fmt']),
				'cls': clase(r[c['clave']]) if r.get(c['clave']) is not None else 'p-cero',
				'vcls': c['vcls'],
				'ord': c['clave'] == clave,
			} for c, clase in zip(columnas, clasificadores[r['rol_principal']])]

		vista = request.GET.get('vista')
		if vista not in {v for v, _ in VISTAS_JUGADORES}:
			vista = 'resumen'

		# Parámetros actuales sin orden (para las cabeceras), sin rol (para las pestañas de rol) y sin vista
		def sin(*claves):
			p = request.GET.copy()
			for k in claves + ('format',):
				p.pop(k, None)
			return p.urlencode()
		return render(request, 'Cinturones/promedios_jugadores.html', {
			'qs_sin_orden': sin('sort', 'order'),
			'qs_sin_rol': sin('rol'),
			'qs_sin_vista': sin('vista'),
			'roles_filtro': [('TOP', 'TOP'), ('JGL', 'JG'), ('MID', 'MID'), ('ADC', 'ADC'), ('SUP', 'SUP')],
			'columnas': columnas,
			'vistas': VISTAS_JUGADORES,
			'vista': vista,
			'sort_activo': clave,
			'minimo': minimo,
			'minimos': [1, 2, 3, 5],
			'jugadores': resultados,
			'jornada': jornada,
			'numero_partida': numero_partida,
			'filtro_jugador': jugador_q,
			'filtro_rol': rol_q,
			'sort': sort,
			'order': order,
			'jornadas_disponibles': list(jornadas_disponibles),
			'numeros_disponibles': numeros_disponibles,
		})
	return JsonResponse({'jugadores': resultados, 'jornadas_disponibles': list(jornadas_disponibles)})


def tier_list(request):
	"""
	Tier list por rol con la nota de rendimiento (ver scoring.py).
	La nota de cada jugador es la media de sus partidas en su rol principal.
	"""
	from . import scoring
	from .views_app import _campeones_favoritos

	jornadas_disponibles = sorted(
		set(partidas_de(request).exclude(jornada__isnull=True).exclude(jornada__exact='').values_list('jornada', flat=True)),
		key=orden_jornada,
	)
	jornada = request.GET.get('jornada') or ''
	numero_partida = request.GET.get('numero_partida') or ''

	numeros_qs = partidas_de(request).exclude(numero_partida__isnull=True).exclude(numero_partida__exact='')
	if jornada:
		numeros_qs = numeros_qs.filter(jornada=jornada)
	numeros_disponibles = list(numeros_qs.values_list('numero_partida', flat=True).distinct().order_by('numero_partida'))

	qs = stats_de(request).select_related('jugador')
	if jornada:
		qs = qs.filter(partida__jornada=jornada)
	if numero_partida:
		qs = qs.filter(partida__numero_partida=numero_partida)
	stats = list(qs)

	# Cada partida se puntúa con sus 10 jugadores (hace falta el rival de cada uno)
	todas = list(StatsJugador.objects.filter(partida_id__in={s.partida_id for s in stats}).select_related('jugador'))
	resultados = scoring.puntuar_stats(todas)
	ranking = scoring.ranking_jugadores(stats, resultados)

	# Mínimo de partidas en su rol principal (las de la nota). Se filtra después de puntuar
	# para que la media del rol, que usa la contracción, no cambie al ocultar jugadores.
	try:
		minimo = max(1, int(request.GET.get('min') or 1))
	except ValueError:
		minimo = 1
	ranking = [f for f in ranking if f['partidas'] >= minimo]

	favoritos = _campeones_favoritos(stats)
	for f in ranking:
		f['campeon_fav'] = favoritos.get(f['jugador_id'])

	# Más MVP y más ACE: en todas sus partidas (no solo en su rol principal), entre los jugadores del ranking
	from collections import Counter
	jugadas = Counter(s.jugador_id for s in stats)
	insignias = {'MVP': Counter(), 'ACE': Counter()}
	for s in stats:
		ins = (resultados.get(s.id) or {}).get('insignia')
		if ins in insignias:
			insignias[ins][s.jugador_id] += 1

	def top_insignia(clave):
		filas = [dict(f, n=insignias[clave][f['jugador_id']], jugadas=jugadas[f['jugador_id']])
				 for f in ranking if insignias[clave][f['jugador_id']]]
		# Empates: antes el que lo consigue en menos partidas, luego por nota
		filas.sort(key=lambda f: (-f['n'], f['jugadas'], -f['nota']))
		return filas[:5]
	premios = [
		{'clave': 'MVP', 'sub': 'Mejor jugador del equipo ganador', 'filas': top_insignia('MVP')},
		{'clave': 'ACE', 'sub': 'Mejor jugador del equipo perdedor', 'filas': top_insignia('ACE')},
	]

	TIER_ORDER = ['S+', 'S', 'A', 'B', 'C', 'D']
	tiers = {t: {r: [] for r in scoring.ROLES} for t in TIER_ORDER}
	for f in ranking:
		if f['rol'] in scoring.ROLES:
			tiers[f['tier']][f['rol']].append(f)
	tiers_list = [
		{'tier': t, 'clase': t.replace('+', 'P'), 'roles': [{'rol': r, 'jugadores': tiers[t][r]} for r in scoring.ROLES]}
		for t in TIER_ORDER
	]
	cortes = [{'tier': t, 'desde': u} for t, u in scoring.TIERS]

	return render(request, 'Cinturones/tier_list.html', {
		'tiers': tiers_list,
		'ranking': ranking,
		'premios': premios,
		'roles': scoring.ROLES,
		'cortes': cortes,
		'ajustes': scoring.ajustes_rol(),
		'jornada': jornada,
		'numero_partida': numero_partida,
		'jornadas_disponibles': jornadas_disponibles,
		'numeros_disponibles': numeros_disponibles,
		'minimo': minimo,
		'minimos': [1, 2, 3, 5],
		'total_jugadores': len(ranking),
	})


def exportar_csv_jugadores(request):
	"""Exporta los promedios de jugadores como CSV. Acepta ?jornada= para filtrar."""
	jornada = request.GET.get('jornada')
	qs = stats_de(request)
	if jornada:
		qs = qs.filter(partida__jornada=jornada)

	roles_qs = qs.values('jugador__id', 'rol').annotate(rol_count=Count('rol')).order_by('jugador__id', '-rol_count')
	rol_principal = {}
	for r in roles_qs:
		jid = r['jugador__id']
		if jid not in rol_principal:
			rol_principal[jid] = r['rol'] or ''

	def calcular_kda(kills, muertes, asistencias):
		if muertes == 0:
			return (kills + asistencias) * 1.0
		return ((kills + asistencias) * 1.0) / muertes

	agregados = qs.values('jugador__id', 'jugador__nombre').annotate(
		avg_kills=Sum('kills'),
		avg_muertes=Sum('muertes'),
		avg_asistencias=Sum('asistencias'),
		avg_kp=Avg('kp_porcentaje'),
		avg_oro_min=Avg('oro_min'),
		avg_dano_oro=Avg('dano_oro'),
		avg_dano_infligido=Avg('dano_infligido'),
		avg_porcentaje_dano_equipo=Avg('porcentaje_dano_equipo'),
		avg_dano_min=Avg('dano_min'),
		avg_dano_recibido=Avg('dano_recibido'),
		avg_cs=Avg('cs'),
		avg_cs_min=Avg('cs_min'),
		avg_vision_min=Avg('vision_min'),
		avg_double=Sum('double_kills'),
		avg_triple=Sum('triple_kills'),
		avg_quadra=Sum('quadra_kills'),
		avg_penta=Sum('penta_kills'),
		avg_game_time=Avg('game_time'),
		games_played=Count('partida__id'),
	).order_by('jugador__nombre')

	response = HttpResponse(content_type='text/csv; charset=utf-8')
	response['Content-Disposition'] = 'attachment; filename="promedios_jugadores.csv"'
	response.write('﻿')  # BOM para Excel

	writer = csv.writer(response)
	writer.writerow([
		'Jugador', 'Rol', 'K', 'D', 'A', 'KDA', 'KP %',
		'CS', 'CS/min', 'Oro/min', 'Dmg/min', 'Dmg Rec', '% Dmg', 'Dmg/Oro',
		'Visión/min', '2 kills', '3 kills', '4 kills', '5 kills',
		'Games', 'Tiempo medio',
	])
	for a in agregados:
		kills = a['avg_kills'] or 0
		muertes = a['avg_muertes'] or 0
		asistencias = a['avg_asistencias'] or 0
		writer.writerow([
			a['jugador__nombre'],
			rol_principal.get(a['jugador__id'], ''),
			kills,
			muertes,
			asistencias,
			round(calcular_kda(kills, muertes, asistencias), 2),
			round(float(a['avg_kp'] or 0), 2),
			round(float(a['avg_cs'] or 0), 2),
			round(float(a['avg_cs_min'] or 0), 2),
			round(float(a['avg_oro_min'] or 0), 2),
			round(float(a['avg_dano_min'] or 0), 2),
			round(float(a['avg_dano_recibido'] or 0), 2),
			round(float(a['avg_porcentaje_dano_equipo'] or 0), 2),
			round(float(a['avg_dano_oro'] or 0), 2),
			round(float(a['avg_vision_min'] or 0), 2),
			int(a['avg_double'] or 0),
			int(a['avg_triple'] or 0),
			int(a['avg_quadra'] or 0),
			int(a['avg_penta'] or 0),
			a['games_played'],
			round(float(a['avg_game_time'] or 0), 2),
		])
	return response


# FUNCIÓN DESACTIVADA POR SEGURIDAD - No se permite añadir partidas desde la web
# @user_passes_test(lambda u: u.is_superuser)
# def add_partida(request):
# 	"""Vista para que un administrador introduzca un match_id y datos complementarios y guarde la partida."""
# 	if request.method == 'POST':
# 		form = AddPartidaForm(request.POST)
# 		if form.is_valid():
# 			api_key = os.environ.get('RIOT_API_KEY') or getattr(settings, 'RIOT_API_KEY', None)
# 			match_id = form.cleaned_data['match_id']
# 			jornada = form.cleaned_data['jornada']
# 			numero_partida = form.cleaned_data['numero_partida']
# 			equipo_azul = form.cleaned_data['equipo_azul']
# 			equipo_rojo = form.cleaned_data['equipo_rojo']
# 
# 			if not api_key:
# 				messages.error(request, 'Se requiere API key para obtener datos de Riot.')
# 				return render(request, 'Cinturones/add_partida_form.html', {'form': form})
# 
# 			api_url = f"https://europe.api.riotgames.com/lol/match/v5/matches/{match_id}?api_key={api_key}"
# 			try:
# 				resp = requests.get(api_url)
# 				resp.raise_for_status()
# 			except Exception as e:
# 				messages.error(request, f'Error al obtener datos de la API')
# 				return render(request, 'Cinturones/add_partida_form.html', {'form': form})
# 
# 			data = extract_match_data(resp.text, equipo_azul, equipo_rojo)
# 			if not data:
# 				messages.error(request, 'No se pudieron extraer datos de la partida.')
# 				return render(request, 'Cinturones/add_partida_form.html', {'form': form})
# 
# 			save_to_django(data, jornada, numero_partida, equipo_azul, equipo_rojo)
# 			messages.success(request, f'Partida {match_id} guardada correctamente.')
# 			return redirect('add_partida')
# 	else:
# 		form = AddPartidaForm()
# 
# 	return render(request, 'Cinturones/add_partida_form.html', {'form': form})
