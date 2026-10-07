"""Рейтинги фильма с разных сайтов: TMDB, IMDb, Rotten Tomatoes, Metacritic, Кинопоиск.

Всё кэшируется в полях модели Title, повторные запросы не выполняются.
"""
import requests
from django.conf import settings

from . import tmdb

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'


def _omdb(**params):
    if not settings.OMDB_API_KEY:
        return {}
    params['apikey'] = settings.OMDB_API_KEY
    try:
        r = requests.get('https://www.omdbapi.com/', params=params,
                         headers={'User-Agent': UA}, timeout=8)
        data = r.json()
    except (requests.RequestException, ValueError):
        return {}
    return data if data.get('Response') == 'True' else {}


def _rating_from(data, source):
    for item in data.get('Ratings', []):
        if item.get('Source') == source:
            return item.get('Value', '')
    return ''


def _kp(imdb_id):
    if not settings.KINOPOISK_API_KEY or not imdb_id:
        return None
    try:
        r = requests.get('https://api.kinopoisk.dev/v1.4/movie',
                         params={'imdbId': imdb_id},
                         headers={'X-API-KEY': settings.KINOPOISK_API_KEY,
                                  'User-Agent': UA},
                         timeout=8)
        data = r.json()
    except (requests.RequestException, ValueError):
        return None
    value = (data.get('rating') or {}).get('kp')
    try:
        return float(value) if value else None
    except (TypeError, ValueError):
        return None


def enrich(title, force=False):
    """Дозаполняет описание и рейтинги у Title. Ничего не делает, если всё уже есть."""
    changed = False

    # TMDB: рейтинг и описание
    if title.tmdb_id and (force or not title.tmdb_rating or not title.overview):
        d = tmdb.details(title.tmdb_type or 'movie', title.tmdb_id)
        if d:
            if force or not title.tmdb_rating:
                title.tmdb_rating = round(float(d.get('vote_average') or 0), 1) or None
            if force or not title.overview:
                title.overview = d.get('overview') or title.overview
            if force or not title.imdb_id:
                title.imdb_id = d.get('imdb_id') or title.imdb_id
            changed = True

    # OMDb: IMDb / Rotten Tomatoes / Metacritic (+ описание для ручных записей)
    if settings.OMDB_API_KEY and (force or not title.imdb_rating):
        data = _omdb(i=title.imdb_id) if title.imdb_id else {}
        if not data and title.name:
            data = _omdb(t=title.name, y=title.year or '')
        if data:
            try:
                title.imdb_rating = float(data.get('imdbRating', '')) or None
            except ValueError:
                title.imdb_rating = None
            title.rt_rating = _rating_from(data, 'Rotten Tomatoes')
            meta = data.get('Metascore', '')
            title.metacritic_rating = meta if meta and meta != 'N/A' else _rating_from(data, 'Metacritic')
            if not title.imdb_id and data.get('imdbID'):
                title.imdb_id = data['imdbID']
            if not title.overview and data.get('Plot') and data['Plot'] != 'N/A':
                title.overview = data['Plot']
            if not title.original_name and data.get('Title'):
                title.original_name = data['Title']
            poster = data.get('Poster', '')
            if not title.poster_url and poster and poster != 'N/A':
                title.poster_url = poster
            changed = True

    # Кинопоиск (необязательно)
    if settings.KINOPOISK_API_KEY and (force or not title.kp_rating):
        value = _kp(title.imdb_id)
        if value:
            title.kp_rating = value
            changed = True

    if changed:
        title.save(update_fields=['overview', 'tmdb_rating', 'imdb_rating',
                                  'rt_rating', 'metacritic_rating', 'kp_rating',
                                  'imdb_id', 'original_name', 'poster_url']
                   if title.pk else None)
    return title


def rating_cards(title, user_rating=None):
    """Список карточек рейтингов для вкладки «Информация»."""
    from . import imdbapi

    cards = []
    if title.imdb_rating:
        cards.append({'name': 'IMDb', 'value': f'{title.imdb_rating:g}',
                      'link': imdbapi.page_url(title.imdb_id), 'color': 'bg-warning text-dark'})
    if title.tmdb_rating:
        cards.append({'name': 'TMDB', 'value': f'{title.tmdb_rating:g}', 'link': '', 'color': 'bg-primary'})
    if title.rt_rating:
        cards.append({'name': 'Rotten Tomatoes', 'value': title.rt_rating, 'link': '', 'color': 'bg-danger'})
    if title.metacritic_rating:
        cards.append({'name': 'Metacritic', 'value': title.metacritic_rating, 'link': '', 'color': 'bg-success'})
    if title.kp_rating:
        cards.append({'name': 'Кинопоиск', 'value': f'{title.kp_rating:g}', 'link': '', 'color': 'bg-dark'})
    if user_rating:
        cards.append({'name': 'Ваша оценка', 'value': f'{user_rating}/5', 'link': '', 'color': 'bg-info text-dark'})
    return cards
