from django.db import models
from django.contrib.auth.models import User


class Genre(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class Title(models.Model):
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

    def __str__(self):
        return self.name


class Tag(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=50)

    def __str__(self):
        return self.name


class Entry(models.Model):
    STATUSES = [('watched', 'Просмотрено'),
                ('watching', 'В процессе'),
                ('planned', 'В планах')]
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.ForeignKey(Title, on_delete=models.CASCADE)
    status = models.CharField(max_length=10, choices=STATUSES, default='planned')
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    review = models.TextField(blank=True)
    tags = models.ManyToManyField(Tag, blank=True)
    added_at = models.DateTimeField(auto_now_add=True)
    watched_at = models.DateField(null=True, blank=True)

    class Meta:
        unique_together = ('user', 'title')

    def __str__(self):
        return f'{self.user} - {self.title}'


class Episode(models.Model):
    entry = models.ForeignKey(Entry, on_delete=models.CASCADE, related_name='episodes')
    season = models.PositiveIntegerField()
    number = models.PositiveIntegerField()
    watched_at = models.DateField(null=True, blank=True)


class Collection(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    entries = models.ManyToManyField(Entry, blank=True)

    def __str__(self):
        return self.name