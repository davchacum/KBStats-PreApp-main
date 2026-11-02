"""
Temporadas de la liga.

La lista está en `temporadas.csv` (raíz del proyecto), una temporada por línea y de la más antigua a la
más reciente:

    slug,nombre,archivo de partidas,archivo de grupos (opcional)

`python manage.py seed_temporadas` crea las temporadas, carga sus grupos y sus partidas.
La temporada que se ve en la web se elige en la barra superior (se guarda en la sesión); por defecto,
la más reciente que ya tiene partidas.
"""
import csv

from django.conf import settings

CONFIG = 'temporadas.csv'


def leer_config():
    """[{slug, nombre, partidas, grupos}, ...] en el orden del archivo (de la más antigua a la más reciente)."""
    ruta = settings.BASE_DIR / CONFIG
    if not ruta.exists():
        return []
    filas = []
    with ruta.open(encoding='utf-8', newline='') as f:
        for row in csv.reader(f):
            row = [c.strip() for c in row]
            if not row or not row[0] or row[0].startswith('#'):
                continue
            row += [''] * (4 - len(row))
            filas.append({'slug': row[0], 'nombre': row[1] or row[0], 'partidas': row[2], 'grupos': row[3]})
    return filas


def leer_grupos(nombre_archivo):
    """Lee un CSV de grupos (GRUPO,equipo,equipo,...) y devuelve [{nombre, equipos}, ...]."""
    if not nombre_archivo:
        return []
    ruta = settings.BASE_DIR / nombre_archivo
    if not ruta.exists():
        return []
    grupos = []
    with ruta.open(encoding='utf-8', newline='') as f:
        for row in csv.reader(f):
            if not row or not row[0].strip():
                continue
            equipos = [e.strip() for e in row[1:] if e and e.strip()]
            if equipos:
                grupos.append({'nombre': row[0].strip(), 'equipos': equipos})
    return grupos


def temporadas_con_partidas():
    """Temporadas que ya tienen partidas, de la más reciente a la más antigua."""
    from .models import Temporada
    return list(Temporada.objects.filter(partidas__isnull=False).distinct().order_by('-orden'))


def temporada_de(request):
    """La temporada elegida en esta petición (ver TemporadaMiddleware)."""
    return getattr(request, 'temporada', None)


class TemporadaMiddleware:
    """
    Pone en `request.temporada` la temporada que se está viendo.
    `?temporada=<slug>` la cambia y queda guardada en la sesión para el resto de páginas.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.temporada = None
        request.temporadas = []
        try:
            disponibles = temporadas_con_partidas()
        except Exception:   # la tabla aún no existe (antes de migrar)
            disponibles = []
        if disponibles:
            por_slug = {t.slug: t for t in disponibles}
            pedida = request.GET.get('temporada')
            if pedida in por_slug and hasattr(request, 'session'):
                request.session['temporada'] = pedida
            guardada = request.session.get('temporada') if hasattr(request, 'session') else None
            request.temporada = por_slug.get(pedida) or por_slug.get(guardada) or disponibles[0]
            request.temporadas = disponibles
        return self.get_response(request)


def contexto(request):
    """Context processor: la temporada actual y las disponibles (para el selector de la barra)."""
    return {'temporada': getattr(request, 'temporada', None), 'temporadas': getattr(request, 'temporadas', [])}
