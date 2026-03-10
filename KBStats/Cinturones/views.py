import os
import csv
from functools import cmp_to_key
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.db.models import Avg, Count
# from django.contrib.auth.decorators import user_passes_test  # DESACTIVADO
# from django.contrib import messages  # DESACTIVADO
import requests

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

		nombre_ganador = partida.ganador_equipo.nombre if partida.ganador_equipo else None
		if nombre_ganador == nombre_azul:
			stats_azul['victorias'] += 1
			stats_rojo['derrotas'] += 1
			if grupo_azul == grupo_rojo:
				h2h_wins[grupo_azul][nombre_azul][nombre_rojo] = h2h_wins[grupo_azul][nombre_azul].get(nombre_rojo, 0) + 1
		elif nombre_ganador == nombre_rojo:
			stats_rojo['victorias'] += 1
			stats_azul['derrotas'] += 1
			if grupo_rojo == grupo_azul:
				h2h_wins[grupo_rojo][nombre_rojo][nombre_azul] = h2h_wins[grupo_rojo][nombre_rojo].get(nombre_azul, 0) + 1

	clasificaciones_render = []
	for grupo in grupos:
		nombre_grupo = grupo['nombre']

		def comparar_equipos(eq_a, eq_b):
			# 1) Más victorias primero.
			if eq_a['victorias'] != eq_b['victorias']:
				return -1 if eq_a['victorias'] > eq_b['victorias'] else 1

			# 2) Más partidos jugados primero.
			if eq_a['jugados'] != eq_b['jugados']:
				return -1 if eq_a['jugados'] > eq_b['jugados'] else 1

			# 3) Desempate por enfrentamiento directo (head-to-head).
			a_vs_b = h2h_wins[nombre_grupo].get(eq_a['equipo'], {}).get(eq_b['equipo'], 0)
			b_vs_a = h2h_wins[nombre_grupo].get(eq_b['equipo'], {}).get(eq_a['equipo'], 0)
			if a_vs_b != b_vs_a:
				return -1 if a_vs_b > b_vs_a else 1

			# 4) Si persiste el empate, menos derrotas y luego nombre.
			if eq_a['derrotas'] != eq_b['derrotas']:
				return -1 if eq_a['derrotas'] < eq_b['derrotas'] else 1
			if eq_a['equipo'] < eq_b['equipo']:
				return -1
			if eq_a['equipo'] > eq_b['equipo']:
				return 1
			return 0

		equipos_ordenados = sorted(
			clasificaciones[nombre_grupo]['equipos'].values(),
			key=cmp_to_key(comparar_equipos)
		)
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
	sort = request.GET.get('sort')
	order = request.GET.get('order', 'desc')

	qs = StatsJugador.objects.all()
	if jornada:
		qs = qs.filter(partida__jornada=jornada)
	if jugador_q:
		qs = qs.filter(jugador__nombre__icontains=jugador_q)

	agregados = qs.values('jugador__id', 'jugador__nombre').annotate(
		avg_kills=Avg('kills'),
		avg_muertes=Avg('muertes'),
		avg_asistencias=Avg('asistencias'),
		avg_kda=Avg('kda'),
		avg_kp=Avg('kp_porcentaje'),
		avg_oro_min=Avg('oro_min'),
		avg_dano_infligido=Avg('dano_infligido'),
		avg_porcentaje_dano_equipo=Avg('porcentaje_dano_equipo'),
		avg_dano_min=Avg('dano_min'),
		avg_dano_recibido=Avg('dano_recibido'),
		avg_cs=Avg('cs'),
		avg_cs_min=Avg('cs_min'),
		avg_vision_min=Avg('vision_min'),
		avg_double=Avg('double_kills'),
		avg_triple=Avg('triple_kills'),
		avg_quadra=Avg('quadra_kills'),
		avg_penta=Avg('penta_kills'),
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
			'avg_kills': float(a['avg_kills'] or 0.0),
			'avg_muertes': float(a['avg_muertes'] or 0.0),
			'avg_asistencias': float(a['avg_asistencias'] or 0.0),
			'avg_kda': float(a['avg_kda'] or 0.0),
			'avg_kp': float(a['avg_kp'] or 0.0),
			'avg_oro_min': float(a['avg_oro_min'] or 0.0),
			'avg_dano_infligido': float(a['avg_dano_infligido'] or 0.0),
			'avg_porcentaje_dano_equipo': float(a['avg_porcentaje_dano_equipo'] or 0.0),
			'avg_dano_min': float(a['avg_dano_min'] or 0.0),
			'avg_dano_recibido': float(a['avg_dano_recibido'] or 0.0),
			'avg_cs': float(a['avg_cs'] or 0.0),
			'avg_cs_min': float(a['avg_cs_min'] or 0.0),
			'avg_vision_min': float(a['avg_vision_min'] or 0.0),
			'avg_double': float(a['avg_double'] or 0.0),
			'avg_triple': float(a['avg_triple'] or 0.0),
			'avg_quadra': float(a['avg_quadra'] or 0.0),
			'avg_penta': float(a['avg_penta'] or 0.0),
			'games_played': a['games_played'],
		})

	wants_html = request.GET.get('format') == 'html' or 'text/html' in request.META.get('HTTP_ACCEPT', '')
	if wants_html:
		return render(request, 'Cinturones/promedios_jugadores.html', {
			'jugadores': resultados,
			'jornada': jornada,
			'filtro_jugador': jugador_q,
			'sort': sort,
			'order': order,
			'jornadas_disponibles': list(jornadas_disponibles),
		})
	return JsonResponse({'jugadores': resultados, 'jornadas_disponibles': list(jornadas_disponibles)})


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
