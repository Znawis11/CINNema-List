import requests
from django.conf import settings

BASE = 'https://api.themoviedb.org/3'
IMG = 'https://image.tmdb.org/t/p/w500'


def _get(path, **params):
    params['api_key'] = settings.TMDB_API_KEY
    params['language'] = 'ru-RU'
    try:
        r = requests.get(BASE + path, params=params, timeout=10)
        return r.json()
    except (requests.RequestException, ValueError):
        return {}


def search(query):
    data = _get('/search/multi', query=query)
    out = []
    for r in data.get('results', []):
        if r.get('media_type') not in ('movie', 'tv'):
            continue
        date = r.get('release_date') or r.get('first_air_date') or ''
        out.append({
            'id': r['id'],
            'media_type': r['media_type'],
            'title': r.get('title') or r.get('name') or '',
            'year': date[:4],
            'poster': IMG + r['poster_path'] if r.get('poster_path') else '',
            'rating': round(r.get('vote_average', 0), 1),
        })
    return out


def details(media_type, tmdb_id):
    data = _get(f'/{media_type}/{tmdb_id}', append_to_response='credits')
    return data if data.get('id') else None