import json
import requests

URL = 'https://caching.graphql.imdb.com/'
H = {
    'Content-Type': 'application/json',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Origin': 'https://www.imdb.com',
    'Referer': 'https://www.imdb.com/',
    'x-imdb-client-name': 'imdb-web',
    'x-imdb-client-version': 'web-consolidation-2025-07-15',
    'Accept': '*/*',
}

def q(query):
    r = requests.post(URL, headers=H, data=json.dumps({'query': query}), timeout=15)
    print(r.status_code, r.text[:2500].replace(chr(10), ' '))
    print('===')

q('{ popularTitles(limit: 3) { titles { id titleText { text } releaseYear { year } ratingsSummary { aggregateRating } primaryImage { url } } } }')
