"""Vistas de la sección Scouting."""

import time

import requests
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import PlayerAccount, ScoutedMatch, ScoutedPlayer, ROLE_CHOICES
from .scouting_utils import (
    ZONE_COLORS,
    ZONE_LABELS,
    compute_player_aggregates,
    extract_jungle_analysis,
    extract_match_summary,
    fetch_match_ids,
    find_shared_games,
    get_api_key,
    resolve_puuid,
)

# Cuántos match IDs pedir a la API (mayor que el objetivo para tener margen con el filtro de rol)
FETCH_IDS_COUNT    = 100
TARGET_MATCH_COUNT = 50
# Segundos entre peticiones (dev key: 100 req/2 min → mínimo 1.2 s)
REQUEST_DELAY      = 1.3


def _riot_get(url: str, timeout: int = 20, max_retries: int = 4) -> requests.Response:
    """GET con reintentos automáticos al recibir 429 usando el header Retry-After."""
    for attempt in range(max_retries):
        r = requests.get(url, timeout=timeout)
        if r.status_code == 429:
            wait = int(r.headers.get('Retry-After', 10)) + 1
            print(f'      [rate-limit] 429 → esperando {wait}s (intento {attempt + 1}/{max_retries})...', flush=True)
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r
    raise Exception(f'Demasiados reintentos (429) en {url}')


def scouting_home(request):
    players = ScoutedPlayer.objects.prefetch_related('accounts').order_by('identifier')
    for p in players:
        p.match_count = ScoutedMatch.objects.filter(account__player=p).count()
    return render(request, 'Cinturones/scouting_list.html', {'players': players})


def scouting_add(request):
    if request.method == 'POST':
        identifier     = request.POST.get('identifier', '').strip()
        preferred_role = request.POST.get('preferred_role', '').strip()
        notes          = request.POST.get('notes', '').strip()
        riot_ids       = [l.strip() for l in request.POST.get('riot_ids', '').splitlines() if l.strip()]

        if not identifier:
            return render(request, 'Cinturones/scouting_add.html',
                          {'error': 'El identificador es obligatorio.', 'role_choices': ROLE_CHOICES})
        if not riot_ids:
            return render(request, 'Cinturones/scouting_add.html',
                          {'error': 'Añade al menos un Riot ID.', 'role_choices': ROLE_CHOICES})

        player, _ = ScoutedPlayer.objects.get_or_create(
            identifier=identifier,
            defaults={'notes': notes, 'preferred_role': preferred_role},
        )
        player.notes          = notes
        player.preferred_role = preferred_role
        player.save()

        for i, riot_id in enumerate(riot_ids):
            PlayerAccount.objects.get_or_create(
                player=player, riot_id=riot_id,
                defaults={'is_main': i == 0},
            )

        return redirect('scouting_detail', player_id=player.pk)

    return render(request, 'Cinturones/scouting_add.html', {'role_choices': ROLE_CHOICES})


def scouting_detail(request, player_id):
    player     = get_object_or_404(ScoutedPlayer, pk=player_id)
    matches    = (ScoutedMatch.objects
                  .filter(account__player=player)
                  .select_related('account')
                  .order_by('-game_start'))
    aggregates     = compute_player_aggregates(matches)
    shared         = find_shared_games(player, matches)
    jungle_matches = matches.filter(role='JUNGLE')

    return render(request, 'Cinturones/scouting_detail.html', {
        'player':         player,
        'matches':        matches[:60],
        'aggregates':     aggregates,
        'shared':         shared[:15],
        'jungle_matches': jungle_matches,
        'role_choices':   ROLE_CHOICES,
    })


def scouting_edit(request, player_id):
    """Edita identificador, rol y notas. No toca las cuentas ya creadas."""
    player = get_object_or_404(ScoutedPlayer, pk=player_id)
    if request.method == 'POST':
        player.identifier     = request.POST.get('identifier', player.identifier).strip()
        player.preferred_role = request.POST.get('preferred_role', '').strip()
        player.notes          = request.POST.get('notes', '').strip()
        player.save()

        # Añadir nuevas cuentas si se indicaron
        new_ids = [l.strip() for l in request.POST.get('riot_ids', '').splitlines() if l.strip()]
        for riot_id in new_ids:
            PlayerAccount.objects.get_or_create(player=player, riot_id=riot_id)

        return redirect('scouting_detail', player_id=player.pk)

    return render(request, 'Cinturones/scouting_add.html', {
        'player':       player,
        'role_choices': ROLE_CHOICES,
        'edit':         True,
    })


def scouting_fetch(request, player_id):
    """
    Fetches new ranked matches from the Riot API.
    Si el jugador tiene preferred_role, solo guarda partidas de ese rol
    hasta alcanzar TARGET_MATCH_COUNT por cuenta.
    """
    player  = get_object_or_404(ScoutedPlayer, pk=player_id)
    api_key = get_api_key()

    if not api_key:
        return JsonResponse({'error': 'RIOT_API_KEY no configurada'}, status=500)

    target_role = player.preferred_role  # '' = sin filtro
    results = {'created': 0, 'skipped': 0, 'filtered': 0, 'errors': 0, 'log': []}

    role_label = target_role or 'todos los roles'
    print(f'\n[Scouting] {player.identifier} — rol: {role_label}', flush=True)

    for account in player.accounts.all():
        if not account.puuid:
            print(f'  [{account.riot_id}] Resolviendo PUUID...', flush=True)
            puuid = resolve_puuid(account.riot_id, api_key)
            if not puuid:
                msg = f'✗ No se pudo resolver PUUID para {account.riot_id}'
                results['errors'] += 1
                results['log'].append(msg)
                print(f'  {msg}', flush=True)
                continue
            account.puuid = puuid
            account.save()
            print(f'  [{account.riot_id}] PUUID resuelto: {puuid[:20]}...', flush=True)

        match_ids = fetch_match_ids(account.puuid, api_key, count=FETCH_IDS_COUNT)
        role_info = f' filtrando por {target_role}' if target_role else ''
        msg = f'● {account.riot_id}: {len(match_ids)} IDs obtenidos{role_info}'
        results['log'].append(msg)
        print(f'  {msg}', flush=True)

        saved_this_account = 0

        for idx, match_id in enumerate(match_ids, 1):
            if saved_this_account >= TARGET_MATCH_COUNT:
                print(f'  [{account.riot_id}] Límite de {TARGET_MATCH_COUNT} partidas alcanzado.', flush=True)
                break

            if ScoutedMatch.objects.filter(account=account, match_id=match_id).exists():
                results['skipped'] += 1
                print(f'    {idx}/{len(match_ids)} {match_id}: ya existe', flush=True)
                continue

            print(f'    {idx}/{len(match_ids)} {match_id}: ', end='', flush=True)

            try:
                match_url = (
                    f'https://europe.api.riotgames.com/lol/match/v5/matches/{match_id}'
                    f'?api_key={api_key}'
                )
                r = _riot_get(match_url)
                match_json = r.text

                summary = extract_match_summary(match_json, account.puuid)
                if not summary:
                    results['errors'] += 1
                    print('sin resumen', flush=True)
                    continue

                # Filtrar por rol si se especificó
                if target_role and summary['role'] != target_role:
                    results['filtered'] += 1
                    skipped_msg = (
                        f'  ↷ {match_id} ignorado ({summary["champion_name"]}, '
                        f'rol: {summary["role"] or "desconocido"})'
                    )
                    results['log'].append(skipped_msg)
                    print(f'↷ {summary["champion_name"]} (rol: {summary["role"] or "desconocido"})', flush=True)
                    time.sleep(REQUEST_DELAY)
                    continue

                sm = ScoutedMatch(
                    account=account,
                    match_id=match_id,
                    game_start=summary['game_start'],
                    game_duration=summary['game_duration'],
                    queue_id=summary['queue_id'],
                    champion_name=summary['champion_name'],
                    role=summary['role'],
                    team_id=summary['team_id'],
                    win=summary['win'],
                    kills=summary['kills'],
                    deaths=summary['deaths'],
                    assists=summary['assists'],
                    cs=summary['cs'],
                    vision_score=summary['vision_score'],
                    damage_dealt=summary['damage_dealt'],
                    gold_earned=summary['gold_earned'],
                    participants=summary['participants'],
                )

                # Para jungla, obtener también el timeline
                if summary['role'] == 'JUNGLE':
                    time.sleep(REQUEST_DELAY)
                    tl_url = (
                        f'https://europe.api.riotgames.com/lol/match/v5/matches/{match_id}'
                        f'/timeline?api_key={api_key}'
                    )
                    try:
                        tr = _riot_get(tl_url)
                        analysis = extract_jungle_analysis(tr.text, match_json, account.puuid)
                        if analysis:
                            sm.position_data = analysis['positions']
                            sm.jungle_stats  = analysis['jungle_stats']
                            print(f'[+timeline] ', end='', flush=True)
                    except Exception as tl_err:
                        print(f'[timeline-err: {tl_err}] ', end='', flush=True)

                sm.save()
                saved_this_account += 1
                results['created'] += 1
                result_msg = (
                    f'  ✓ {match_id} ({summary["champion_name"]}, '
                    f'{"Victoria" if summary["win"] else "Derrota"})'
                )
                results['log'].append(result_msg)
                print(
                    f'✓ {summary["champion_name"]} '
                    f'{"V" if summary["win"] else "D"} '
                    f'[{saved_this_account}/{TARGET_MATCH_COUNT}]',
                    flush=True,
                )

            except Exception as e:
                results['errors'] += 1
                results['log'].append(f'  ✗ Error en {match_id}: {e}')
                print(f'✗ {e}', flush=True)

            time.sleep(REQUEST_DELAY)

        summary_msg = f'  → {saved_this_account} partidas guardadas para {account.riot_id}'
        results['log'].append(summary_msg)
        print(summary_msg, flush=True)
        account.last_fetched = timezone.now()
        account.save()

    print(
        f'[Scouting] Fin: {results["created"]} nuevas, '
        f'{results["skipped"]} existentes, '
        f'{results["filtered"]} filtradas, '
        f'{results["errors"]} errores\n',
        flush=True,
    )

    return JsonResponse(results)


def scouting_jungle_detail(request, player_id, match_id):
    player = get_object_or_404(ScoutedPlayer, pk=player_id)
    match  = get_object_or_404(ScoutedMatch, account__player=player, match_id=match_id)
    stats  = match.jungle_stats or {}

    zone_dist = sorted(
        [{'key': k, 'label': ZONE_LABELS.get(k, k), 'color': ZONE_COLORS.get(k, '#6b7280'), 'pct': v}
         for k, v in stats.get('zone_pct', {}).items() if v > 0.5],
        key=lambda z: -z['pct'],
    )
    early_dist = sorted(
        [{'key': k, 'label': ZONE_LABELS.get(k, k), 'color': ZONE_COLORS.get(k, '#6b7280'), 'pct': v}
         for k, v in stats.get('early_zone_pct', {}).items() if v > 0.5],
        key=lambda z: -z['pct'],
    )

    kills = stats.get('kills_involving', [])
    for k in kills:
        mins = k['t'] // 60000
        secs = (k['t'] % 60000) // 1000
        k['time_str']   = f'{mins}:{secs:02d}'
        k['zone_label'] = ZONE_LABELS.get(k['zone'], k['zone'])

    # Pathing top vs bot (usando early game para reflejar intención de ruta)
    early_pct = stats.get('early_zone_pct', stats.get('zone_pct', {}))
    top_e = early_pct.get('top_lane', 0)
    bot_e = early_pct.get('bot_lane', 0)
    tb_sum = top_e + bot_e
    if tb_sum > 0:
        pathing_top_pct = round(top_e / tb_sum * 100)
        pathing_bot_pct = 100 - pathing_top_pct
        pathing_side    = 'top' if top_e >= bot_e else 'bot'
    else:
        pathing_top_pct = pathing_bot_pct = 0
        pathing_side    = None

    return render(request, 'Cinturones/scouting_jungle.html', {
        'player':          player,
        'match':           match,
        'stats':           stats,
        'zone_dist':       zone_dist,
        'early_dist':      early_dist,
        'kills':           kills,
        'pathing_side':    pathing_side,
        'pathing_top_pct': pathing_top_pct,
        'pathing_bot_pct': pathing_bot_pct,
    })


def scouting_jungle_heatmap_data(request, player_id, match_id):
    player = get_object_or_404(ScoutedPlayer, pk=player_id)
    match  = get_object_or_404(ScoutedMatch, account__player=player, match_id=match_id)

    if not match.position_data:
        return JsonResponse({'error': 'Sin datos de posición'}, status=404)

    team = match.jungle_stats.get('team', 100) if match.jungle_stats else 100
    return JsonResponse({
        'players': {
            '1': {
                'name':      match.account.riot_id,
                'team':      team,
                'positions': match.position_data,
            }
        },
        'kills':      [],
        'objectives': [],
    })


@require_POST
def scouting_delete(request, player_id):
    player = get_object_or_404(ScoutedPlayer, pk=player_id)
    player.delete()
    return redirect('scouting_home')


def scouting_export(request, player_id):
    """Genera un ZIP: index.html (visión general) + partidas/EUW1_xxx.html por partida de jungla."""
    import base64, io, zipfile
    import json as _json

    player         = get_object_or_404(ScoutedPlayer, pk=player_id)
    matches        = (ScoutedMatch.objects
                      .filter(account__player=player)
                      .select_related('account')
                      .order_by('-game_start'))
    aggregates     = compute_player_aggregates(matches)
    shared         = find_shared_games(player, list(matches))
    jungle_matches = matches.filter(role='JUNGLE')
    export_date    = timezone.now().strftime('%d/%m/%Y %H:%M')

    # ── Recursos estáticos ───────────────────────────────────────────
    kbstats_css = heatmap_js = map_b64 = ''
    try:
        from django.contrib.staticfiles.finders import find as _sfind
        css_p = _sfind('css/kbstats.css')
        if css_p:
            with open(css_p, 'r', encoding='utf-8') as f:
                kbstats_css = f.read()
        img_p = _sfind('images/f5da4bd98cb87704342fa1c6e4b6ab416aca990e-705x701.png')
        if img_p:
            with open(img_p, 'rb') as f:
                map_b64 = 'data:image/png;base64,' + base64.b64encode(f.read()).decode()
    except Exception:
        pass
    try:
        r = requests.get(
            'https://cdn.jsdelivr.net/npm/heatmap.js@2.0.5/build/heatmap.min.js',
            timeout=10,
        )
        if r.ok:
            heatmap_js = r.text
    except Exception:
        pass

    # ── Construir ZIP ────────────────────────────────────────────────
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:

        # index.html
        index_html = render_to_string('Cinturones/scouting_export_index.html', {
            'player':         player,
            'matches':        list(matches[:60]),
            'aggregates':     aggregates,
            'shared':         list(shared[:15]),
            'jungle_matches': jungle_matches,
            'kbstats_css':    kbstats_css,
            'export_date':    export_date,
        }, request)
        zf.writestr('index.html', index_html)

        # partidas/EUW1_xxx.html — una por partida de jungla con datos de posición
        for m in jungle_matches:
            if not m.position_data:
                continue
            stats = m.jungle_stats or {}

            kills = []
            for k in stats.get('kills_involving', []):
                mins = k['t'] // 60000
                secs = (k['t'] % 60000) // 1000
                kills.append({
                    **k,
                    'time_str':   f'{mins}:{secs:02d}',
                    'zone_label': ZONE_LABELS.get(k.get('zone', ''), k.get('zone', '')),
                })

            zone_dist = sorted(
                [{'key': k, 'label': ZONE_LABELS.get(k, k),
                  'color': ZONE_COLORS.get(k, '#6b7280'), 'pct': v}
                 for k, v in stats.get('zone_pct', {}).items() if v > 0.5],
                key=lambda z: -z['pct'],
            )
            early_dist = sorted(
                [{'key': k, 'label': ZONE_LABELS.get(k, k),
                  'color': ZONE_COLORS.get(k, '#6b7280'), 'pct': v}
                 for k, v in stats.get('early_zone_pct', {}).items() if v > 0.5],
                key=lambda z: -z['pct'],
            )

            early_pct    = stats.get('early_zone_pct', stats.get('zone_pct', {}))
            top_e = early_pct.get('top_lane', 0)
            bot_e = early_pct.get('bot_lane', 0)
            tb_sum = top_e + bot_e
            if tb_sum > 0:
                pathing_top  = round(top_e / tb_sum * 100)
                pathing_bot  = 100 - pathing_top
                pathing_side = 'top' if top_e >= bot_e else 'bot'
            else:
                pathing_top = pathing_bot = 0
                pathing_side = None

            match_html = render_to_string('Cinturones/scouting_export_match.html', {
                'player':         player,
                'match':          m,
                'stats':          stats,
                'zone_dist':      zone_dist,
                'early_dist':     early_dist,
                'kills':          kills,
                'pathing_top':    pathing_top,
                'pathing_bot':    pathing_bot,
                'pathing_side':   pathing_side,
                'team':           stats.get('team', 100),
                'positions_json': _json.dumps(m.position_data, ensure_ascii=False),
                'map_b64_json':   _json.dumps(map_b64),
                'heatmap_js':     heatmap_js,
                'kbstats_css':    kbstats_css,
                'export_date':    export_date,
            }, request)
            zf.writestr(f'partidas/{m.match_id}.html', match_html)

    buf.seek(0)
    safe_name = ''.join(c for c in player.identifier if c.isalnum() or c in '-_ ').strip()
    response = HttpResponse(buf.read(), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="scouting_{safe_name}.zip"'
    return response
