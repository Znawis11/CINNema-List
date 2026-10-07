# -*- coding: utf-8 -*-
"""Дымовой тест: проводник файлов, файл вне папок, файлы серий, стрим."""
import os
import tempfile
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import Client
from django.conf import settings

settings.ALLOWED_HOSTS.append('testserver')
from django.contrib.auth.models import User
from tracker.models import Entry, Title, Episode

c = Client()
u, _ = User.objects.get_or_create(username='uitest')
u.set_password('uitest12345')
u.save()
c.login(username='uitest', password='uitest12345')

movie = Entry.objects.filter(user=u, title__type='movie').first()
series = Entry.objects.filter(user=u, title__type='series').first()
if not movie:
    t = Title.objects.filter(type='movie').first()
    movie, _ = Entry.objects.get_or_create(user=u, title=t)

# --- временный видеофайл ВНЕ подключённых папок
tmpdir = tempfile.mkdtemp(prefix='pick_', dir=None)
path = os.path.join(tmpdir, 'My Movie.mp4')
with open(path, 'wb') as f:
    f.write(b'\x00' * 128)
print('файл вне папок:', path)

# 1) страница проводника
r = c.get(f'/entry/{movie.pk}/files/', {'path': tmpdir})
b = r.content.decode()
print('проводник:', r.status_code, '| папка видна:', tmpdir.split("/")[-1] in b,
      '| файл виден:', 'My Movie.mp4' in b)

# 2) привязка файла к фильму
r = c.post(f'/entry/{movie.pk}/files/', {'path': tmpdir, 'file': path})
print('привязка фильма:', r.status_code, '→', r.headers.get('Location', ''))
movie.title.refresh_from_db()
print('local_file сохранён:', movie.title.local_file == path)

# 3) стрим такого файла (вне папок!) должен отдаваться
r = c.get(f'/stream/{movie.title.pk}/')
data = b''.join(r.streaming_content) if r.status_code == 200 else b''
print('stream фильма:', r.status_code, '| байты:', len(data))

# 4) файл с недопустимым расширением не берётся
bad = os.path.join(tmpdir, 'evil.txt')
open(bad, 'w').write('x')
r = c.post(f'/entry/{movie.pk}/files/', {'path': tmpdir, 'file': bad})
movie.title.refresh_from_db()
print('txt отклонён:', movie.title.local_file == path)

# 5) вкладка плеера с файлом
r = c.get(f'/entry/{movie.pk}/', {'tab': 'player'})
b = r.content.decode()
print('плеер:', r.status_code, '| source:', '/stream/' in b,
      '| кнопка проводника:', 'file_pick' in b)

if series:
    # 6) страница проводника для серии (season/number в query)
    r = c.get(f'/entry/{series.pk}/files/', {'path': tmpdir, 'season': '1', 'number': '3'})
    b = r.content.decode()
    print('проводник для серии:', r.status_code, '| номер в форме:', 'name="number" value="3"' in b)

    # 7) привязка файла к серии
    ep_path = os.path.join(tmpdir, 'S01E03.mp4')
    open(ep_path, 'wb').write(b'\x00' * 64)
    r = c.post(f'/entry/{series.pk}/files/',
               {'path': tmpdir, 'file': ep_path, 'season': '1', 'number': '3'})
    ep = Episode.objects.filter(entry=series, season=1, number=3).first()
    print('привязка серии:', r.status_code, '| файл у серии:', bool(ep) and ep.local_file == ep_path)

    # 8) стрим серии
    r = c.get(f'/stream/{series.title.pk}/{ep.pk}/')
    data = b''.join(r.streaming_content) if r.status_code == 200 else b''
    print('stream серии:', r.status_code, '| байты:', len(data))

    # 9) чужая серия недоступна
    r = c.get(f'/stream/{series.title.pk}/999999/')
    print('чужая серия → 404:', r.status_code == 404)

    # 10) вкладка «Серии»: «Смотреть» у серии с файлом
    r = c.get(f'/entry/{series.pk}/', {'tab': 'episodes', 'season': '1'})
    b = r.content.decode()
    print('вкладка серий:', r.status_code, '| Смотреть:', '▶ Смотреть' in b,
          '| нет «Просмотрена»:', 'Просмотрена' not in b,
          '| есть ✓:', '✓' in b)

    # 11) вкладка плеера сериала: панель серий
    r = c.get(f'/entry/{series.pk}/', {'tab': 'player'})
    b = r.content.decode()
    print('плеер сериала:', r.status_code, '| панель серий:', 'Серия:' in b,
          '| stream_ep:', f'/stream/{series.title.pk}/' in b)

    # 12) авто-отметка (fetch из плеера)
    r = c.post(f'/entry/{series.pk}/episodes/',
               {'action': 'watch', 'season': '1', 'number': '3'},
               HTTP_X_FETCH='1')
    ep.refresh_from_db()
    print('fetch-ответ:', r.status_code, r.content[:40], '| watched_at:', ep.watched_at)
