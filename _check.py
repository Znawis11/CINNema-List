# -*- coding: utf-8 -*-
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import Client
from django.conf import settings

settings.ALLOWED_HOSTS.append('testserver')
from tracker.models import Entry

c = Client()
c.login(username='uitest', password='uitest12345')
e = Entry.objects.get(user__username='uitest', title__name='Матрица')
e.rating = 5
e.save()
r = c.get('/collection/', {'min_rating': '4'}, HTTP_HX_REQUEST='true')
b = r.content.decode()
print('Матрица:', 'Матрица' in b, '| Интерстеллар:', 'Интерстеллар' in b, '| Джокер:', 'Джокер' in b)
e.rating = None
e.save()
