from django.urls import path
from . import views

urlpatterns = [
    path('', views.entry_list, name='entry_list'),
    path('register/', views.register, name='register'),
    path('entry/add/', views.entry_create, name='entry_create'),
    path('entry/<int:pk>/edit/', views.entry_update, name='entry_update'),
    path('entry/<int:pk>/delete/', views.entry_delete, name='entry_delete'),
    path('tmdb/', views.tmdb_page, name='tmdb_page'),
    path('tmdb/results/', views.tmdb_results, name='tmdb_results'),
    path('tmdb/add/<str:media_type>/<int:tmdb_id>/', views.tmdb_add, name='tmdb_add'),
    path('watch/<int:pk>/', views.watch, name='watch'),
    path('stream/<int:pk>/', views.stream, name='stream'),
    path('library/', views.library_page, name='library_page'),
    path('library/browse/', views.browse, name='browse'),
]
