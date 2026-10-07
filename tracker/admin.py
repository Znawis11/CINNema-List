from django.contrib import admin
from .models import Genre, Title, Tag, Entry, Episode, Collection

admin.site.register([Genre, Title, Tag, Entry, Episode, Collection])