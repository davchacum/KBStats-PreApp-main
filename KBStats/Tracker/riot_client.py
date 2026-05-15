import time
import requests
from django.conf import settings

ROUTING = "europe"
_BASE = f"https://{ROUTING}.api.riotgames.com"

# 0.5 s entre llamadas → ~2 req/s, muy por debajo del límite de desarrollo (20 req/s)
# pero seguro para no saturar si se hacen 100 partidas × 2 endpoints = 200 llamadas (~1:40 min)
_DELAY = 0.5


def _get(url, params=None):
    headers = {"X-Riot-Token": settings.RIOT_API_KEY}
    r = requests.get(url, headers=headers, params=params, timeout=15)
    r.raise_for_status()
    time.sleep(_DELAY)
    return r.json()


def get_puuid(game_name: str, tag_line: str) -> dict:
    """Devuelve el account dict {puuid, gameName, tagLine}."""
    url = f"{_BASE}/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}"
    return _get(url)


def get_match_ids(puuid: str, count: int = 50, queue: int = None) -> list[str]:
    """Lista de match IDs del jugador. queue=None → todos los modos."""
    url = f"{_BASE}/lol/match/v5/matches/by-puuid/{puuid}/ids"
    params = {"count": count}
    if queue is not None:
        params["queue"] = queue
    return _get(url, params=params)


def get_match(match_id: str) -> dict:
    url = f"{_BASE}/lol/match/v5/matches/{match_id}"
    return _get(url)


def get_timeline(match_id: str) -> dict:
    url = f"{_BASE}/lol/match/v5/matches/{match_id}/timeline"
    return _get(url)
