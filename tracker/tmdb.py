import time

import requests
from django.conf import settings

BASE = 'https://api.themoviedb.org/3'
IMG = 'https://image.tmdb.org/t/p/w500'
TTL = 3600  # кэш ответов API на час
_cache = {}


def _get(path, **params):
    key = (path, tuple(sorted(params.items())))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]

    params['api_key'] = settings.TMDB_API_KEY
    params['language'] = 'ru-RU'
    data = {}
    try:
        r = requests.get(BASE + path, params=params, timeout=10)
        data = r.json()
    except (requests.RequestException, ValueError):
        data = {}
    _cache[key] = (time.time(), data)
    return data


def _movie(r):
    date = r.get('release_date') or r.get('first_air_date') or ''
    return {
        'id': r['id'],
        'media_type': r.get('media_type') or ('tv' if r.get('name') and not r.get('title') else 'movie'),
        'title': r.get('title') or r.get('name') or '',
        'original': r.get('original_title') or r.get('original_name') or '',
        'year': date[:4],
        'poster': IMG + r['poster_path'] if r.get('poster_path') else '',
        'rating': round(r.get('vote_average', 0), 1),
    }


def search(query):
    data = _get('/search/multi', query=query)
    out = []
    for r in data.get('results', []):
        if r.get('media_type') not in ('movie', 'tv'):
            continue
        out.append(_movie(r))
    return out


def popular():
    """Популярные фильмы (запасной источник для строки «Популярное сейчас»)."""
    data = _get('/movie/popular')
    return [_movie(r) for r in data.get('results', []) if r.get('poster_path')]


def details(media_type, tmdb_id):
    data = _get(f'/{media_type}/{tmdb_id}', append_to_response='credits')
    return data if data.get('id') else None


def season(tv_id, number):
    """Список серий сезона сериала (названия, длительность, даты выхода)."""
    data = _get(f'/tv/{tv_id}/season/{number}')
    if not data.get('episodes'):
        return None
    return {
        'name': data.get('name') or f'Сезон {number}',
        'episodes': [{
            'number': e.get('episode_number'),
            'name': e.get('name') or f'Серия {e.get("episode_number")}',
            'runtime': e.get('runtime'),
            'air_date': e.get('air_date') or '',
        } for e in data['episodes']],
    }


def keywords(media_type, tmdb_id):
    """Ключевые слова (теги) фильма с TMDB."""
    data = _get(f'/{media_type}/{tmdb_id}/keywords')
    if media_type == 'tv':
        items = data.get('results', [])
    else:
        items = data.get('keywords', [])
    return [k['name'] for k in items if k.get('name')][:24]
