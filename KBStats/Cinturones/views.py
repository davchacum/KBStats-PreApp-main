import csv
from functools import cmp_to_key
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.db.models import Avg, Count, Sum
# from django.contrib.auth.decorators import user_passes_test  # DESACTIVADO
# from django.contrib import messages  # DESACTIVADO

from .models import Partida, StatsJugador
# from .forms import AddPartidaForm  # DESACTIVADO
# from .utils import extract_match_data, save_to_django  # DESACTIVADO


def _leer_grupos_desde_seed():
	"""Lee `seed_grupos.csv` y devuelve [{nombre, equipos}, ...]."""
	seed_path = settings.BASE_DIR / 'seed_grupos.csv'
	grupos = []

	if not seed_path.exists():
		return grupos

	with seed_path.open(mode='r', encoding='utf-8', newline='') as csv_file:
		reader = csv.reader(csv_file)
		for row in reader:
			if not row:
				continue
			nombre_grupo = row[0].strip()
			equipos = [equipo.strip() for equipo in row[1:] if equipo and equipo.strip()]
			if nombre_grupo and equipos:
				grupos.append({'nombre': nombre_grupo, 'equipos': equipos})

	return grupos


def clasificacion_grupos(request):
	"""Muestra clasificación por grupo: PJ, V y D."""
	grupos = _leer_grupos_desde_seed()

	if not grupos:
		# messages.warning(request, 'No se encontró información de grupos en seed_grupos.csv.')  # DESACTIVADO
		return render(request, 'Cinturones/clasificacion_grupos.html', {'clasificaciones': []})

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

	partidas = (Partida.objects
		.select_related('equipo_azul', 'equipo_rojo', 'ganador_equipo')
		.all())

	for partida in partidas:
		nombre_azul = partida.equipo_azul.nombre if partida.equipo_azul else None
		nombre_rojo = partida.equipo_rojo.nombre if partida.equipo_rojo else None
		if not nombre_azul or not nombre_rojo:
			continue

		grupo_azul = equipo_a_grupo.get(nombre_azul)
		grupo_rojo = equipo_a_grupo.get(nombre_rojo)

		# Solo ignorar partidas con equipos no presentes en seed_grupos.csv.
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

	return render(
		request,
		'Cinturones/clasificacion_grupos.html',
		{'clasificaciones': clasificaciones_render},
	)


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

	partidas = (Partida.objects
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


def index(request):
	"""Página de inicio sencilla con enlaces a las vistas principales."""
	context = {
		'total_partidas': Partida.objects.count(),
		'total_jugadores': StatsJugador.objects.values_list('jugador', flat=True).distinct().count(),
	}
	return render(request, 'Cinturones/index.html', context)


def buscar_partidos_form(request):
	"""Muestra un formulario simple para introducir la jornada y buscar partidas.

	Envía una petición GET a la vista `buscar_partidos_por_jornada`.
	"""
	jornada = request.GET.get('jornada')
	sort = request.GET.get('sort')
	order = request.GET.get('order', 'asc')
	# Si se pasa jornada, filtrar por ella; si no, devolver todas las partidas
	# Mapa de campos permitidos para ordenar
	sort_map = {
		'jornada': 'jornada',
		'numero': 'numero_partida',
		'duracion': 'duracion_segundos',
		'equipo_azul': 'equipo_azul__nombre',
		'equipo_rojo': 'equipo_rojo__nombre',
		'ganador': 'ganador_equipo__nombre',
		'created': 'created_at',
	}
	if jornada:
		partidas_qs = (Partida.objects
			.filter(jornada=jornada)
			.select_related('equipo_azul', 'equipo_rojo', 'ganador_equipo'))
		# orden por defecto: numero_partida
		default_order = ['numero_partida']
	else:
		partidas_qs = (Partida.objects
			.all()
			.select_related('equipo_azul', 'equipo_rojo', 'ganador_equipo'))
		# orden por defecto: jornada, numero_partida
		default_order = ['jornada', 'numero_partida']

	# Aplicar orden si se solicita y es válido
	if sort in sort_map:
		field = sort_map[sort]
		if order == 'desc':
			field = f'-{field}'
		partidas_qs = partidas_qs.order_by(field)
	else:
		partidas_qs = partidas_qs.order_by(*default_order)

	# Construir estructura agrupada por jornada: lista de {jornada, partidas: [...]}
	partidas_result = []
	for p in partidas_qs:
		partidas_result.append({
			'id': p.id,
			'match_id': p.match_id,
			'jornada': p.jornada,
			'numero_partida': p.numero_partida,
			'equipo_azul': p.equipo_azul.nombre if p.equipo_azul else None,
			'equipo_rojo': p.equipo_rojo.nombre if p.equipo_rojo else None,
			'ganador_equipo': p.ganador_equipo.nombre if p.ganador_equipo else None,
			'duracion_segundos': f"{p.duracion_segundos//60}:{p.duracion_segundos%60:02}",
		})

	groups = []
	if jornada:
		# Si se filtró por jornada, crear un único grupo
		groups = [{
			'jornada': jornada,
			'partidas': partidas_result,
		}]
	else:
		# Agrupar por jornada en orden
		current_j = None
		for p in partidas_result:
			if p['jornada'] != current_j:
				current_j = p['jornada']
				groups.append({'jornada': current_j, 'partidas': [p]})
			else:
				groups[-1]['partidas'].append(p)

	total_partidas = Partida.objects.count()

	return render(
		request,
		'Cinturones/buscar_partidos_form.html',
		{'groups': groups, 'jornada': jornada, 'total_partidas': total_partidas},
	)


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

		return render(
			request,
			'Cinturones/partida_detail.html',
			{
				'partida': data,
				'equipo_azul': equipo_azul_nombre,
				'equipo_rojo': equipo_rojo_nombre,
				'ganador_equipo': partida.ganador_equipo.nombre if partida.ganador_equipo else None,
				'stats_azul': stats_azul,
				'stats_rojo': stats_rojo,
			},
		)

	return JsonResponse(data)


def promedios_jugadores(request):
	"""Devuelve el promedio de las estadísticas por jugador.

	Parámetros GET opcionales:
	- jornada: filtrar stats por `partida__jornada` antes de agregar
	- jugador: nombre (contiene) para filtrar jugadores específicos
	"""
	# Obtener las jornadas directamente desde la tabla Partida (evita duplicados nulos/vacíos)
	jornadas_disponibles = (Partida.objects
							 .exclude(jornada__isnull=True)
							 .exclude(jornada__exact='')
							 .values_list('jornada', flat=True)
							 .distinct()
							 .order_by('jornada'))
	jornada = request.GET.get('jornada')
	jugador_q = request.GET.get('jugador')
	rol_q = request.GET.get('rol')
	sort = request.GET.get('sort')
	order = request.GET.get('order', 'desc')

	qs = StatsJugador.objects.all()
	if jornada:
		qs = qs.filter(partida__jornada=jornada)
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

	def calcular_kda(kills, muertes, asistencias):
		if muertes == 0:
			return (kills + asistencias) * 1.0
		return ((kills + asistencias) * 1.0) / muertes

	agregados = qs.values('jugador__id', 'jugador__nombre').annotate(
		avg_kills=Sum('kills'),
		avg_muertes=Sum('muertes'),
		avg_asistencias=Sum('asistencias'),
		avg_kda=calcular_kda(Sum('kills'), Sum('muertes'), Sum('asistencias')),
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
			'avg_double': int(a['avg_double'] or 0.0),
			'avg_triple': int(a['avg_triple'] or 0.0),
			'avg_quadra': int(a['avg_quadra'] or 0.0),
			'avg_penta': int(a['avg_penta'] or 0.0),
			'avg_game_time': float(a['avg_game_time'] or 0.0),
			'games_played': a['games_played'],
			'rol_principal': rol_principal.get(a['jugador__id'], ''),
		})

	wants_html = request.GET.get('format') == 'html' or 'text/html' in request.META.get('HTTP_ACCEPT', '')
	if wants_html:
		return render(request, 'Cinturones/promedios_jugadores.html', {
			'jugadores': resultados,
			'jornada': jornada,
			'filtro_jugador': jugador_q,
			'filtro_rol': rol_q,
			'sort': sort,
			'order': order,
			'jornadas_disponibles': list(jornadas_disponibles),
		})
	return JsonResponse({'jugadores': resultados, 'jornadas_disponibles': list(jornadas_disponibles)})


def tier_list(request):
	# ── Estructura de ponderaciones (para el modal visual) ─────────────────
	DISPLAY_WEIGHTS = {
		'TOP': [
			('Combate',    [('K',7,False),('D',9,True),('A',5,False),('KP %',5,False)]),
			('Farmeo',     [('CS/min',14,False),('CS',7,False),('Oro/min',13,False)]),
			('Daño',       [('Dmg/min',12,False),('Dmg/Oro',7,False),('% Dmg',5,False),('Dmg Rec',5,True)]),
			('Visión',     [('Visión/min',6,False)]),
			('Multi-kill', [('2 kills',3,False),('3 kills',2,False)]),
		],
		'JGL': [
			('Combate',    [('K',9,False),('D',8,True),('A',6,False),('KP %',16,False)]),
			('Farmeo',     [('CS/min',9,False),('CS',6,False),('Oro/min',12,False)]),
			('Daño',       [('Dmg/min',7,False),('Dmg/Oro',5,False),('% Dmg',2,False)]),
			('Visión',     [('Visión/min',8,False)]),
			('Multi-kill', [('2 kills',4,False),('3 kills',4,False),('4 kills',2,False),('5 kills',2,False)]),
		],
		'MID': [
			('Combate',    [('K',8,False),('D',8,True),('A',6,False),('KP %',9,False)]),
			('Farmeo',     [('CS/min',12,False),('CS',5,False),('Oro/min',10,False)]),
			('Daño',       [('Dmg/min',15,False),('Dmg/Oro',8,False),('% Dmg',6,False)]),
			('Visión',     [('Visión/min',6,False)]),
			('Multi-kill', [('2 kills',2,False),('3 kills',2,False),('4 kills',2,False),('5 kills',1,False)]),
		],
		'ADC': [
			('Combate',    [('K',9,False),('D',10,True),('A',5,False),('KP %',5,False)]),
			('Farmeo',     [('CS/min',14,False),('CS',6,False),('Oro/min',11,False)]),
			('Daño',       [('Dmg/min',17,False),('Dmg/Oro',9,False),('% Dmg',7,False)]),
			('Visión',     [('Visión/min',4,False)]),
			('Multi-kill', [('2 kills',2,False),('3 kills',1,False)]),
		],
		'SUP': [
			('Combate',    [('K',4,False),('D',8,True),('A',14,False),('KP %',19,False)]),
			('Daño',       [('Dmg/min',8,False),('Dmg Rec',9,True),('% Dmg',3,False)]),
			('Economía',   [('Oro/min',8,False)]),
			('Visión',     [('Visión/min',26,False)]),
			('Multi-kill', [('2 kills',1,False)]),
		],
	}
	max_pct = 26
	roles_display = []
	for role, cats in DISPLAY_WEIGHTS.items():
		categories = []
		for cat_name, stats in cats:
			categories.append({
				'name': cat_name,
				'stats': [{'label': s[0], 'pct': s[1], 'pct_scaled': round(s[1] / max_pct * 100), 'inverse': s[2]} for s in stats],
			})
		roles_display.append({'role': role, 'categories': categories})

	# ── Ponderaciones numéricas para scoring ───────────────────────────────
	SCORE_WEIGHTS = {
		'TOP': {'k':.07,'d':.09,'a':.05,'kp':.05,'cs_min':.14,'cs':.07,'oro_min':.13,'dmg_min':.12,'dmg_oro':.07,'pct_dmg':.05,'dmg_rec':.05,'vision_min':.06,'double':.03,'triple':.02},
		'JGL': {'k':.09,'d':.08,'a':.06,'kp':.16,'cs_min':.09,'oro_min':.12,'cs':.06,'vision_min':.08,'dmg_min':.07,'dmg_oro':.05,'pct_dmg':.02,'double':.04,'triple':.04,'quadra':.02,'penta':.02},
		'MID': {'k':.08,'d':.08,'a':.06,'kp':.09,'dmg_min':.15,'dmg_oro':.08,'pct_dmg':.06,'cs_min':.12,'oro_min':.10,'cs':.05,'vision_min':.06,'double':.02,'triple':.02,'quadra':.02,'penta':.01},
		'ADC': {'k':.09,'d':.10,'a':.05,'kp':.05,'dmg_min':.17,'dmg_oro':.09,'pct_dmg':.07,'cs_min':.14,'oro_min':.11,'cs':.06,'vision_min':.04,'double':.02,'triple':.01},
		'SUP': {'k':.04,'d':.08,'a':.14,'kp':.19,'vision_min':.26,'dmg_rec':.09,'dmg_min':.08,'pct_dmg':.03,'oro_min':.08,'double':.01},
	}
	# clave scoring → campo en resultados
	FIELD_MAP = {
		'k':'avg_kills','d':'avg_muertes','a':'avg_asistencias','kda':'avg_kda',
		'kp':'avg_kp','oro_min':'avg_oro_min','dmg_oro':'avg_dano_oro',
		'pct_dmg':'avg_porcentaje_dano_equipo','dmg_min':'avg_dano_min',
		'dmg_rec':'avg_dano_recibido','cs':'avg_cs','cs_min':'avg_cs_min',
		'vision_min':'avg_vision_min','double':'avg_double','triple':'avg_triple',
		'quadra':'avg_quadra','penta':'avg_penta',
	}
	INVERSE_STATS = {'d', 'dmg_rec'}

	def _normalize(values):
		mn, mx = min(values), max(values)
		if mx == mn:
			return [0.5] * len(values)
		return [(v - mn) / (mx - mn) for v in values]

	def _assign_tier(score):
		if score >= 90: return 'S+'
		if score >= 80: return 'S'
		if score >= 70: return 'A'
		if score >= 60: return 'B'
		if score >= 50: return 'C'
		return 'D'

	# ── Filtros ────────────────────────────────────────────────────────────
	jornadas_disponibles = (Partida.objects
		.exclude(jornada__isnull=True).exclude(jornada__exact='')
		.values_list('jornada', flat=True).distinct().order_by('jornada'))
	jornada = request.GET.get('jornada')

	qs = StatsJugador.objects.all()
	if jornada:
		qs = qs.filter(partida__jornada=jornada)

	# ── Rol principal por jugador ──────────────────────────────────────────
	roles_qs = qs.values('jugador__id', 'rol').annotate(rol_count=Count('rol')).order_by('jugador__id', '-rol_count')
	rol_principal = {}
	for r in roles_qs:
		jid = r['jugador__id']
		if jid not in rol_principal:
			rol_principal[jid] = r['rol'] or ''

	# ── Misma agregación que promedios_jugadores ───────────────────────────
	def calcular_kda(kills, muertes, asistencias):
		if muertes == 0:
			return (kills + asistencias) * 1.0
		return ((kills + asistencias) * 1.0) / muertes

	agregados = qs.values('jugador__id', 'jugador__nombre').annotate(
		avg_kills=Sum('kills'),
		avg_muertes=Sum('muertes'),
		avg_asistencias=Sum('asistencias'),
		avg_kda=calcular_kda(Sum('kills'), Sum('muertes'), Sum('asistencias')),
		avg_kp=Avg('kp_porcentaje'),
		avg_oro_min=Avg('oro_min'),
		avg_dano_oro=Avg('dano_oro'),
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

	# ── Construir lista de jugadores con su rol ────────────────────────────
	jugadores = []
	for a in agregados:
		rol = rol_principal.get(a['jugador__id'], '')
		jugadores.append({
			'jugador_id': a['jugador__id'],
			'jugador_nombre': a['jugador__nombre'],
			'rol': rol,
			'avg_kills': float(a['avg_kills'] or 0),
			'avg_muertes': float(a['avg_muertes'] or 0),
			'avg_asistencias': float(a['avg_asistencias'] or 0),
			'avg_kda': float(a['avg_kda'] or 0),
			'avg_kp': float(a['avg_kp'] or 0),
			'avg_oro_min': float(a['avg_oro_min'] or 0),
			'avg_dano_oro': float(a['avg_dano_oro'] or 0),
			'avg_porcentaje_dano_equipo': float(a['avg_porcentaje_dano_equipo'] or 0),
			'avg_dano_min': float(a['avg_dano_min'] or 0),
			'avg_dano_recibido': float(a['avg_dano_recibido'] or 0),
			'avg_cs': float(a['avg_cs'] or 0),
			'avg_cs_min': float(a['avg_cs_min'] or 0),
			'avg_vision_min': float(a['avg_vision_min'] or 0),
			'avg_double': float(a['avg_double'] or 0),
			'avg_triple': float(a['avg_triple'] or 0),
			'avg_quadra': float(a['avg_quadra'] or 0),
			'avg_penta': float(a['avg_penta'] or 0),
			'avg_game_time': float(a['avg_game_time'] or 0),
			'games_played': a['games_played'],
		})

	# ── Scoring por grupo de rol ───────────────────────────────────────────
	by_role = {}
	for j in jugadores:
		by_role.setdefault(j['rol'], []).append(j)

	for rol, group in by_role.items():
		weights = SCORE_WEIGHTS.get(rol)
		if not weights:
			for j in group:
				j['score'] = 0.0
				j['tier'] = 'D'
			continue
		normalised = {}
		for skey, fkey in FIELD_MAP.items():
			if skey not in weights:
				continue
			vals = [p[fkey] for p in group]
			norm = _normalize(vals)
			normalised[skey] = [1 - v if skey in INVERSE_STATS else v for v in norm]
		for idx, j in enumerate(group):
			score = sum(normalised[sk][idx] * weights[sk] for sk in normalised) * 100
			j['raw_score'] = round(score, 1)

	# ── Factor multiplicador por partidas (global, no por rol) ───────────
	# Min partidas → ×1.00 · max partidas → ×1.20 (sin penalización)
	GAMES_MIN_FACTOR = 0.95  # pocas partidas → ×0.95, máximas → ×1.00
	all_games = [j['games_played'] for j in jugadores if 'raw_score' in j]
	g_max = max(all_games) if all_games else 1
	for j in jugadores:
		if 'raw_score' not in j:
			j['score'] = 0.0
			j['tier'] = 'D'
			continue
		games_norm = j['games_played'] / g_max if g_max > 0 else 1.0
		factor = GAMES_MIN_FACTOR + (1.0 - GAMES_MIN_FACTOR) * games_norm
		score = min(100.0, j['raw_score'] * factor)
		j['score'] = round(score, 1)
		j['tier'] = _assign_tier(score)

	# ── Agrupar por tier y rol para el template ───────────────────────────
	TIER_ORDER = ['S+', 'S', 'A', 'B', 'C', 'D']
	ROL_ORDER  = ['TOP', 'JGL', 'MID', 'ADC', 'SUP']
	tiers = {t: {r: [] for r in ROL_ORDER} for t in TIER_ORDER}
	for j in jugadores:
		rol = j['rol'] if j['rol'] in ROL_ORDER else 'TOP'
		tiers[j['tier']][rol].append(j)
	for t in TIER_ORDER:
		for r in ROL_ORDER:
			tiers[t][r].sort(key=lambda x: -x['score'])
	tiers_list = [
		{'tier': t, 'roles': [{'rol': r, 'jugadores': tiers[t][r]} for r in ROL_ORDER]}
		for t in TIER_ORDER
	]

	return render(request, 'Cinturones/tier_list.html', {
		'roles': roles_display,
		'tiers': tiers_list,
		'jornada': jornada,
		'jornadas_disponibles': list(jornadas_disponibles),
	})


def exportar_csv_jugadores(request):
	"""Exporta los promedios de jugadores como CSV. Acepta ?jornada= para filtrar."""
	jornada = request.GET.get('jornada')
	qs = StatsJugador.objects.all()
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
