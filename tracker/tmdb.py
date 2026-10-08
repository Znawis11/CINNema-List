"""Клиент TMDB: поиск, детали фильма, сезоны сериала, жанры.

Ответы кэшируются на TTL, при ошибке сети флаг offline() становится True —
по нему шаблоны показывают «нет связи» вместо пустых карточек.
"""
import time

import requests
from django.conf import settings

BASE = 'https://api.themoviedb.org/3'
IMG = 'https://image.tmdb.org/t/p/w500'
TTL = 3600  # кэш ответов API на час
_cache = {}
_offline = False   # True, если последний запрос к TMDB не удалось выполнить


def _get(path, **params):
    """GET-запрос к API с кэшем и обработкой сетевых ошибок (не падает)."""
    global _offline
    key = (path, tuple(sorted(params.items())))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < TTL:
        _offline = hit[2]   # статус сети сохраняется вместе с ответом
        return hit[1]

    params['api_key'] = settings.TMDB_API_KEY
    params['language'] = 'ru-RU'
    data = {}
    try:
        r = requests.get(BASE + path, params=params, timeout=10)
        data = r.json()
        _offline = False
    except (requests.RequestException, ValueError):
        data = {}
        _offline = True
    _cache[key] = (time.time(), data, _offline)
    return data


def offline():
    """True, если последний запрос к TMDB завершился ошибкой сети."""
    return _offline


def _movie(r):
    """Приводит объект фильма из ответа TMDB к виду карточки для шаблона."""
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
    """Поиск фильмов и сериалов по названию (только movie/tv)."""
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


def find_by_imdb(imdb_id):
    """TMDB-id и тип медиа по IMDb-id (tt0111161 -> ('movie', 278)).

    Нужно для карточек «Популярное сейчас»: они приходят из IMDb, а
    страница фильма строится по данным TMDB. None — если TMDB не знает
    такой id (нет интернета, фильм отсутствует в базе).
    """
    if not imdb_id:
        return None
    data = _get('/find/' + imdb_id, external_source='imdb_id')
    for key in ('movie_results', 'tv_results'):   # сначала фильмы, потом сериалы
        for r in data.get(key) or []:
            if r.get('id'):
                return ('tv' if key == 'tv_results' else 'movie', r['id'])
    return None


def details(media_type, tmdb_id):
    """Подробности фильма: жанры, описание, актёры и внешние id (IMDb)."""
    data = _get(f'/{media_type}/{tmdb_id}', append_to_response='credits,external_ids')
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
