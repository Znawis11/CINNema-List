from django.urls import path
from . import views

# Все адреса сайта. Порядок важен: более частные шаблоны (например
# film/imdb/<id>/) идут раньше общих (film/<тип>/<id>/).
urlpatterns = [
    # --- главная и учётные записи -------------------------------------------
    path('', views.home, name='home'),                       # главная: поиск и обзор
    path('register/', views.register, name='register'),      # регистрация
    path('profile/', views.profile, name='profile'),         # профиль и статистика

    # --- коллекция фильмов пользователя -------------------------------------
    path('collection/', views.entry_list, name='entry_list'),    # список + подборки
    path('entry/add/', views.entry_create, name='entry_create'), # добавить вручную
    path('entry/<int:pk>/edit/', views.entry_update, name='entry_update'),
    path('entry/<int:pk>/delete/', views.entry_delete, name='entry_delete'),
    path('entry/<int:pk>/', views.entry_detail, name='entry_detail'),  # карточка
    path('entry/<int:pk>/tags/', views.entry_tags, name='entry_tags'),  # статус/оценка/теги
    path('entry/<int:pk>/location/', views.entry_location, name='entry_location'),  # файл/стриминг
    path('entry/<int:pk>/episodes/', views.entry_episodes, name='entry_episodes'),   # отметка серий
    path('entry/<int:pk>/watched/', views.entry_watched, name='entry_watched'),      # авто-отметка из плеера
    path('entry/<int:pk>/episode-stream/', views.episode_stream, name='episode_stream'),  # ссылка серии

    # --- отдельная страница фильма (вне коллекции): описание + кнопка «Добавить»
    path('film/imdb/<str:imdb_id>/', views.film_by_imdb, name='film_by_imdb'),
    path('film/<str:media_type>/<int:tmdb_id>/', views.film_detail, name='film_detail'),

    # --- поиск и добавление фильмов через TMDB ------------------------------
    path('tmdb/', views.tmdb_page, name='tmdb_page'),
    path('tmdb/results/', views.tmdb_results, name='tmdb_results'),
    path('tmdb/add/<str:media_type>/<int:tmdb_id>/', views.tmdb_add, name='tmdb_add'),

    # --- просмотр: плеер и отдача файла -------------------------------------
    path('watch/<int:pk>/', views.watch, name='watch'),
    path('track/<int:pk>/', views.track_ping, name='track_ping'),   # пинг плеера
    path('stream/<int:pk>/', views.stream, name='stream'),          # отдача видео (Range)
    path('stream/<int:pk>/<int:ep_pk>/', views.stream, name='stream_ep'),

    # --- выбор видеофайла ----------------------------------------------------
    path('library/', views.library_page, name='library_page'),      # папки с фильмами
    path('library/browse/', views.browse, name='browse'),
    path('entry/<int:pk>/files/', views.file_pick, name='file_pick'),        # проводник
    path('entry/<int:pk>/file-match/', views.file_match, name='file_match'), # системный диалог
    path('entry/<int:pk>/file-match/list/', views.file_match_list, name='file_match_list'),

    # --- правовые документы (публичные, без входа в систему) ----------------
    path('legal/', views.legal_index, name='legal_index'),          # список документов
    path('legal/<str:page>/', views.legal_page, name='legal_page'), # конкретный документ
]
