from django.contrib import admin
from .models import Genre, Title, Tag, Entry, Episode, Collection, WatchSession

admin.site.register([Genre, Title, Tag, Entry, Episode, Collection, WatchSession])