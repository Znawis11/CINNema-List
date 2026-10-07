import requests
from django.conf import settings

URL = 'https://www.omdbapi.com/'

GENRES_RU = {
    'Action': 'Боевик', 'Adventure': 'Приключения', 'Animation': 'Мультфильм',
    'Comedy': 'Комедия', 'Crime': 'Криминал', 'Documentary': 'Документальный',
    'Drama': 'Драма', 'Family': 'Семейный', 'Fantasy': 'Фэнтези',
    'History': 'История', 'Horror': 'Хоррор', 'Music': 'Музыка',
    'Mystery': 'Детектив', 'Romance': 'Мелодрама', 'Sci-Fi': 'Фантастика',
    'Thriller': 'Триллер', 'War': 'Военный', 'Western': 'Вестерн',
    'Biography': 'Биография', 'Sport': 'Спорт',
}


def _get(params):
    params['apikey'] = settings.OMDB_API_KEY
    try:
        return requests.get(URL, params=params, timeout=10).json()
    except (requests.RequestException, ValueError):
        return {}


def search(query):
    data = _get({'s': query})
    if data.get('Response') != 'True':
        return []
    return [r for r in data.get('Search', []) if r.get('Type') in ('movie', 'series')]


def details(imdb_id):
    data = _get({'i': imdb_id})
    return data if data.get('Response') == 'True' else None