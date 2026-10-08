"""Модели сайта: фильмы (Title), записи коллекции (Entry), серийность (Episode),
подборки (Collection), теги, папки библиотеки и сессии просмотра.

Пользователь работает через Entry — одна запись на (пользователя, фильм).
Title общий для всех: сведения из TMDB хранятся один раз на фильм.
"""
from django.db import models
from django.contrib.auth.models import User


class Genre(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class Title(models.Model):
    """Фильм/сериал: общие сведения (из TMDB) и привязанный локальный файл."""
    TYPES = [('movie', 'Фильм'), ('series', 'Сериал'), ('doc', 'Документальный')]
    name = models.CharField(max_length=255)
    director = models.CharField(max_length=255, blank=True)
    genres = models.ManyToManyField(Genre, blank=True)
    type = models.CharField(max_length=10, choices=TYPES, default='movie')
    year = models.PositiveIntegerField(null=True, blank=True)
    poster_url = models.URLField(blank=True)
    duration_min = models.PositiveIntegerField(default=100)
    tmdb_id = models.IntegerField(null=True, blank=True)
    tmdb_type = models.CharField(max_length=10, blank=True)  # movie или tv
    imdb_id = models.CharField(max_length=15, blank=True)
    original_name = models.CharField(max_length=255, blank=True)
    local_file = models.CharField(max_length=500, blank=True)
    overview = models.TextField(blank=True)
    total_episodes = models.PositiveIntegerField(null=True, blank=True)  # всех серий (из TMDB)
    # рейтинги с разных сайтов (кэшируются при добавлении/открытии фильма)
    tmdb_rating = models.FloatField(null=True, blank=True)
    imdb_rating = models.FloatField(null=True, blank=True)
    rt_rating = models.CharField(max_length=20, blank=True)        # Rotten Tomatoes, напр. "88%"
    metacritic_rating = models.CharField(max_length=20, blank=True)  # Metacritic, напр. "73"
    kp_rating = models.FloatField(null=True, blank=True)           # Кинопоиск (если задан ключ)

    def __str__(self):
        return self.name


class Tag(models.Model):
    """Пользовательский тег (фильтруется на главной, свой у каждого юзера)."""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=50)

    def __str__(self):
        return self.name


class Entry(models.Model):
    """Фильм в коллекции пользователя: статус, оценка, рецензия, где смотреть."""
    STATUSES = [('watched', 'Просмотрено'),
                ('watching', 'В процессе'),
                ('planned', 'В планах')]
    # где находится фильм: свой файл на ПК или стриминговый сервис
    LOCATIONS = [('local', 'Локально (файл на ПК)'),
                 ('streaming', 'Стриминг (по ссылке)')]
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.ForeignKey(Title, on_delete=models.CASCADE)
    status = models.CharField(max_length=10, choices=STATUSES, default='planned')
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    review = models.TextField(blank=True)
    location = models.CharField(max_length=10, choices=LOCATIONS, default='local')
    streaming_url = models.URLField(blank=True)   # страница фильма на стриминге
    tags = models.ManyToManyField(Tag, blank=True)
    added_at = models.DateTimeField(auto_now_add=True)
    watched_at = models.DateField(null=True, blank=True)

    class Meta:
        unique_together = ('user', 'title')

    def __str__(self):
        return f'{self.user} - {self.title}'


class Episode(models.Model):
    """Одна серия сериала: свои данные, независимые от других серий.

    У каждой серии хранится отдельно привязанный видеофайл (local_file)
    и своя ссылка на стриминг (streaming_url) — при переходе на другую
    серию данные этой серии никуда не деваются, потому что лежат здесь.
    """
    entry = models.ForeignKey(Entry, on_delete=models.CASCADE, related_name='episodes')
    season = models.PositiveIntegerField()
    number = models.PositiveIntegerField()
    watched_at = models.DateField(null=True, blank=True)
    local_file = models.CharField(max_length=500, blank=True)  # свой файл у серии
    # своя ссылка этой серии на стриминговый сервис (пусто — смотрим файл)
    streaming_url = models.URLField(blank=True)

    class Meta:
        # одна строка на (серию, сезон, номер) — данные не задвигаются
        unique_together = ('entry', 'season', 'number')

    def __str__(self):
        return f'{self.entry}: S{self.season}E{self.number}'


class Collection(models.Model):
    """Подборка: имя и произвольный набор фильмов пользователя (M2M)."""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    entries = models.ManyToManyField(Entry, blank=True)

    def __str__(self):
        return self.name


class LibraryFolder(models.Model):
    """Папка пользователя, в которой сканируются видеофайлы для плеера."""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    path = models.CharField(max_length=500)

    class Meta:
        unique_together = ('user', 'path')

    def __str__(self):
        return self.path


class WatchSession(models.Model):
    """Один сеанс просмотра в плеере: продлевается пингами каждые ~45 сек."""
    user = models.ForeignKey(User, on_delete=models.CASCADE,
                             related_name='watch_sessions')
    title = models.ForeignKey(Title, on_delete=models.CASCADE,
                              related_name='watch_sessions')
    started_at = models.DateTimeField(auto_now_add=True)
    last_ping = models.DateTimeField()
    seconds = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f'{self.user} - {self.title} ({self.seconds} c)'
