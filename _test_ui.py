"""Временная проверка представлений нового UI."""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import Client
from django.conf import settings
settings.ALLOWED_HOSTS.append('testserver')
from tracker.models import Entry, Tag

c = Client()
assert c.login(username='uitest', password='uitest12345'), 'login failed'

ok = []


def check(name, cond, extra=''):
    ok.append((name, bool(cond), extra))
    print(('OK  ' if cond else 'FAIL'), name, extra if not cond else '')


# страницы
r = c.get('/')
check('главная 200', r.status_code == 200, r.status_code)
check('строка IMDb', 'Популярное сейчас' in r.content.decode(), '')
check('нет дублей кнопок', r.content.decode().count('+ Добавить') == 1)

e = Entry.objects.get(user__username='uitest', title__name='Матрица')
for tab in ('info', 'tags', 'player'):
    r = c.get(f'/entry/{e.pk}/?tab={tab}')
    check(f'вкладка {tab}', r.status_code == 200, r.status_code)

r = c.get('/entry/99999/')
check('чужая карточка 404', r.status_code == 404, r.status_code)

# вкладка «Теги»: статус
r = c.post(f'/entry/{e.pk}/tags/', {'action': 'status', 'status': 'watching'})
check('redirect после статуса', r.status_code == 302, r.status_code)
e.refresh_from_db()
check('статус изменён', e.status == 'watching', e.status)

# оценка
c.post(f'/entry/{e.pk}/tags/', {'action': 'rating', 'rating': '3'})
e.refresh_from_db()
check('оценка изменена', e.rating == 3, e.rating)
c.post(f'/entry/{e.pk}/tags/', {'action': 'rating', 'rating': '0'})
e.refresh_from_db()
check('оценка сброшена', e.rating is None, e.rating)

# свои теги
c.post(f'/entry/{e.pk}/tags/', {'action': 'add_tag', 'name': 'проверка-тега'})
e.refresh_from_db()
check('тег добавлен', 'проверка-тега' in list(e.tags.values_list('name', flat=True)))
tag = Tag.objects.get(user__username='uitest', name='проверка-тега')
c.post(f'/entry/{e.pk}/tags/', {'action': 'remove_tag', 'remove': str(tag.pk)})
e.refresh_from_db()
check('тег удалён', 'проверка-тега' not in list(e.tags.values_list('name', flat=True)))

# поиск (htmx-фрагмент)
hx = {'HTTP_HX_REQUEST': 'true'}
r = c.get('/', {'q': 'матр'}, **hx)
check('поиск матр', 'Матрица' in r.content.decode() and 'Интерстеллар' not in r.content.decode())
r = c.get('/', {'q': 'нолан'}, **hx)
check('поиск по режиссёру', 'Интерстеллар' in r.content.decode())

# фильтры
r = c.get('/', {'status': 'planned'}, **hx)
body = r.content.decode()
check('фильтр статуса', 'Джокер' in body and 'Матрица' not in body)
r = c.get('/', {'min_rating': '5'}, **hx)
body = r.content.decode()
check('фильтр моей оценки', 'Матрица' in body and 'Интерстеллар' not in body)
r = c.get('/', {'min_score': '8'}, **hx)
body = r.content.decode()
check('фильтр рейтинга сайта', 'Матрица' in body and 'Джокер' not in body)
r = c.get('/', {'dur': 'lt60'}, **hx)
check('фильтр длительности', r.content.decode().count('card h-100') == 0 or 'Ничего' in r.content.decode())
r = c.get('/', {'type': 'series'}, **hx)
check('фильтр типа', 'Ничего не найдено' in r.content.decode())
r = c.get('/', {'sort': 'year'}, **hx)
check('сортировка по году', r.status_code == 200)

# жанр-фильтр
from tracker.models import Genre
g = Genre.objects.get(name='Боевик')
r = c.get('/', {'genres': [str(g.pk)]}, **hx)
body = r.content.decode()
check('фильтр по жанру', 'Матрица' in body and 'Джокер' not in body)

# тег-фильтр
t = Tag.objects.filter(user__username='uitest').first()
r = c.get('/', {'tags': [str(t.pk)]}, **hx)
check('фильтр по тегу', 'Матрица' in r.content.decode())

# пустой/битый запрос не роняет страницу
r = c.get('/', {'min_rating': 'abc', 'dur': 'zzz', 'sort': 'weird'}, **hx)
check('битые параметры', r.status_code == 200, r.status_code)

# поиск фильмов (tmdb-страница) и папки
r = c.get('/tmdb/?q=Матрица')
check('страница поиска', r.status_code == 200, r.status_code)
r = c.get('/library/')
check('страница папок', r.status_code == 200, r.status_code)

# просмотр перенесён во вкладку плеера
r = c.get(f'/watch/{e.title.pk}/')
check('watch → плеер', r.status_code == 302 and '/entry/' in r.url and 'tab=player' in r.url,
      f'{r.status_code} {getattr(r, "url", "")}')

# добавление вручную: форма и сохранение
r = c.get('/entry/add/')
check('форма добавления', r.status_code == 200, r.status_code)
r = c.post('/entry/add/', {'name': 'Тестовый фильм', 'director': 'X', 'type': 'movie',
                           'year': '2020', 'status': 'planned', 'new_tags': 'тест1, тест2'})
check('добавление вручную → карточка', r.status_code == 302 and '/entry/' in r.url,
      f'{r.status_code} {getattr(r, "url", "")}')

print()
print('Итого:', sum(1 for _, c_, _ in ok if c_), '/', len(ok), 'успешно')
fails = [n for n, c_, _ in ok if not c_]
if fails:
    print('Провалено:', fails)

