"""Временный скрипт: наполняет БД тестовыми фильмами для проверки UI."""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth.models import User
from tracker.models import Title, Entry, Genre, Tag
from tracker import ratings

SEED = [
    ('tt0133093', 'Матрица', 'The Matrix', 1999, 'Лана и Лилли Вачовски', 'movie', 'watched', 5),
    ('tt0816692', 'Интерстеллар', 'Interstellar', 2014, 'Кристофер Нолан', 'movie', 'watching', 4),
    ('tt7286456', 'Джокер', 'Joker', 2019, 'Тодд Филлипс', 'movie', 'planned', None),
]

user = User.objects.filter(username='uitest').first()
assert user, 'нет пользователя uitest'

for imdb_id, name, original, year, director, ttype, status, my_rating in SEED:
    title, created = Title.objects.get_or_create(
        name=name,
        defaults=dict(original_name=original, year=year, director=director,
                      type=ttype, duration_min=130, imdb_id=imdb_id))
    if not title.imdb_id:
        title.imdb_id = imdb_id
        title.save()
    ratings.enrich(title, force=True)
    if created:
        for g in ('фантастика', 'драма') if year != 1999 else ('фантастика', 'боевик'):
            genre, _ = Genre.objects.get_or_create(name=g.capitalize())
            title.genres.add(genre)
    entry, _ = Entry.objects.get_or_create(user=user, title=title)
    entry.status = status
    if my_rating:
        entry.rating = my_rating
    entry.save()

e = Entry.objects.get(user=user, title__name='Матрица')
for t in ('киберпанк', 'для компании'):
    tag, _ = Tag.objects.get_or_create(user=user, name=t)
    e.tags.add(tag)

print('готово, записей:', Entry.objects.filter(user=user).count())
for t in Title.objects.all():
    print(t.name, t.imdb_rating, t.rt_rating, t.metacritic_rating, bool(t.overview),
          t.poster_url[:60])
