from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.urls import reverse
from django.http import JsonResponse
from django.utils import timezone
from datetime import date, timedelta
from urllib.parse import quote
import re
import mimetypes
from pathlib import Path
from django.http import StreamingHttpResponse, Http404
from django.views.decorators.http import require_POST
from .forms import EntryForm
from .models import (Entry, Title, Genre, Tag, LibraryFolder, Episode,
                     WatchSession, Collection)
from . import tmdb, library, imdbapi, ratings


# --- фильтры коллекции -------------------------------------------------------

DURATIONS = [
    ('', 'Любая длительность'),
    ('lt60', 'До 60 мин'),
    ('60-90', '60–90 мин'),
    ('90-120', '90–120 мин'),
    ('120-150', '120–150 мин'),
    ('gte150', 'От 150 мин'),
]
_DURATION_TESTS = {
    'lt60': lambda d: d < 60,
    '60-90': lambda d: 60 <= d < 90,
    '90-120': lambda d: 90 <= d < 120,
    '120-150': lambda d: 120 <= d < 150,
    'gte150': lambda d: d >= 150,
}

SORTS = [
    ('added', 'Сначала добавленные'),
    ('year', 'По году'),
    ('name', 'По названию'),
    ('my', 'По моей оценке'),
    ('score', 'По рейтингу сайта'),
]

MY_RATINGS = [('', 'Любая моя оценка'), ('3', '★ 3 и выше'),
              ('4', '★ 4 и выше'), ('5', '★ только 5')]
SITE_RATINGS = [('', 'Любой рейтинг'), ('5', '5 и выше'), ('6', '6 и выше'),
                ('7', '7 и выше'), ('8', '8 и выше'), ('9', '9 и выше')]
REVIEWS = [('', 'Любые рецензии'), ('yes', 'С рецензией'), ('no', 'Без рецензии')]
LOCATIONS = [('', 'Локально и стриминг'), ('local', 'Только локальные'),
             ('streaming', 'Только стриминговые')]


def _site_score(entry):
    """Лучший из рейтингов сайтов (IMDb / TMDB / Кинопоиск) для карточки."""
    scores = [v for v in (entry.title.imdb_rating, entry.title.tmdb_rating,
                          entry.title.kp_rating) if v]
    return max(scores) if scores else None


def _with_scores(entries):
    """Предподсчёт рейтинга сайта: SQLite не умеет регистронезависимый поиск
    по кириллице, поэтому все фильтры ниже выполняются в Python."""
    for e in entries:
        e.site_score = _site_score(e)
    return entries


def _watched_minutes(entry):
    """Минуты, которые просмотренный фильм добавляет в общий счётчик времени.

    Фильм или док — просто его длительность. Сериал — длина серии
    (у сериала в duration_min хранится именно она), помноженная на число
    отмеченных просмотренных серий; если серии не отмечены, а фильм помечен
    просмотренным целиком, берём число всех серий из TMDB.
    """
    t = entry.title
    if t.type != 'series':
        return t.duration_min or 0
    n = sum(1 for ep in entry.episodes.all() if ep.watched_at)
    if not n and not entry.watched_at:
        return 0
    n = n or t.total_episodes or 1
    return n * (t.duration_min or 0)


@login_required
def home(request):
    """Главная: поиск фильмов в TMDB, популярное сейчас и последние добавления.

    Поиск на главной ищет только по базе TMDB (поиск по своей коллекции с
    фильтрами живёт на странице «Коллекция»).
    """
    recent = _with_scores(list(
        Entry.objects.filter(user=request.user)
        .select_related('title')
        .prefetch_related('title__genres', 'tags')
        .order_by('-added_at')[:6]))

    stats = Entry.objects.filter(user=request.user).aggregate(
        total=Count('id'), watched=Count('id', filter=Q(status='watched')))

    # предпочтения по жанрам — тот же подсчёт, что в профиле;
    # показывать имеет смысл, только если в коллекции есть хоть что-то
    genres = ({'labels': [], 'values': [], 'unit': 'ч'} if not stats['total']
              else _genre_chart(request.user,
                                _watch_stats(request.user)['genre_hours']))

    return render(request, 'tracker/home.html', {
        'q': request.GET.get('q', '').strip(),
        'popular': imdbapi.popular(18),
        'recent': recent,
        'stats': stats,
        'collections': Collection.objects.filter(user=request.user)
                                         .annotate(n=Count('entries'))
                                         .order_by('name')[:8],
        'has_search': True,
        'genres': genres,
    })


def register(request):
    """Регистрация: создаёт учётную запись и сразу входит в систему."""
    form = UserCreationForm(request.POST or None)
    if form.is_valid():
        login(request, form.save())
        return redirect('home')
    return render(request, 'registration/register.html', {'form': form})


def _collection_action(request):
    """CRUD подборок из страницы коллекции (POST)."""
    action = request.POST.get('action')
    name = (request.POST.get('name') or '').strip()[:100]
    coll_id = request.POST.get('collection') or request.POST.get('id')

    if action == 'create':
        if name:
            # подборка просто создаётся; остаёмся в основном списке, где её
            # можно наполнить, отметив фильмы галочками (см. entry_list)
            Collection.objects.create(user=request.user, name=name)
            messages.success(request, f'Подборка «{name}» создана — отметьте '
                                      f'в списке нужные фильмы галочками и '
                                      f'нажмите «Добавить в подборку».')
            return redirect('entry_list')
        messages.warning(request, 'Назовите подборку.')
        return redirect('entry_list')

    coll = Collection.objects.filter(pk=coll_id, user=request.user).first()
    if not coll:
        return redirect('entry_list')

    if action == 'rename':
        if name:
            coll.name = name
            coll.save(update_fields=['name'])
    elif action == 'delete':
        cname = coll.name
        coll.delete()
        messages.success(request, f'Подборка «{cname}» удалена.')
        return redirect('entry_list')
    elif action == 'add':
        # добавление в подборку: из её собственной страницы (select) и
        # из основного списка (галочки на карточках + селектор подборки)
        ids = request.POST.getlist('entries')
        entries = list(Entry.objects.filter(pk__in=ids, user=request.user))
        if entries:
            coll.entries.add(*entries)
            messages.success(request, f'В подборку «{coll.name}» добавлено: '
                                      f'{len(entries)}.')
        if request.POST.get('back') == 'main':
            # добавляли из основного списка — возвращаемся в него, чтобы
            # можно было сразу отметить следующую партию фильмов
            if not entries:
                messages.warning(request, 'Отметьте хотя бы один фильм галочкой.')
            return redirect('entry_list')
    elif action == 'remove':
        entry = coll.entries.filter(pk=request.POST.get('entry')).first()
        if entry:
            coll.entries.remove(entry)

    return redirect(f"{reverse('entry_list')}?collection={coll.pk}")


def _filter_entries(request):
    """Расширенный поиск по коллекции: (entries, ctx).

    Текстовый запрос ищет по названию, режиссёру, жанрам, своим тегам,
    рецензии и году; плюс фильтры по жанрам, тегам, длительности, оценкам,
    типу, наличию рецензии, месту просмотра и сортировка.

    SQLite не умеет регистронезависимый поиск по кириллице, поэтому всё
    это выполняется в Python (см. _with_scores).
    """
    entries = (Entry.objects.filter(user=request.user)
               .select_related('title')
               .prefetch_related('title__genres', 'tags'))

    status = request.GET.get('status', '')
    if status in dict(Entry.STATUSES):
        entries = entries.filter(status=status)
    entries = _with_scores(list(entries))

    q = request.GET.get('q', '').strip().lower()
    if q:
        entries = [e for e in entries if
                   q in e.title.name.lower()
                   or q in e.title.director.lower()
                   or q in e.review.lower()
                   or (e.title.year and q in str(e.title.year))
                   or any(q in g.name.lower() for g in e.title.genres.all())
                   or any(q in t.name.lower() for t in e.tags.all())]

    genres_sel = request.GET.getlist('genres')
    if genres_sel:
        entries = [e for e in entries
                   if any(str(g.pk) in genres_sel for g in e.title.genres.all())]

    tags_sel = request.GET.getlist('tags')
    if tags_sel:
        entries = [e for e in entries
                   if any(str(t.pk) in tags_sel for t in e.tags.all())]

    dur = request.GET.get('dur', '')
    if dur in _DURATION_TESTS:
        test = _DURATION_TESTS[dur]
        entries = [e for e in entries if test(e.title.duration_min or 0)]

    try:
        min_rating = int(request.GET.get('min_rating') or 0)
    except ValueError:
        min_rating = 0
    if min_rating:
        entries = [e for e in entries if e.rating and e.rating >= min_rating]

    try:
        min_score = int(request.GET.get('min_score') or 0)
    except ValueError:
        min_score = 0
    if min_score:
        entries = [e for e in entries if e.site_score and e.site_score >= min_score]

    title_type = request.GET.get('type', '')
    if title_type in dict(Title.TYPES):
        entries = [e for e in entries if e.title.type == title_type]

    # мои рецензии
    review = request.GET.get('review', '')
    if review == 'yes':
        entries = [e for e in entries if e.review.strip()]
    elif review == 'no':
        entries = [e for e in entries if not e.review.strip()]

    # где находится фильм: локально или на стриминге
    location = request.GET.get('location', '')
    if location in dict(Entry.LOCATIONS):
        entries = [e for e in entries if e.location == location]

    sort = request.GET.get('sort', 'added')
    if sort == 'year':
        entries.sort(key=lambda e: e.title.year or 0, reverse=True)
    elif sort == 'name':
        entries.sort(key=lambda e: e.title.name.lower())
    elif sort == 'my':
        entries.sort(key=lambda e: e.rating or 0, reverse=True)
    elif sort == 'score':
        entries.sort(key=lambda e: e.site_score or 0, reverse=True)
    else:
        entries.sort(key=lambda e: e.added_at, reverse=True)

    ctx = {'q': q, 'status': status, 'sort': sort,
           'dur': dur, 'min_rating': request.GET.get('min_rating', ''),
           'min_score': request.GET.get('min_score', ''), 'type': title_type,
           'review': review, 'location': location,
           'genres_sel': genres_sel, 'tags_sel': tags_sel,
           'durations': DURATIONS, 'sorts': SORTS, 'statuses': Entry.STATUSES,
           'types': Title.TYPES, 'my_ratings': MY_RATINGS,
           'site_ratings': SITE_RATINGS, 'reviews': REVIEWS,
           'locations': LOCATIONS,
           'all_genres': Genre.objects.all().order_by('name'),
           'all_tags': Tag.objects.filter(user=request.user).order_by('name'),
           'active_filters': len([1 for v in (q, status, dur, title_type,
                                              review, location,
                                              request.GET.get('min_rating'),
                                              request.GET.get('min_score'),
                                              genres_sel, tags_sel) if v])}
    return entries, ctx


@login_required
def entry_list(request):
    """Основной список коллекции + подборки слева.

    GET — карточки фильмов (с поиском, фильтрами и сортировкой), POST —
    действия с подборками (создание, добавление фильмов галочками и т. п.).
    """
    if request.method == 'POST':
        return _collection_action(request)

    entries, ctx = _filter_entries(request)

    # подборка — только на странице коллекции (на главной подборок нет)
    collection = request.GET.get('collection', '')
    active_collection = None
    other_entries = []
    if collection.isdigit():
        active_collection = Collection.objects.filter(
            pk=collection, user=request.user).first()
        if active_collection:
            ids = set(active_collection.entries.values_list('pk', flat=True))
            entries = [e for e in entries if e.pk in ids]
            other_entries = (Entry.objects.filter(user=request.user)
                             .exclude(pk__in=ids)
                             .select_related('title')
                             .order_by('title__name'))
        else:
            entries = []
        ctx['active_filters'] += 1

    # подборки пользователя (для сайдбара и для добавления галочками)
    collections = (Collection.objects.filter(user=request.user)
                   .annotate(n=Count('entries')).order_by('name'))

    # режим «галочек»: включается только в основном списке (без открытой
    # подборки) и только если подборки уже созданы — иначе добавлять некуда
    ctx.update(entries=entries, collection=collection, collections=collections,
               pick_mode=active_collection is None and bool(collections),
               active_collection=active_collection, other_entries=other_entries)

    if request.headers.get('HX-Request'):
        return render(request, 'tracker/_entry_cards.html', ctx)
    return render(request, 'tracker/entry_list.html', ctx)


@login_required
def entry_create(request):
    """Добавление фильма вручную (без поиска через TMDB)."""
    form = EntryForm(request.POST or None, user=request.user)
    if form.is_valid():
        entry = form.save()
        messages.success(request, f'«{entry.title.name}» добавлен в коллекцию.')
        return redirect('entry_list')
    return render(request, 'tracker/entry_form.html',
                  {'form': form, 'heading': 'Добавить'})


@login_required
def entry_update(request, pk):
    """Редактирование записи о фильме в коллекции."""
    entry = get_object_or_404(Entry, pk=pk, user=request.user)
    form = EntryForm(request.POST or None, instance=entry, user=request.user)
    if form.is_valid():
        form.save()
        return redirect(f"{reverse('entry_detail', args=[entry.pk])}?tab=info")
    return render(request, 'tracker/entry_form.html',
                  {'form': form, 'heading': 'Изменить'})


@login_required
def entry_delete(request, pk):
    """Удаление фильма из коллекции (GET — подтверждение, POST — удаление)."""
    entry = get_object_or_404(Entry, pk=pk, user=request.user)
    if request.method == 'POST':
        entry.delete()
        return redirect('entry_list')
    return render(request, 'tracker/entry_confirm_delete.html', {'entry': entry})


# --- карточка фильма: вкладки «Информация», «Теги», «Видеоплеер» -------------

def _series_ctx(request, entry, season=None):
    """Сезоны и серии сериала (общие для вкладок «Серии» и «Видеоплеер»).

    К каждой серии добавляются её СОБСТВЕННЫЕ данные из таблицы Episode:
    watched_at (отметка пользователя), local_file (привязанный видеофайл)
    и streaming_url (ссылка на эту серию) — поэтому при переходе на другую
    серию данные предыдущей никуда не пропадают.
    """
    title = entry.title
    watched = {(e.season, e.number): e for e in entry.episodes.all()}
    seasons, season_numbers = [], []
    if title.tmdb_id:
        d = tmdb.details('tv', title.tmdb_id)
        if d:
            seasons = [s for s in d.get('seasons', []) if s.get('season_number')]
            season_numbers = [s['season_number'] for s in seasons]
            total = d.get('number_of_episodes')
            if total and title.total_episodes != total:
                title.total_episodes = total
                title.save(update_fields=['total_episodes'])

    requested = season or request.GET.get('season', '')
    if requested and str(requested).isdigit() and (
            not season_numbers or int(requested) in season_numbers):
        current = int(requested)
    else:
        # первый сезон, где ещё нет ни одной просмотренной серии
        current = season_numbers[0] if season_numbers else 1
        for sn in season_numbers:
            if not any(k[0] == sn for k in watched):
                current = sn
                break

    episodes = []
    data = tmdb.season(title.tmdb_id, current) if title.tmdb_id else None
    for ep in (data['episodes'] if data else []):
        rec = watched.get((current, ep['number']))
        episodes.append({**ep,
                         'watched_at': rec.watched_at if rec else None,
                         'local_file': rec.local_file if rec else '',
                         'streaming_url': rec.streaming_url if rec else '',
                         'ep_pk': rec.pk if rec else None})
    # серии, отмеченные вручную, но не найденные в TMDB (например, сбитый номер)
    for (sn, num), rec in watched.items():
        if sn == current and not any(e['number'] == num for e in episodes):
            episodes.append({'number': num, 'name': f'Серия {num}',
                             'runtime': None, 'air_date': '',
                             'watched_at': rec.watched_at,
                             'local_file': rec.local_file,
                             'streaming_url': rec.streaming_url,
                             'ep_pk': rec.pk})
    episodes.sort(key=lambda e: e['number'])

    return {
        'seasons': seasons, 'season_numbers': season_numbers,
        'current_season': current, 'episodes': episodes,
        'watched_total': len(watched),
        'no_tmdb': not title.tmdb_id,
    }


@login_required
def entry_detail(request, pk):
    """Карточка фильма в коллекции: вкладки информация / плеер / серии / оценка.

    POST — привязка видеофайла: с season/number файл пишется в Episode
    конкретной серии, без них — в Title (обычный фильм).
    """
    entry = get_object_or_404(Entry, pk=pk, user=request.user)
    title = entry.title

    if request.method == 'POST':  # привязка видеофайла (вкладка «Видеоплеер»)
        path = request.POST.get('file', '')
        season = request.POST.get('season', '')
        number = request.POST.get('number', '')
        if library.safe_path(library.user_folders(request.user), path) \
                or library.resolve(path):
            # есть season/number — файл принадлежит конкретной серии
            # (_bind_path сам решит, в Episode или в Title его записать)
            return redirect(_bind_path(request, entry, path, season, number))
        return redirect(f"{reverse('entry_detail', args=[entry.pk])}?tab=player")

    tab = request.GET.get('tab', 'info')
    if tab not in ('info', 'tags', 'player', 'episodes'):
        tab = 'info'
    is_series = title.type == 'series' or title.tmdb_type == 'tv'
    if tab == 'episodes' and not is_series:
        tab = 'info'

    ctx = {'entry': entry, 'title': title, 'tab': tab, 'is_series': is_series,
           'statuses': Entry.STATUSES, 'stars': [1, 2, 3, 4, 5],
           'MEDIA': tmdb.IMG}

    if tab == 'info':
        ratings.enrich(title)
        details = (tmdb.details(title.tmdb_type or 'movie', title.tmdb_id)
                   if title.tmdb_id else None)
        ctx['details'] = details
        if details:
            cast = details.get('credits', {}).get('cast', [])
            ctx['cast'] = [c.get('name') for c in cast[:8]]
        ctx['rating_cards'] = ratings.rating_cards(title, entry.rating)

    elif tab == 'tags':
        ctx['tmdb_keywords'] = (tmdb.keywords(title.tmdb_type or 'movie',
                                              title.tmdb_id)
                                if title.tmdb_id else [])
        ctx['user_tags'] = Tag.objects.filter(user=request.user).order_by('name')

    else:  # player
        folders = library.user_folders(request.user)
        if not library.safe_path(folders, title.local_file) \
                and not library.resolve(title.local_file):
            title.local_file = library.find(folders, title.name, title.original_name)
            title.save(update_fields=['local_file'])
        ctx['has_folders'] = bool(folders)
        ctx['files'] = [] if title.local_file else library.scan(folders)

        if is_series:
            # какая серия играет (?ep=<pk эпизода>)
            current_ep = request.GET.get('ep', '')
            playing = (entry.episodes.filter(pk=current_ep).first()
                       if str(current_ep).isdigit() else None)
            # сезон для списка: у играющей серии — её собственный
            season = (playing.season if playing
                      else request.GET.get('season'))
            ctx.update(_series_ctx(request, entry, season=season))
            ctx['playing'] = playing

    if tab == 'episodes':
        ctx.update(_series_ctx(request, entry))

    return render(request, 'tracker/entry_detail.html', ctx)


@login_required
def entry_tags(request, pk):
    """Действия со вкладки «Теги»: статус, оценка, свои теги."""
    entry = get_object_or_404(Entry, pk=pk, user=request.user)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'status':
            value = request.POST.get('status')
            if value in dict(Entry.STATUSES):
                entry.status = value
                # дата просмотра нужна статистике (в какой месяц попадёт
                # длительность фильма), поэтому ставим её автоматически
                entry.watched_at = (timezone.localdate() if value == 'watched'
                                    else None)
                entry.save(update_fields=['status', 'watched_at'])
        elif action == 'rating':
            try:
                value = int(request.POST.get('rating') or 0)
            except ValueError:
                value = 0
            entry.rating = value if 1 <= value <= 5 else None
            entry.save(update_fields=['rating'])
        elif action == 'review':
            entry.review = (request.POST.get('review') or '').strip()[:10000]
            entry.save(update_fields=['review'])
        elif action == 'add_tag':
            name = request.POST.get('name', '').strip()[:50]
            if name:
                tag, _ = Tag.objects.get_or_create(user=request.user, name=name)
                entry.tags.add(tag)
        elif action == 'remove_tag':
            try:
                entry.tags.remove(Tag.objects.get(
                    pk=request.POST.get('remove'), user=request.user))
            except (Tag.DoesNotExist, TypeError, ValueError):
                pass
    return redirect(f"{reverse('entry_detail', args=[entry.pk])}?tab=tags")


def _streaming_url(raw):
    """Ссылка на страницу фильма на стриминге (приводим к http/https)."""
    url = (raw or '').strip()
    if not url:
        return ''
    if not re.match(r'^https?://', url, re.I):
        url = 'https://' + url.lstrip('/')
    return url


@login_required
@require_POST
def entry_location(request, pk):
    """Метка «где находится фильм»: локальный файл или стриминг."""
    entry = get_object_or_404(Entry, pk=pk, user=request.user)
    location = request.POST.get('location')
    if location in dict(Entry.LOCATIONS):
        entry.location = location
        entry.streaming_url = (_streaming_url(request.POST.get('streaming_url'))
                               if location == 'streaming' else '')
        entry.save(update_fields=['location', 'streaming_url'])
        if location == 'streaming' and not entry.streaming_url:
            messages.warning(request, 'Фильм отмечен как стриминговый — '
                                      'не забудьте указать ссылку на него.')
    return redirect(f"{reverse('entry_detail', args=[entry.pk])}?tab=player")


@login_required
@require_POST
def episode_stream(request, pk):
    """Ссылка конкретной серии на стриминг (пишется в Episode.streaming_url).

    Ссылка принадлежит серии, а не всему сериалу: при переходе на другую
    серию у каждой остаётся своя. Пустое поле — ссылку убираем.
    """
    entry = get_object_or_404(Entry, pk=pk, user=request.user)
    season = request.POST.get('season', '')
    number = request.POST.get('number', '')
    back = f"{reverse('entry_detail', args=[entry.pk])}?tab=player"
    if not (season.isdigit() and number.isdigit()):
        return redirect(back)

    # нормализуем вид ссылки и обрезаем по лимиту поля URLField (200 симв.)
    url = _streaming_url(request.POST.get('streaming_url'))[:200]
    ep, _ = Episode.objects.get_or_create(entry=entry, season=int(season),
                                          number=int(number))
    ep.streaming_url = url
    ep.save(update_fields=['streaming_url'])
    if url:
        messages.success(request, f'Ссылка для S{season}E{number} сохранена.')
    else:
        messages.info(request, f'Ссылка для S{season}E{number} удалена.')
    # возвращаемся к той же серии, чтобы сразу увидеть сохранённые данные
    return redirect(f'{back}&season={season}&ep={ep.pk}')


@login_required
@require_POST
def entry_watched(request, pk):
    """Отметка фильма просмотренным — вызывается плеером в конце видео.

    Длительность фильма сразу попадает в общий счётчик времени (см.
    _watch_stats), поэтому важно проставить и статус, и дату просмотра.
    """
    entry = get_object_or_404(Entry, pk=pk, user=request.user)
    if entry.status != 'watched':
        entry.status = 'watched'
        entry.watched_at = entry.watched_at or timezone.localdate()
        entry.save(update_fields=['status', 'watched_at'])
    return JsonResponse({'ok': True, 'status': entry.get_status_display(),
                         'watched_at': entry.watched_at})


@login_required
@require_POST
def entry_episodes(request, pk):
    """Отметка просмотренных серий (вкладка «Серии» карточки сериала)."""
    entry = get_object_or_404(Entry, pk=pk, user=request.user)
    season = request.POST.get('season', '')
    season = int(season) if season.isdigit() else 1
    number = request.POST.get('number', '')
    back = f"{reverse('entry_detail', args=[entry.pk])}?tab=episodes&season={season}"
    if not number.isdigit():
        return redirect(back)
    number = int(number)

    if request.POST.get('action') == 'unwatch':
        Episode.objects.filter(entry=entry, season=season, number=number).delete()
    else:
        # серия могла появиться раньше — при привязке файла или ссылки;
        # отметка просмотренной всё равно должна проставить дату
        ep, _ = Episode.objects.get_or_create(
            entry=entry, season=season, number=number,
            defaults={'watched_at': timezone.localdate()})
        if not ep.watched_at:
            ep.watched_at = timezone.localdate()
            ep.save(update_fields=['watched_at'])
            if entry.status == 'planned':
                entry.status = 'watching'
                entry.save(update_fields=['status'])

    # все серии просмотрены — закрываем сериал (считаем именно просмотренные,
    # а не все, у которых просто привязан файл)
    if entry.title.total_episodes:
        watched_count = entry.episodes.filter(watched_at__isnull=False).count()
        if watched_count >= entry.title.total_episodes and entry.status != 'watched':
            entry.status = 'watched'
            entry.watched_at = timezone.localdate()
            entry.save(update_fields=['status', 'watched_at'])
    if request.headers.get('X-Fetch'):  # авто-отметка из плеера
        return JsonResponse({'ok': True})
    return redirect(back)


# --- выбор видеофайла: системный диалог + проводник ---------------------------

def _bind_path(request, entry, chosen, season='', number=''):
    """Привязать файл к фильму или к серии; возвращает URL возврата."""
    back = f"{reverse('entry_detail', args=[entry.pk])}?tab=player"
    if season.isdigit() and number.isdigit():
        ep, _ = Episode.objects.get_or_create(
            entry=entry, season=int(season), number=int(number))
        ep.local_file = chosen
        ep.save(update_fields=['local_file'])
        # сразу открываем плеер на этой серии
        back += f'&season={season}&ep={ep.pk}'
    else:
        entry.title.local_file = chosen
        entry.title.save(update_fields=['local_file'])
    return back


def _pick_query(season='', number=''):
    """Query-строка для возврата season/number в URL ('' — если их нет)."""
    parts = []
    if season.isdigit():
        parts.append(f'season={season}')
    if number.isdigit():
        parts.append(f'number={number}')
    return ('?' + '&'.join(parts)) if parts else ''


@login_required
@require_POST
def file_match(request, pk):
    """Системный диалог выбора файла.

    Браузер не отдаёт путь выбранного файла — присылает имя и размер,
    сервер сам находит файл на диске. Нашёл один — привязывает сразу,
    нашёл несколько — отдаёт список, ничего не нашёл — уводит в проводник.
    """
    entry = get_object_or_404(Entry, pk=pk, user=request.user)
    season = request.POST.get('season', '')
    number = request.POST.get('number', '')
    name = (request.POST.get('name') or '').strip()
    try:
        size = int(request.POST.get('size') or 0)
    except ValueError:
        size = 0
    extra = _pick_query(season, number)          # '?season=1&number=2' или ''

    if not name or Path(name).name != name:
        return redirect(f"{reverse('file_pick', args=[entry.pk])}{extra}")

    found = library.locate(name, size if size > 0 else None,
                            _search_roots(request.user))

    if len(found) == 1:
        return redirect(_bind_path(request, entry, str(found[0]), season, number))

    if extra:                     # extra уже начинается с '?'
        extra = '&' + extra[1:]
    if len(found) > 1:
        return redirect(f"{reverse('file_match_list', args=[entry.pk])}"
                        f"?name={quote(name)}&size={size}{extra}")
    # не нашли — даём запасной выбор по папкам
    return redirect(f"{reverse('file_pick', args=[entry.pk])}"
                    f"?miss={quote(name)}{extra}")


def _search_roots(user):
    """Корни поиска: подключённые папки, домашняя папка, внешние диски."""
    roots = list(library.user_folders(user))
    home = str(Path.home())
    if home not in roots:
        roots.append(home)
    volumes = Path('/Volumes')
    if volumes.is_dir():
        roots += [str(v) for v in volumes.iterdir() if v.is_dir()]
    return roots


@login_required
def file_match_list(request, pk):
    """Нашлось несколько одноимённых файлов — выбрать нужный."""
    entry = get_object_or_404(Entry, pk=pk, user=request.user)
    name = request.GET.get('name', '').strip()
    try:
        size = int(request.GET.get('size') or 0)
    except ValueError:
        size = 0
    season = request.GET.get('season', '')
    number = request.GET.get('number', '')
    found = [str(p) for p in library.locate(name, size if size > 0 else None,
                                            _search_roots(request.user),
                                            limit=20)]
    if len(found) == 1:
        return redirect(_bind_path(request, entry, found[0], season, number))
    if not found:
        back = _pick_query(season, number)
        if back:
            back = '&' + back[1:]
        return redirect(f"{reverse('file_pick', args=[entry.pk])}"
                        f"?miss={quote(name)}{back}")
    return render(request, 'tracker/file_match_list.html', {
        'entry': entry, 'name': name, 'found': found,
        'season': season, 'number': number,
        'back': _pick_query(season, number)})


@login_required
def file_pick(request, pk):
    """Проводник: навигация по папкам и выбор видеофайла (mp4/mkv/avi).

    Привязывает файл к фильму, а с параметром season/number — к конкретной
    серии. Это запасной путь: основной — системный диалог (file_match).
    """
    entry = get_object_or_404(Entry, pk=pk, user=request.user)
    raw = request.GET.get('path') or request.POST.get('path') or ''
    try:
        p = Path(raw or Path.home()).expanduser().resolve()
    except OSError:
        p = Path.home()
    if not p.is_dir():
        p = Path.home()

    dirs, files = [], []
    try:
        for child in sorted(p.iterdir(), key=lambda d: (not d.is_dir(), d.name.lower())):
            if child.name.startswith('.'):
                continue
            if child.is_dir():
                dirs.append(child)
            elif child.suffix.lower() in library.PICK_EXT:
                files.append(child)
    except PermissionError:
        pass

    season = request.GET.get('season') or request.POST.get('season') or ''
    number = request.GET.get('number') or request.POST.get('number') or ''
    miss = request.GET.get('miss', '')
    error = ''

    if request.method == 'POST':   # выбрали файл в списке — привязываем
        chosen = request.POST.get('file', '')
        if library.resolve(chosen):
            return redirect(_bind_path(request, entry, chosen, season, number))
        error = 'Этот файл взять нельзя: нужен видеофайл mp4, mkv или avi.'

    ctx = {'path': p, 'dirs': dirs, 'files': files, 'entry': entry,
           'season': season, 'number': number, 'error': error, 'miss': miss,
           'parent': p.parent if p.parent != p else None,
           'qseason': f'&season={season}' if season.isdigit() else '',
           'qnumber': f'&number={number}' if number.isdigit() else ''}
    return render(request, 'tracker/file_pick.html', ctx)


# --- учёт времени просмотра (пишется плеером) --------------------------------

PING_GRACE = 180   # пауза дольше — это уже новый сеанс
PING_MAX = 90      # за один пинг не начисляем больше (45 с интервал + запас)


@login_required
@require_POST
def track_ping(request, pk):
    """Пинг от плеера: продлевает текущий сеанс просмотра."""
    title = get_object_or_404(Title, pk=pk)
    now = timezone.now()
    session = (WatchSession.objects
               .filter(user=request.user, title=title)
               .order_by('-last_ping').first())
    if session and (now - session.last_ping).total_seconds() < PING_GRACE:
        elapsed = int((now - session.last_ping).total_seconds())
        session.seconds += min(elapsed, PING_MAX)
        session.last_ping = now
        session.save(update_fields=['seconds', 'last_ping'])
    else:
        WatchSession.objects.create(user=request.user, title=title,
                                    last_ping=now)
    return JsonResponse({'ok': True})


# --- поиск и добавление фильмов через TMDB -----------------------------------

@login_required
def tmdb_page(request):
    """Страница перенесена на главную — старый адрес ведёт туда же."""
    q = request.GET.get('q', '').strip()
    return redirect(f"{reverse('home')}?q={quote(q)}" if q else reverse('home'))


@login_required
def tmdb_results(request):
    """Результаты поиска по TMDB (запрос htmx-формы на главной)."""
    q = request.GET.get('q', '').strip()
    results = tmdb.search(q) if len(q) >= 2 else []
    folders = library.user_folders(request.user)
    # что уже есть в коллекции — чтобы не добавлять дубли
    have = {}
    if results:
        mine = Entry.objects.filter(
            user=request.user,
            title__tmdb_id__in=[r['id'] for r in results],
            title__tmdb_type__in=[r['media_type'] for r in results],
        ).select_related('title')
        have = {(e.title.tmdb_id, e.title.tmdb_type): e.pk for e in mine}
    for r in results:
        r['local'] = bool(library.find(folders, r['title'], r['original']))
        r['entry_pk'] = have.get((r['id'], r['media_type']))
        r['added'] = bool(r['entry_pk'])
    return render(request, 'tracker/_tmdb_results.html',
                  {'results': results, 'q': q, 'offline': tmdb.offline()})


def _title_from_tmdb(request, media_type, tmdb_id):
    """Возвращает Title для фильма из TMDB: находит существующий или создаёт.

    Запись создаётся один раз на фильм (ищется по tmdb_id + tmdb_type),
    дальше переиспользуется всеми пользователями. Здесь НЕ создаётся
    запись в коллекции (Entry) — это делает отдельная кнопка «Добавить».
    """
    title = Title.objects.filter(tmdb_id=tmdb_id, tmdb_type=media_type).first()
    if title:
        return title

    d = tmdb.details(media_type, tmdb_id)
    if not d:
        return None

    date = d.get('release_date') or d.get('first_air_date') or ''
    genre_names = [g['name'] for g in d.get('genres', [])]
    is_doc = 'документальный' in [g.lower() for g in genre_names]

    if media_type == 'movie':
        director = next((c['name'] for c in d.get('credits', {}).get('crew', [])
                         if c.get('job') == 'Director'), '')
        duration = d.get('runtime') or 100
    else:
        director = ', '.join(c['name'] for c in d.get('created_by', [])[:2])
        runtimes = d.get('episode_run_time') or [45]
        duration = runtimes[0]

    title = Title.objects.create(
        name=d.get('title') or d.get('name') or '',
        director=director,
        type='doc' if is_doc else ('series' if media_type == 'tv' else 'movie'),
        year=int(date[:4]) if date[:4].isdigit() else None,
        poster_url=tmdb.IMG + d['poster_path'] if d.get('poster_path') else '',
        duration_min=duration,
        tmdb_id=tmdb_id,
        tmdb_type=media_type,
        imdb_id=d.get('imdb_id') or '',
        overview=d.get('overview') or '',
        tmdb_rating=round(float(d.get('vote_average') or 0), 1) or None,
        original_name=d.get('original_title') or d.get('original_name') or '',
        total_episodes=(d.get('number_of_episodes')
                        if media_type == 'tv' else None),
    )
    # сразу подбираем локальный файл и дозапрашиваем рейтинги сторонних сайтов
    folders = library.user_folders(request.user)
    title.local_file = library.find(folders, title.name, title.original_name)
    title.save()
    for g in genre_names:
        genre, _ = Genre.objects.get_or_create(name=g.capitalize())
        title.genres.add(genre)
    ratings.enrich(title)  # рейтинги IMDb / Rotten Tomatoes / Metacritic
    return title


def _back_url(request, default=None):
    """Локальный адрес для возврата после POST (защита от open redirect).

    default вычисляется внутри функции: reverse() на этапе импорта модуля
    ещё не может разрешить адреса (URLconf в этот момент не загружен).
    """
    url = request.POST.get('next') or ''
    if url.startswith('/') and not url.startswith('//'):
        return url
    return default or reverse('home')


@login_required
@require_POST
def tmdb_add(request, media_type, tmdb_id):
    """Добавить фильм из TMDB в коллекцию пользователя (POST).

    next — куда вернуться после добавления (страница фильма, главная).
    """
    if media_type not in ('movie', 'tv'):
        return redirect('home')

    back = _back_url(request)
    title = _title_from_tmdb(request, media_type, tmdb_id)
    if not title:
        messages.error(request, 'Не удалось получить информацию о фильме '
                                'из TMDB. Попробуйте ещё раз позже.')
        return redirect(back)

    _, created = Entry.objects.get_or_create(user=request.user, title=title)
    if created:
        messages.success(request, f'«{title.name}» добавлен в коллекцию.')
    else:
        messages.info(request, f'«{title.name}» уже есть в вашей коллекции.')
    return redirect(back)


# --- отдельная страница фильма (вне коллекции) --------------------------------

@login_required
def film_detail(request, media_type, tmdb_id):
    """Базовая страница фильма/сериала из TMDB: только описание и рейтинги.

    Сознательно не связана с записью в коллекции: ни плеера, ни вкладок,
    ни редактирования — только информация и кнопка «Добавить в коллекцию».
    """
    if media_type not in ('movie', 'tv'):
        raise Http404

    title = _title_from_tmdb(request, media_type, tmdb_id)
    if not title:
        messages.warning(request, 'Не удалось загрузить информацию о фильме. '
                                  'Проверьте подключение к интернету и '
                                  'обновите страницу.')
        return redirect('home')

    ratings.enrich(title)  # если рейтинги ещё не получены — достроим
    details = tmdb.details(media_type, tmdb_id) or {}
    cast = [c.get('name') for c in details.get('credits', {}).get('cast', [])[:8]]
    # IMDb-id: сначала из своей записи, иначе из свежего ответа TMDB
    imdb_id = title.imdb_id or (details.get('external_ids') or {}).get('imdb_id', '')

    # есть ли уже фильм в коллекции — чтобы показать правильную кнопку
    entry = Entry.objects.filter(user=request.user, title=title).first()

    return render(request, 'tracker/film_detail.html', {
        'title': title,
        'details': details,
        'cast': cast,
        'imdb_id': imdb_id,
        'entry': entry,
        'media_type': media_type,
        'tmdb_id': tmdb_id,
        'rating_cards': ratings.rating_cards(title),
        'MEDIA': tmdb.IMG,
    })


@login_required
def film_by_imdb(request, imdb_id):
    """Страница фильма по IMDb-id (карточки «Популярное сейчас»).

    IMDb отдаёт только свой id, поэтому сначала находим фильм в TMDB;
    если не вышло — уводим в поиск на главной с этим названием.
    """
    found = tmdb.find_by_imdb(imdb_id)
    if found:
        return redirect('film_detail', found[0], found[1])
    q = request.GET.get('q', '').strip()
    return redirect(f"{reverse('home')}?q={quote(q)}" if q else reverse('home'))


# --- правовые документы (публичные страницы, без входа) -----------------------

# слаг документа -> (заголовок, шаблон). Меняется в одном месте,
# ссылки в футере и в меню документов берутся отсюда же через urls.py
LEGAL_PAGES = {
    'agreement': ('Пользовательское соглашение', 'legal/agreement.html'),
    'privacy': ('Политика обработки персональных данных', 'legal/privacy.html'),
    'consent': ('Согласие на обработку персональных данных', 'legal/consent.html'),
    'disclaimer': ('Правила сайта и отказ от ответственности', 'legal/disclaimer.html'),
    'contacts': ('Контакты и сведения об операторе', 'legal/contacts.html'),
}


def legal_index(request):
    """Хаб со списком всех правовых документов сайта."""
    return render(request, 'legal/index.html', {
        'pages': [{'slug': slug, 'title': title}
                  for slug, (title, _) in LEGAL_PAGES.items()],
    })


def legal_page(request, page):
    """Одна правовая страница (доступна без входа в систему)."""
    item = LEGAL_PAGES.get(page)
    if not item:
        raise Http404
    title, template = item
    return render(request, template, {'doc_title': title,
                                      'pages': [{'slug': slug, 'title': t}
                                                for slug, (t, _) in LEGAL_PAGES.items()]})


# --- просмотр ----------------------------------------------------------------

@login_required
def watch(request, pk):
    """Страница просмотра перенесена во вкладку «Видеоплеер» карточки фильма."""
    entry = get_object_or_404(Entry, pk=pk, user=request.user)
    return redirect(f"{reverse('entry_detail', args=[entry.pk])}?tab=player")


def _path_for_stream(request, title, ep_pk=None):
    """Файл, который можно отдать: у серии — свой, иначе общий у фильма.

    Пути берутся из БД, не из запроса, поэтому достаточно проверки
    существования файла и его расширения (library.resolve). Файлы вне
    подключённых папок тоже разрешены — их привязал сам владелец.
    """
    if ep_pk:
        ep = (Episode.objects.select_related('entry')
              .filter(pk=ep_pk, entry__user=request.user).first())
        if not ep:
            return None
        return (library.resolve(ep.local_file)
                or library.safe_path(library.user_folders(request.user),
                                     ep.local_file))
    return (library.resolve(title.local_file)
            or library.safe_path(library.user_folders(request.user),
                                 title.local_file))


@login_required
def stream(request, pk, ep_pk=None):
    """Отдача видеофайла в плеер с поддержкой заголовка Range (перемотка)."""
    entry = get_object_or_404(Entry, title__pk=pk, user=request.user)
    title = entry.title
    path = _path_for_stream(request, title, ep_pk)
    if not path:
        raise Http404
    size = path.stat().st_size
    start, end, status = 0, size - 1, 200
    m = re.match(r'bytes=(\d*)-(\d*)', request.headers.get('Range', ''))
    if m:
        if m.group(1):
            start = int(m.group(1))
        if m.group(2):
            end = min(int(m.group(2)), size - 1)
        status = 206
    length = end - start + 1

    def chunks():
        # чтение кусками по 1 МБ, чтобы браузер мог перематывать видео
        # без загрузки всего файла целиком
        with open(path, 'rb') as f:
            f.seek(start)
            left = length
            while left > 0:
                data = f.read(min(1024 * 1024, left))
                if not data:
                    break
                left -= len(data)
                yield data

    # mimetypes не знает про mkv/avi на всех платформах — указываем явно
    ctype = (mimetypes.guess_type(path.name)[0]
             or {'.mkv': 'video/x-matroska', '.avi': 'video/x-msvideo'}.get(path.suffix.lower())
             or 'video/mp4')
    resp = StreamingHttpResponse(chunks(), status=status, content_type=ctype)
    resp['Accept-Ranges'] = 'bytes'
    resp['Content-Length'] = str(length)
    if status == 206:
        resp['Content-Range'] = f'bytes {start}-{end}/{size}'
    return resp


# --- папки с фильмами --------------------------------------------------------

@login_required
def library_page(request):
    """Папки пользователя с фильмами: добавление/удаление папок (вкладка «Папки»).

    Добавление путей доступно только администраторам — иначе любой
    пользователь мог бы добавить системные папки (например, /etc).
    """
    error = ''
    if request.method == 'POST':
        if request.POST.get('action') == 'remove':
            LibraryFolder.objects.filter(user=request.user,
                                         pk=request.POST.get('id')).delete()
        elif request.user.is_staff:
            p = Path(request.POST.get('path', '').strip()).expanduser()
            if p.is_dir():
                LibraryFolder.objects.get_or_create(user=request.user, path=str(p.resolve()))
            else:
                error = 'Такой папки нет. Проверьте путь.'
        else:
            error = 'Добавлять папки могут только администраторы.'
        if not error:
            return redirect('library_page')
    folders = list(LibraryFolder.objects.filter(user=request.user))
    count = len(library.scan([f.path for f in folders], force=True))
    return render(request, 'tracker/library.html',
                  {'folders': folders, 'count': count, 'error': error})


@login_required
def browse(request):
    """Проводник браузера: список папок и видеофайлов для выбора фильма.

    Доступен только администраторам — иначе любой пользователь мог бы
    просматривать структуру папок сервера.
    """
    if not request.user.is_staff:
        raise Http404
    p = Path(request.GET.get('path') or Path.home()).expanduser()
    try:
        p = p.resolve()
    except OSError:
        p = Path.home()
    if not p.is_dir():
        p = Path.home()
    dirs = []
    try:
        dirs = sorted((d for d in p.iterdir()
                       if d.is_dir() and not d.name.startswith('.')),
                      key=lambda d: d.name.lower())
    except PermissionError:
        pass
    return render(request, 'tracker/browse.html', {
        'path': p, 'dirs': dirs,
        'parent': p.parent if p.parent != p else None})


# --- профиль и статистика ----------------------------------------------------

MONTHS_SHORT = ['янв', 'фев', 'мар', 'апр', 'май', 'июн',
                'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
TYPE_LABELS = {'movie': 'Фильмы', 'series': 'Сериалы', 'doc': 'Док-фильмы'}


def _last_months(n):
    """Последние n календарных месяцев в порядке возрастания: (год, месяц)."""
    today = timezone.localdate()
    out, y, m = [], today.year, today.month
    for _ in range(n):
        out.append((y, m))
        m, y = (12, y - 1) if m == 1 else (m - 1, y)
    return list(reversed(out))


def _last_weeks(n):
    """Последние n ISO-недель в порядке возрастания: (год, неделя)."""
    today = timezone.localdate()
    monday = today - timedelta(days=today.isoweekday() - 1)
    return [(monday - timedelta(days=7 * i)).isocalendar()[:2]
            for i in range(n - 1, -1, -1)]


def _watch_stats(user):
    """Время просмотра пользователя, разложенное по месяцам, жанрам и типам.

    Счётчик складывается из двух источников:
      1) длина каждого фильма, отмеченного «Просмотрено» — она просто
         прибавляется к общему времени (так учитываются фильмы, которые
         смотрелись на стриминге или в стороннем плеере);
      2) реальное воспроизведение в нашем плеере (сеансы) — но только по
         фильмам, которые ещё не отмечены просмотренными, иначе один и тот
         же фильм посчитался бы дважды.
    """
    sessions = (WatchSession.objects.filter(user=user)
                .select_related('title').prefetch_related('title__genres'))
    watched_entries = list(
        Entry.objects.filter(user=user, status='watched')
        .select_related('title').prefetch_related('title__genres', 'episodes'))
    watched_titles = {e.title_id for e in watched_entries}

    per_month, genre_hours, type_hours = {}, {}, {}
    total_sec = 0

    def add_time(sec, when, title, genres):
        """Прибавляет секунды к общему счётчику и во все разрезы статистики."""
        nonlocal total_sec
        total_sec += sec
        if when is not None:
            key = (when.year, when.month)
            per_month[key] = per_month.get(key, 0) + sec
        for g in genres:
            genre_hours[g] = genre_hours.get(g, 0) + sec
        type_hours[title.type] = type_hours.get(title.type, 0) + sec

    for s in sessions:
        if s.title_id in watched_titles:
            continue
        d = timezone.localtime(s.last_ping)
        add_time(s.seconds, d, s.title, [g.name for g in s.title.genres.all()])

    for e in watched_entries:
        mins = _watched_minutes(e)
        if not mins:
            continue
        when = e.watched_at or timezone.localtime(e.added_at)
        add_time(mins * 60, when, e.title, [g.name for g in e.title.genres.all()])

    return {'total_sec': total_sec, 'per_month': per_month,
            'genre_hours': genre_hours, 'type_hours': type_hours,
            'watched_entries': watched_entries}


def _genre_chart(user, genre_hours):
    """Данные графика «предпочтения по жанрам» (то же, что в профиле).

    Если времени ещё нет, показываем количество просмотренных фильмов — так
    график остаётся полезным с первого дня.
    """
    if not genre_hours:
        counts = {}
        for e in Entry.objects.filter(user=user, status='watched').select_related(
                'title').prefetch_related('title__genres'):
            for g in e.title.genres.all():
                counts[g.name] = counts.get(g.name, 0) + 1
        items = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:10]
        return {'labels': [k for k, _ in items],
                'values': [v for _, v in items], 'unit': 'шт'}

    items = sorted(genre_hours.items(), key=lambda kv: kv[1], reverse=True)[:10]
    return {'labels': [k for k, _ in items],
            'values': [round(v / 3600, 1) for _, v in items], 'unit': 'ч'}


@login_required
def profile(request):
    """Профиль: статистика просмотров (часы, графики) и список статусов."""
    user = request.user
    st = _watch_stats(user)
    total_sec, per_month = st['total_sec'], st['per_month']
    genre_hours, type_hours = st['genre_hours'], st['type_hours']

    # --- часы: по месяцам, по жанрам, по типам -----------------------------
    months = _last_months(8)
    hours_values = [round(per_month.get(k, 0) / 3600, 1) for k in months]
    hours_labels = [f'{MONTHS_SHORT[m - 1]} {str(y)[2:]}' for y, m in months]
    hours_now = hours_values[-1]
    hours_avg = round(sum(hours_values) / len(hours_values), 1)

    genres = _genre_chart(user, genre_hours)
    genre_unit = genres['unit']

    if not type_hours:  # запасной вариант — просто количество записей
        for e in Entry.objects.filter(user=user).select_related('title'):
            type_hours[e.title.type] = type_hours.get(e.title.type, 0) + 1
    type_items = sorted(type_hours.items(), key=lambda kv: kv[1], reverse=True)
    type_labels = [TYPE_LABELS.get(k, k) for k, _ in type_items]
    if total_sec:
        type_values, type_unit = [round(v / 3600, 1) for _, v in type_items], 'ч'
    else:
        type_values, type_unit = [v for _, v in type_items], 'шт'

    # --- серии по неделям ---------------------------------------------------
    weeks = _last_weeks(8)
    per_week = {k: 0 for k in weeks}
    episodes = Episode.objects.filter(entry__user=user,
                                      watched_at__isnull=False)
    for ep in episodes:
        key = ep.watched_at.isocalendar()[:2]
        if key in per_week:
            per_week[key] += 1
    week_monday = timezone.localdate() - timedelta(
        days=timezone.localdate().isoweekday() - 1)
    week_labels = [(week_monday - timedelta(days=7 * (len(weeks) - 1 - i)))
                   .strftime('%d.%m') for i in range(len(weeks))]
    week_values = [per_week[k] for k in weeks]
    episodes_now = week_values[-1]

    # --- недосмотренное -----------------------------------------------------
    unfinished = list(Entry.objects.filter(user=user, status='watching')
                      .select_related('title').order_by('-added_at'))
    for e in unfinished:
        e.ep_watched = e.episodes.count()
        e.ep_total = e.title.total_episodes
        e.progress = (min(100, round(e.ep_watched * 100 / e.ep_total))
                      if e.ep_total else None)

    ctx = {
        'stats': {
            'hours_now': hours_now, 'hours_avg': hours_avg,
            'episodes_now': episodes_now,
            'unfinished': len(unfinished),
            'total': Entry.objects.filter(user=user).count(),
            'watched': Entry.objects.filter(user=user, status='watched').count(),
            'hours_total': round(total_sec / 3600, 1),
        },
        'unfinished': unfinished,
        'hours': {'labels': hours_labels, 'values': hours_values},
        'genres': genres,
        'types': {'labels': type_labels, 'values': type_values,
                  'unit': type_unit},
        'weeks': {'labels': week_labels, 'values': week_values},
        'has_watch_time': total_sec > 0,
    }
    return render(request, 'tracker/profile.html', ctx)
