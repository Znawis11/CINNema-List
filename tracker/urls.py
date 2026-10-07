from django.urls import path
from . import views

urlpatterns = [
    path('', views.entry_list, name='entry_list'),
    path('register/', views.register, name='register'),
    path('entry/add/', views.entry_create, name='entry_create'),
    path('entry/<int:pk>/edit/', views.entry_update, name='entry_update'),
    path('entry/<int:pk>/delete/', views.entry_delete, name='entry_delete'),
    path('entry/<int:pk>/', views.entry_detail, name='entry_detail'),
    path('entry/<int:pk>/tags/', views.entry_tags, name='entry_tags'),
    path('tmdb/', views.tmdb_page, name='tmdb_page'),
    path('tmdb/results/', views.tmdb_results, name='tmdb_results'),
    path('tmdb/add/<str:media_type>/<int:tmdb_id>/', views.tmdb_add, name='tmdb_add'),
    path('watch/<int:pk>/', views.watch, name='watch'),
    path('library/', views.library_page, name='library_page'),
    path('library/browse/', views.browse, name='browse'),
    path('profile/', views.profile, name='profile'),
    path('entry/<int:pk>/episodes/', views.entry_episodes, name='entry_episodes'),
    path('entry/<int:pk>/files/', views.file_pick, name='file_pick'),
    path('entry/<int:pk>/file-match/', views.file_match, name='file_match'),
    path('entry/<int:pk>/file-match/list/', views.file_match_list, name='file_match_list'),
    path('track/<int:pk>/', views.track_ping, name='track_ping'),
    path('stream/<int:pk>/', views.stream, name='stream'),
    path('stream/<int:pk>/<int:ep_pk>/', views.stream, name='stream_ep'),
]
