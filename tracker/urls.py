from django.urls import path
from . import views

urlpatterns = [
    path('', views.entry_list, name='entry_list'),
    path('register/', views.register, name='register'),
    path('entry/add/', views.entry_create, name='entry_create'),
    path('entry/<int:pk>/edit/', views.entry_update, name='entry_update'),
    path('entry/<int:pk>/delete/', views.entry_delete, name='entry_delete'),
    path('imdb/', views.imdb_page, name='imdb_page'),
    path('imdb/results/', views.imdb_results, name='imdb_results'),
    path('imdb/add/<str:imdb_id>/', views.imdb_add, name='imdb_add'),
]