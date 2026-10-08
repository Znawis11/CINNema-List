"""Популярные сейчас фильмы по данным IMDb.

IMDb не имеет официального открытого API, поэтому источники пробуются по очереди:
1. GraphQL-эндпоинт IMDb (тот же, что использует сам сайт imdb.com);
2. парсинг страницы чарта https://www.imdb.com/chart/moviemeter/;
3. запасной вариант — TMDB, чтобы строка не пустовала, если IMDb недоступен.
"""
import json
import re
import time

import requests

from . import tmdb

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')
TTL = 6 * 3600  # кэш популярных на 6 часов
_cache = {}

GRAPHQL_URL = 'https://caching.graphql.imdb.com/'
GRAPHQL_QUERY = """
query PopularTitles($limit: Int!) {
  popularTitles(limit: $limit) {
    titles {
      id
      titleText { text }
      titleType { id }
      releaseYear { year }
      ratingsSummary { aggregateRating }
      primaryImage { url }
    }
  }
}
"""

_CHART_URL = 'https://www.imdb.com/chart/moviemeter/'


def _http(url, **kw):
    """GET с браузерным User-Agent; None при ошибке или пустом ответе."""
    try:
        r = requests.get(url, headers={'User-Agent': UA,
                                       'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8'},
                         timeout=10, **kw)
        if r.status_code == 200 and r.text:
            return r.text
    except requests.RequestException:
        pass
    return ''


def _walk(node):
    """Обходит JSON-структуру, отдавая все словари."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _first(d, *paths, default=''):
    """Первое непустое значение по точечным путям: 'ratings.aggregateRating'."""
    for path in paths:
        cur = d
        for part in path.split('.'):
            if isinstance(cur, dict):
                cur = cur.get(part)
            else:
                cur = None
                break
        if cur is not None and cur != '':
            return cur
    return default


def _extract(d):
    """Словарь {'id', 'title', 'year', 'rating', 'poster'} или None."""
    raw = str(_first(d, 'id', 'imdbId', 'url'))
    m = re.search(r'(tt\d+)', raw)
    if not m:
        return None
    name = _first(d, 'titleText.text', 'titleText.name', 'primaryTitle',
                  'title', 'name')
    if not isinstance(name, str) or not name:
        return None
    year = _first(d, 'releaseYear.year', 'startYear', 'year')
    if isinstance(year, dict):
        year = year.get('year') or ''
    year = str(year)[:4] if str(year).isdigit() else ''
    rating = _first(d, 'ratingsSummary.aggregateRating', 'ratings.aggregateRating',
                    'aggregateRating.rating', 'rating', 'imdbRating',
                    'vote_average', default=None)
    try:
        rating = round(float(rating), 1) if rating not in (None, '', 'N/A') else None
    except (TypeError, ValueError):
        rating = None
    poster = _first(d, 'primaryImage.url', 'images.primary.url', 'image.url',
                    'poster.url', 'poster')
    if isinstance(poster, dict):
        poster = poster.get('url') or ''
    return {'id': m.group(1), 'title': name, 'year': year,
            'rating': rating, 'poster': str(poster)}


def _from_graphql(limit=20):
    """Данные с самого IMDb (GraphQL-запрос, который использует imdb.com)."""
    payload = {'query': GRAPHQL_QUERY, 'variables': {'limit': limit}}
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': UA,
        'Origin': 'https://www.imdb.com',
        'Referer': 'https://www.imdb.com/',
        'x-imdb-client-name': 'imdb-web',
        'x-imdb-client-version': 'web-consolidation-2025-07-15',
        'Accept': '*/*',
    }
    try:
        r = requests.post(GRAPHQL_URL, headers=headers,
                          data=json.dumps(payload), timeout=12)
        data = r.json()
    except (requests.RequestException, ValueError):
        return []
    titles = ((data.get('data') or {}).get('popularTitles') or {}).get('titles') or []
    out, movies = [], []
    for d in titles:
        item = _extract(d) if isinstance(d, dict) else None
        if item:
            out.append(item)
            # в строке «Популярное сейчас» — только фильмы, без сериалов
            if str(_first(d, 'titleType.id', default='movie')) == 'movie':
                movies.append(item)
    return movies or out


def _from_chart_page():
    """Парсинг страницы imdb.com/chart/moviemeter/ (встроенный JSON)."""
    text = _http(_CHART_URL)
    if not text:
        return []
    blobs = []
    for pattern in (r'<script[^>]*type="application/json"[^>]*>(.*?)</script>',
                    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>'):
        for m in re.finditer(pattern, text, re.S):
            try:
                blobs.append(json.loads(m.group(1)))
            except ValueError:
                pass

    out, seen = [], set()
    for blob in blobs:
        for d in _walk(blob):
            item = _extract(d)
            if item and item['id'] not in seen:
                seen.add(item['id'])
                out.append(item)
    return out


def _from_tmdb():
    """Запасной вариант, если IMDb недоступен."""
    return [{'id': '', **r} for r in tmdb.popular()]


def popular(limit=18):
    """Список популярных сейчас фильмов: [{id, title, year, rating, poster}]."""
    hit = _cache.get('popular')
    if hit and time.time() - hit[0] < TTL:
        return hit[1][:limit]

    items = _from_graphql(limit * 2) or _from_chart_page() or _from_tmdb()
    # без постера строка выглядит плохо — отбрасываем такие карточки
    items = [i for i in items if i.get('poster')][:limit] or items[:limit]
    _cache['popular'] = (time.time(), items)
    return items


def page_url(imdb_id):
    """Прямая ссылка на страницу фильма на IMDb (пусто, если id нет)."""
    return f'https://www.imdb.com/title/{imdb_id}/' if imdb_id else ''
