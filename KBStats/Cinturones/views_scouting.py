"""Vistas de la sección Scouting."""

import time

import requests
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import PlayerAccount, ScoutedMatch, ScoutedPlayer
from .scouting_utils import (
    compute_player_aggregates,
    extract_jungle_analysis,
    extract_match_summary,
    fetch_match_ids,
    find_shared_games,
    get_api_key,
    resolve_puuid,
    ZONE_LABELS,
    ZONE_COLORS,
)


def scouting_home(request):
    players = ScoutedPlayer.objects.prefetch_related('accounts').order_by('identifier')
    # Attach quick match count to each player
    for p in players:
        p.match_count = ScoutedMatch.objects.filter(account__player=p).count()
    return render(request, 'Cinturones/scouting_list.html', {'players': players})


def scouting_add(request):
    if request.method == 'POST':
        identifier = request.POST.get('identifier', '').strip()
        notes      = request.POST.get('notes', '').strip()
        riot_ids   = [l.strip() for l in request.POST.get('riot_ids', '').splitlines() if l.strip()]

        if not identifier:
            return render(request, 'Cinturones/scouting_add.html',
                          {'error': 'El identificador es obligatorio.'})
        if not riot_ids:
            return render(request, 'Cinturones/scouting_add.html',
                          {'error': 'Añade al menos un Riot ID.'})

        player, _ = ScoutedPlayer.objects.get_or_create(
            identifier=identifier, defaults={'notes': notes}
        )
        player.notes = notes
        player.save()

        for i, riot_id in enumerate(riot_ids):
            PlayerAccount.objects.get_or_create(
                player=player, riot_id=riot_id,
                defaults={'is_main': i == 0},
            )

        return redirect('scouting_detail', player_id=player.pk)

    return render(request, 'Cinturones/scouting_add.html')


def scouting_detail(request, player_id):
    player   = get_object_or_404(ScoutedPlayer, pk=player_id)
    matches  = (ScoutedMatch.objects
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
        'jungle_matches': jungle_matches[:20],
        'zone_labels':    ZONE_LABELS,
        'zone_colors':    ZONE_COLORS,
    })


def scouting_fetch(request, player_id):
    """Fetches new ranked matches from the Riot API for all accounts. Returns JSON."""
    player  = get_object_or_404(ScoutedPlayer, pk=player_id)
    api_key = get_api_key()

    if not api_key:
        return JsonResponse({'error': 'RIOT_API_KEY no configurada'}, status=500)

    results = {'created': 0, 'skipped': 0, 'errors': 0, 'log': []}

    for account in player.accounts.all():
        # Resolve PUUID if missing
        if not account.puuid:
            puuid = resolve_puuid(account.riot_id, api_key)
            if not puuid:
                results['errors'] += 1
                results['log'].append(f'✗ No se pudo resolver PUUID para {account.riot_id}')
                continue
            account.puuid = puuid
            account.save()

        match_ids = fetch_match_ids(account.puuid, api_key, count=50)
        results['log'].append(f'● {account.riot_id}: {len(match_ids)} partidas encontradas')

        for match_id in match_ids:
            if ScoutedMatch.objects.filter(account=account, match_id=match_id).exists():
                results['skipped'] += 1
                continue

            try:
                match_url = (
                    f'https://europe.api.riotgames.com/lol/match/v5/matches/{match_id}'
                    f'?api_key={api_key}'
                )
                r = requests.get(match_url, timeout=20)
                r.raise_for_status()
                match_json = r.text

                summary = extract_match_summary(match_json, account.puuid)
                if not summary:
                    results['errors'] += 1
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

                if summary['role'] == 'JUNGLE':
                    time.sleep(0.5)
                    tl_url = (
                        f'https://europe.api.riotgames.com/lol/match/v5/matches/{match_id}'
                        f'/timeline?api_key={api_key}'
                    )
                    tr = requests.get(tl_url, timeout=20)
                    if tr.ok:
                        analysis = extract_jungle_analysis(tr.text, match_json, account.puuid)
                        if analysis:
                            sm.position_data = analysis['positions']
                            sm.jungle_stats  = analysis['jungle_stats']

                sm.save()
                results['created'] += 1
                role_tag = f', {summary["role"]}' if summary['role'] else ''
                results['log'].append(
                    f'  ✓ {match_id} ({summary["champion_name"]}{role_tag}, '
                    f'{"Victoria" if summary["win"] else "Derrota"})'
                )

            except Exception as e:
                results['errors'] += 1
                results['log'].append(f'  ✗ Error en {match_id}: {e}')

            time.sleep(0.5)

        account.last_fetched = timezone.now()
        account.save()

    return JsonResponse(results)


def scouting_jungle_detail(request, player_id, match_id):
    player = get_object_or_404(ScoutedPlayer, pk=player_id)
    match  = get_object_or_404(ScoutedMatch, account__player=player, match_id=match_id)
    stats  = match.jungle_stats or {}

    # Build zone distribution list sorted by %
    zone_dist = []
    for key, pct in stats.get('zone_pct', {}).items():
        zone_dist.append({
            'key':   key,
            'label': ZONE_LABELS.get(key, key),
            'color': ZONE_COLORS.get(key, '#6b7280'),
            'pct':   pct,
        })
    zone_dist.sort(key=lambda z: -z['pct'])

    early_dist = []
    for key, pct in stats.get('early_zone_pct', {}).items():
        early_dist.append({
            'key':   key,
            'label': ZONE_LABELS.get(key, key),
            'color': ZONE_COLORS.get(key, '#6b7280'),
            'pct':   pct,
        })
    early_dist.sort(key=lambda z: -z['pct'])

    # Format kill events
    kills = stats.get('kills_involving', [])
    for k in kills:
        mins = k['t'] // 60000
        secs = (k['t'] % 60000) // 1000
        k['time_str'] = f'{mins}:{secs:02d}'
        k['zone_label'] = ZONE_LABELS.get(k['zone'], k['zone'])

    return render(request, 'Cinturones/scouting_jungle.html', {
        'player':     player,
        'match':      match,
        'stats':      stats,
        'zone_dist':  zone_dist,
        'early_dist': early_dist,
        'kills':      kills,
    })


def scouting_jungle_heatmap_data(request, player_id, match_id):
    """Endpoint JSON para el heatmap de jungla."""
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
