import csv
import io
import json
import os
import random
import string
import threading
import time
from datetime import timedelta

import requests
from django.conf import settings
from django.db import connection, transaction
from django.db.models import Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.http import require_POST

from .models import LadderPlayer, LadderUpdateState, ROL_CHOICES

# Solo superusuarios pueden acceder a la configuración
_superuser_required = user_passes_test(lambda u: u.is_active and u.is_superuser, login_url='/login/')

# ── Kblix game views ──────────────────────────────────────────────────────────

def index(request):
    return render(request, 'Kblix/index.html')


def sala(request, room_id):
    return render(request, 'Kblix/sala.html', {'room_id': room_id})


def crear_sala(request):
    room_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return redirect('kblix:sala', room_id=room_id)


# ── Ladder helpers ────────────────────────────────────────────────────────────

UPDATE_INTERVAL = timedelta(minutes=30)
_BATCH_SIZE     = 45

# Mapeo roles de StatsJugador → ROL_CHOICES
_ROL_MAP = {
    'top': 'TOP', 'toplane': 'TOP',
    'jgl': 'JUNGLE', 'jungla': 'JUNGLE', 'jungle': 'JUNGLE', 'jg': 'JUNGLE',
    'mid': 'MID', 'middle': 'MID',
    'adc': 'ADC', 'bot': 'ADC', 'botlane': 'ADC',
    'sup': 'SUPPORT', 'supp': 'SUPPORT', 'support': 'SUPPORT',
}


def _get_api_key():
    return os.environ.get('RIOT_API_KEY') or getattr(settings, 'RIOT_API_KEY', None)


def _get_stats_data(nombres):
    """Devuelve {nombre: {last_team, most_common_role}} consultando StatsJugador."""
    if not nombres:
        return {}
    try:
        from KBStats.Cinturones.models import Jugador as StatJugador, StatsJugador
    except ImportError:
        return {}

    jugadores = {j.nombre: j for j in StatJugador.objects.filter(nombre__in=nombres)}
    result = {}

    for nombre in nombres:
        jugador = jugadores.get(nombre)
        if not jugador:
            result[nombre] = {'last_team': None, 'most_common_role': None}
            continue

        last_stat = (
            StatsJugador.objects
            .filter(jugador=jugador)
            .exclude(equipo_nombre='').exclude(equipo_nombre__isnull=True)
            .order_by('-partida__created_at', '-id')
            .values('equipo_nombre')
            .first()
        )
        role_stat = (
            StatsJugador.objects
            .filter(jugador=jugador)
            .exclude(rol='').exclude(rol__isnull=True)
            .values('rol').annotate(c=Count('rol')).order_by('-c')
            .first()
        )
        raw_role = role_stat['rol'].lower() if role_stat else None
        result[nombre] = {
            'last_team':        last_stat['equipo_nombre'] if last_stat else None,
            'most_common_role': _ROL_MAP.get(raw_role) if raw_role else None,
        }

    return result


def _try_start_update():
    try:
        with transaction.atomic():
            state = LadderUpdateState.objects.select_for_update().get_or_create(pk=1)[0]
            if state.is_updating:
                return False
            overdue = (
                state.last_update is None
                or (timezone.now() - state.last_update) > UPDATE_INTERVAL
            )
            if not overdue:
                return False
            state.is_updating = True
            state.save(update_fields=['is_updating'])
            return True
    except Exception:
        return False


def _try_start_single_update():
    try:
        with transaction.atomic():
            state = LadderUpdateState.objects.select_for_update().get_or_create(pk=1)[0]
            if state.is_updating:
                return False
            state.is_updating = True
            state.update_progress = 0
            state.total_players = 1
            state.save(update_fields=['is_updating', 'update_progress', 'total_players'])
            return True
    except Exception:
        return False


def _riot_get(url: str, timeout: int = 15, retries: int = 3) -> requests.Response:
    """GET con reintento automático en 429 usando Retry-After."""
    for attempt in range(retries):
        r = requests.get(url, timeout=timeout)
        if r.status_code == 429:
            wait = int(r.headers.get('Retry-After', 10)) + 1
            print(f'  [Ladder] 429 rate-limit → esperando {wait}s (intento {attempt+1}/{retries})', flush=True)
            time.sleep(wait)
            continue
        return r
    raise Exception(f'Demasiados reintentos 429 en {url}')


def _update_single_player(p: LadderPlayer):
    api_key = _get_api_key()
    if not api_key:
        print(f'  [Ladder] ⚠ Sin RIOT_API_KEY — no se pueden actualizar rangos.', flush=True)
        return

    # 1. Resolver PUUID
    if not p.puuid:
        if not p.riot_id or '#' not in p.riot_id:
            print(f'  [Ladder] {p.nombre}: riot_id "{p.riot_id}" no tiene formato GameName#TAG — saltando', flush=True)
            return
        game_name, tag = p.riot_id.split('#', 1)
        print(f'  [Ladder] {p.nombre}: resolviendo PUUID para {p.riot_id}…', flush=True)
        r = _riot_get(
            f'https://europe.api.riotgames.com/riot/account/v1/accounts/'
            f'by-riot-id/{game_name}/{tag}?api_key={api_key}',
        )
        if not r.ok:
            print(f'  [Ladder] {p.nombre}: error PUUID HTTP {r.status_code} — {r.text[:120]}', flush=True)
            return
        p.puuid = r.json().get('puuid', '')
        p.save(update_fields=['puuid'])
        print(f'  [Ladder] {p.nombre}: PUUID OK ({p.puuid[:18]}…)', flush=True)

    # 2. Obtener rango SoloQ directamente por PUUID (endpoint moderno, sin summoner_id)
    print(f'  [Ladder] {p.nombre}: consultando rango…', flush=True)
    r = _riot_get(
        f'https://euw1.api.riotgames.com/lol/league/v4/entries/'
        f'by-puuid/{p.puuid}?api_key={api_key}',
    )
    if not r.ok:
        print(f'  [Ladder] {p.nombre}: error ranked HTTP {r.status_code} — {r.text[:120]}', flush=True)
        return

    solo = next((e for e in r.json() if e.get('queueType') == 'RANKED_SOLO_5x5'), None)
    if solo:
        p.tier   = solo.get('tier', '')
        p.rank   = solo.get('rank', '')
        p.lp     = solo.get('leaguePoints', 0)
        p.wins   = solo.get('wins', 0)
        p.losses = solo.get('losses', 0)
        print(f'  [Ladder] {p.nombre}: {p.tier} {p.rank} {p.lp} LP ({p.wins}V/{p.losses}D)', flush=True)
    else:
        p.tier = 'UNRANKED'
        print(f'  [Ladder] {p.nombre}: sin clasificar (no hay SoloQ)', flush=True)

    p.last_updated = timezone.now()
    p.save(update_fields=['tier', 'rank', 'lp', 'wins', 'losses', 'last_updated'])


def _ws_push(progress: int, total: int, nombre: str = '', done: bool = False):
    """Envía actualización al grupo WebSocket desde el hilo síncrono de fondo."""
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        cl = get_channel_layer()
        if cl:
            async_to_sync(cl.group_send)('ladder_updates', {
                'type':     'ladder.update',
                'progress': progress,
                'total':    total,
                'nombre':   nombre,
                'done':     done,
            })
    except Exception as e:
        print(f'[Ladder WS] push error: {e}', flush=True)


def _run_ladder_update():
    try:
        api_key = _get_api_key()
        print(f'[Ladder] API key: {"OK (" + str(len(api_key)) + " chars)" if api_key else "⚠ NO CONFIGURADA"}', flush=True)

        players = list(LadderPlayer.objects.filter(riot_id__isnull=False).exclude(riot_id=''))
        total_en_bd = LadderPlayer.objects.count()
        print(f'[Ladder] {len(players)} jugadores con riot_id (de {total_en_bd} en total).', flush=True)

        if not players:
            print('[Ladder] Sin jugadores con riot_id — nada que actualizar.', flush=True)
            LadderUpdateState.objects.filter(pk=1).update(
                is_updating=False, last_update=timezone.now(), update_progress=100, total_players=0,
            )
            return

        LadderUpdateState.objects.filter(pk=1).update(total_players=len(players), update_progress=0)
        print(f'[Ladder] Iniciando actualización de {len(players)} jugadores.', flush=True)

        for i, p in enumerate(players):
            try:
                _update_single_player(p)
                print(f'[Ladder] {i+1}/{len(players)} {p.nombre}: {p.tier} {p.rank} {p.lp}LP', flush=True)
            except Exception as e:
                print(f'[Ladder] Error {p.nombre}: {e}', flush=True)

            pct = round((i + 1) / len(players) * 100)
            LadderUpdateState.objects.filter(pk=1).update(update_progress=pct)
            _ws_push(pct, len(players), p.nombre)

            if (i + 1) % _BATCH_SIZE == 0 and i + 1 < len(players):
                print(f'[Ladder] Lote completado, esperando 60 s...', flush=True)
                time.sleep(60)
            elif i + 1 < len(players):
                time.sleep(60 / _BATCH_SIZE)

        LadderUpdateState.objects.filter(pk=1).update(
            is_updating=False, last_update=timezone.now(), update_progress=100,
        )
        _ws_push(100, len(players), done=True)
        print('[Ladder] Actualización completada.', flush=True)

    except Exception as e:
        print(f'[Ladder] Error crítico: {e}', flush=True)
        LadderUpdateState.objects.filter(pk=1).update(is_updating=False)
    finally:
        connection.close()


# ── Ladder views ──────────────────────────────────────────────────────────────

_SORT_KEYS = {
    'rank':    lambda p: p.rank_score,
    'winrate': lambda p: p.winrate or 0,
    'wins':    lambda p: p.wins,
    'losses':  lambda p: p.losses,
    'games':   lambda p: p.wins + p.losses,
}


def _build_players(equipo_filter, rol_filter, sort, sort_dir):
    """Lógica compartida entre ladder() y ladder_partial()."""
    qs = LadderPlayer.objects.filter(riot_id__isnull=False).exclude(riot_id='')
    if rol_filter:
        qs = qs.filter(rol=rol_filter)

    players = sorted(qs, key=_SORT_KEYS.get(sort, _SORT_KEYS['rank']), reverse=(sort_dir == 'desc'))

    nombres    = [p.nombre for p in players]
    stats_data = _get_stats_data(nombres)

    for p in players:
        sd = stats_data.get(p.nombre, {})
        p.display_team = p.equipo or sd.get('last_team') or '—'
        p.display_rol  = p.rol or sd.get('most_common_role') or ''
        p.total_games  = p.wins + p.losses

    if equipo_filter:
        players = [p for p in players if p.display_team == equipo_filter]

    return players


def ladder(request):
    state = LadderUpdateState.get()
    state.last_request = timezone.now()
    state.save(update_fields=['last_request'])

    if _try_start_update():
        threading.Thread(target=_run_ladder_update, daemon=True).start()

    rol_filter    = request.GET.get('rol', '')
    equipo_filter = request.GET.get('equipo', '')
    sort          = request.GET.get('sort', 'rank')
    sort_dir      = request.GET.get('dir', 'desc')

    players = _build_players(equipo_filter, rol_filter, sort, sort_dir)

    # Equipos únicos para el selector de filtro (calculados sobre todos los jugadores)
    all_player_nombres = list(LadderPlayer.objects.filter(riot_id__isnull=False).exclude(riot_id='').values_list('nombre', flat=True))
    all_stats_data = _get_stats_data(all_player_nombres)
    equipo_set = set()
    for ap in LadderPlayer.objects.filter(riot_id__isnull=False).exclude(riot_id=''):
        t = ap.equipo or all_stats_data.get(ap.nombre, {}).get('last_team') or ''
        if t:
            equipo_set.add(t)
    all_teams = sorted(equipo_set)

    return render(request, 'Kblix/ladder.html', {
        'players':        players,
        'state':          state,
        'all_teams':      all_teams,
        'equipo_filter':  equipo_filter,
        'rol_filter':     rol_filter,
        'sort':           sort,
        'sort_dir':       sort_dir,
        'rol_choices':    ROL_CHOICES,
    })


def ladder_status(request):
    state = LadderUpdateState.get()
    return JsonResponse({
        'is_updating': state.is_updating,
        'progress':    state.update_progress,
        'total':       state.total_players,
        'last_update': state.last_update.isoformat() if state.last_update else None,
    })


def ladder_partial(request):
    """Devuelve solo las filas <tr> del ladder para actualización en vivo."""
    equipo_filter = request.GET.get('equipo', '')
    rol_filter    = request.GET.get('rol', '')
    sort          = request.GET.get('sort', 'rank')
    sort_dir      = request.GET.get('dir', 'desc')
    players       = _build_players(equipo_filter, rol_filter, sort, sort_dir)
    return render(request, 'Kblix/_ladder_rows.html', {'players': players})


@_superuser_required
@require_POST
def ladder_force_update(request):
    """Fuerza una actualización inmediata. Sobreescribe cualquier flag atascado."""
    try:
        # Siempre forzamos: el admin tiene prioridad sobre el flag is_updating
        LadderUpdateState.objects.update_or_create(
            pk=1,
            defaults={'is_updating': True, 'last_update': None, 'update_progress': 0},
        )
    except Exception as e:
        return JsonResponse({'ok': False, 'reason': str(e)})

    threading.Thread(target=_run_ladder_update, daemon=True).start()
    return JsonResponse({'ok': True})


@_superuser_required
@require_POST
def ladder_player_force_update(request, player_id):
    """Fuerza la actualización manual de un único jugador de ladder."""
    player = LadderPlayer.objects.filter(pk=player_id).first()
    if not player:
        return JsonResponse({'ok': False, 'reason': 'Jugador no encontrado.'}, status=404)

    if not _try_start_single_update():
        return JsonResponse({'ok': False, 'reason': 'Ya hay una actualización en curso.'}, status=409)

    try:
        _update_single_player(player)
        LadderUpdateState.objects.filter(pk=1).update(
            is_updating=False,
            update_progress=100,
            last_update=timezone.now(),
            total_players=1,
        )
        return JsonResponse({'ok': True})
    except Exception as e:
        return JsonResponse({'ok': False, 'reason': str(e)})
    finally:
        LadderUpdateState.objects.filter(pk=1).update(is_updating=False)


# ── Ladder config (admin) ─────────────────────────────────────────────────────

@_superuser_required
def ladder_config(request):
    players = LadderPlayer.objects.all().order_by('nombre')

    # Jugadores de stats disponibles para añadir (no en el ladder aún)
    try:
        from KBStats.Cinturones.models import Jugador as StatJugador
        configured = set(players.values_list('nombre', flat=True))
        available = list(
            StatJugador.objects.values_list('nombre', flat=True)
            .order_by('nombre')
        )
        # Los ya configurados van al principio para búsqueda fácil
        available = [n for n in available if n not in configured]
    except ImportError:
        available = []

    return render(request, 'Kblix/ladder_config.html', {
        'players':    players,
        'available':  available,
        'rol_choices': ROL_CHOICES,
    })


@_superuser_required
@require_POST
def ladder_player_save(request, player_id=None):
    """Crea o edita un LadderPlayer. player_id=None → crear."""
    nombre  = request.POST.get('nombre', '').strip()
    riot_id = request.POST.get('riot_id', '').strip()
    rol     = request.POST.get('rol', '').strip()
    equipo  = request.POST.get('equipo', '').strip()

    if not nombre:
        return redirect('ladder_config')

    if player_id:
        p = LadderPlayer.objects.filter(pk=player_id).first()
        if not p:
            return redirect('ladder_config')
    else:
        p, _ = LadderPlayer.objects.get_or_create(nombre=nombre)

    if riot_id != p.riot_id:
        p.riot_id = riot_id
        p.puuid = p.summoner_id = ''
        p.tier = p.rank = ''
        p.lp = p.wins = p.losses = 0
        p.last_updated = None
    p.rol    = rol
    p.equipo = equipo
    p.nombre = nombre
    p.save()

    return redirect('ladder_config')


@_superuser_required
@require_POST
def ladder_player_delete(request, player_id):
    LadderPlayer.objects.filter(pk=player_id).delete()
    return JsonResponse({'ok': True})


@_superuser_required
def ladder_export_csv(request):
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = 'attachment; filename="ladder_config.csv"'

    writer = csv.writer(response)
    writer.writerow(['nombre', 'riot_id', 'rol', 'equipo', 'tier', 'rank', 'lp', 'wins', 'losses'])
    for p in LadderPlayer.objects.all().order_by('nombre'):
        writer.writerow([p.nombre, p.riot_id, p.rol, p.equipo, p.tier, p.rank, p.lp, p.wins, p.losses])

    return response


@_superuser_required
@require_POST
def ladder_sync_riot_ids(request):
    """Copia nombre → riot_id para todos los jugadores donde nombre contiene '#' y riot_id está vacío."""
    updated = (
        LadderPlayer.objects
        .filter(riot_id='', nombre__contains='#')
        .count()
    )
    for p in LadderPlayer.objects.filter(riot_id='', nombre__contains='#'):
        p.riot_id = p.nombre
        p.save(update_fields=['riot_id'])
    print(f'[Ladder] {updated} riot_ids sincronizados desde nombre.', flush=True)
    return redirect('ladder_config')


@_superuser_required
@require_POST
def ladder_import_from_stats(request):
    """Crea LadderPlayer para todos los Jugador de Cinturones que no estén ya en el ladder."""
    from KBStats.Cinturones.models import Jugador as StatJugador, StatsJugador

    existing = set(LadderPlayer.objects.values_list('nombre', flat=True))
    to_create = []

    for jugador in StatJugador.objects.select_related('equipo').all():
        if jugador.nombre in existing:
            continue

        equipo = jugador.equipo.nombre if jugador.equipo else ''

        role_stat = (
            StatsJugador.objects
            .filter(jugador=jugador)
            .exclude(rol='').exclude(rol__isnull=True)
            .values('rol').annotate(c=Count('rol')).order_by('-c')
            .first()
        )
        raw_role = role_stat['rol'].lower() if role_stat else ''
        rol = _ROL_MAP.get(raw_role, '')

        # Si el nombre ya tiene formato GameName#TAG, usarlo como riot_id directamente
        riot_id = jugador.nombre if '#' in jugador.nombre else ''
        to_create.append(LadderPlayer(nombre=jugador.nombre, riot_id=riot_id, equipo=equipo, rol=rol))

    if to_create:
        LadderPlayer.objects.bulk_create(to_create, ignore_conflicts=True)
        print(f'[Ladder] Importados {len(to_create)} jugadores desde estadísticas.', flush=True)

    return redirect('ladder_config')


@_superuser_required
@require_POST
def ladder_import_csv(request):
    f = request.FILES.get('csv_file')
    if not f:
        return redirect('ladder_config')

    reader = csv.DictReader(io.TextIOWrapper(f, encoding='utf-8-sig'))
    for row in reader:
        nombre = row.get('nombre', '').strip()
        if not nombre:
            continue

        p, _ = LadderPlayer.objects.get_or_create(nombre=nombre)

        new_riot_id = row.get('riot_id', '').strip()
        if new_riot_id and new_riot_id != p.riot_id:
            p.riot_id = new_riot_id
            p.puuid = p.summoner_id = ''
            p.tier = p.rank = ''
            p.lp = p.wins = p.losses = 0
            p.last_updated = None

        if row.get('rol', '').strip():
            p.rol = row['rol'].strip()
        if row.get('equipo', '').strip():
            p.equipo = row['equipo'].strip()
        for field, col in [('tier', 'tier'), ('rank', 'rank')]:
            if row.get(col, '').strip():
                setattr(p, field, row[col].strip())
        for field, col in [('lp', 'lp'), ('wins', 'wins'), ('losses', 'losses')]:
            try:
                setattr(p, field, int(row.get(col, '') or 0))
            except ValueError:
                pass
        p.save()

    return redirect('ladder_config')
