from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.http import JsonResponse
from django.utils import timezone
from datetime import date, timedelta
import re
import mimetypes
from pathlib import Path
from django.http import StreamingHttpResponse, Http404
from django.views.decorators.http import require_POST
from .forms import EntryForm
from .models import (Entry, Title, Genre, Tag, LibraryFolder, Episode,
                     WatchSession)
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


def register(request):
    form = UserCreationForm(request.POST or None)
    if form.is_valid():
        login(request, form.save())
        return redirect('entry_list')
    return render(request, 'registration/register.html', {'form': form})


@login_required
def entry_list(request):
    entries = (Entry.objects.filter(user=request.user)
               .select_related('title')
               .prefetch_related('title__genres', 'tags'))

    status = request.GET.get('status', '')
    if status in dict(Entry.STATUSES):
        entries = entries.filter(status=status)
    entries = list(entries)

    # предподсчёт: SQLite не умеет регистронезависимый поиск по кириллице,
    # поэтому остальные фильтры выполняются в Python
    for e in entries:
        scores = [v for v in (e.title.imdb_rating, e.title.tmdb_rating,
                              e.title.kp_rating) if v]
        e.site_score = max(scores) if scores else None

    q = request.GET.get('q', '').strip().lower()
    if q:
        entries = [e for e in entries if
                   q in e.title.name.lower()
                   or q in e.title.director.lower()
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

    ctx = {'entries': entries, 'q': q, 'status': status, 'sort': sort,
           'dur': dur, 'min_rating': request.GET.get('min_rating', ''),
           'min_score': request.GET.get('min_score', ''), 'type': title_type,
           'genres_sel': genres_sel, 'tags_sel': tags_sel,
           'durations': DURATIONS, 'sorts': SORTS, 'statuses': Entry.STATUSES,
           'types': Title.TYPES, 'my_ratings': MY_RATINGS,
           'site_ratings': SITE_RATINGS,
           'all_genres': Genre.objects.all().order_by('name'),
           'all_tags': Tag.objects.filter(user=request.user).order_by('name'),
           'active_filters': len([1 for v in (q, status, dur, title_type,
                                              request.GET.get('min_rating'),
                                              request.GET.get('min_score'),
                                              genres_sel, tags_sel) if v])}

    if request.headers.get('HX-Request'):
        return render(request, 'tracker/_entry_cards.html', ctx)

    # строка «Популярное сейчас» — только на полной странице (с кэшем)
    ctx['popular'] = imdbapi.popular(18)
    return render(request, 'tracker/entry_list.html', ctx)


@login_required
def entry_create(request):
    form = EntryForm(request.POST or None, user=request.user)
    if form.is_valid():
        return redirect('entry_detail', pk=form.save().pk)
    return render(request, 'tracker/entry_form.html',
                  {'form': form, 'heading': 'Добавить'})


@login_required
def entry_update(request, pk):
    entry = get_object_or_404(Entry, pk=pk, user=request.user)
    form = EntryForm(request.POST or None, instance=entry, user=request.user)
    if form.is_valid():
        form.save()
        return redirect(f"{reverse('entry_detail', args=[entry.pk])}?tab=info")
    return render(request, 'tracker/entry_form.html',
                  {'form': form, 'heading': 'Изменить'})


@login_required
def entry_delete(request, pk):
    entry = get_object_or_404(Entry, pk=pk, user=request.user)
    if request.method == 'POST':
        entry.delete()
        return redirect('entry_list')
    return render(request, 'tracker/entry_confirm_delete.html', {'entry': entry})


# --- карточка фильма: вкладки «Информация», «Теги», «Видеоплеер» -------------

@login_required
def entry_detail(request, pk):
    entry = get_object_or_404(Entry, pk=pk, user=request.user)
    title = entry.title

    if request.method == 'POST':  # привязка видеофайла (вкладка «Видеоплеер»)
        path = request.POST.get('file', '')
        if library.safe_path(library.user_folders(request.user), path):
            title.local_file = path
            title.save(update_fields=['local_file'])
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
        if not library.safe_path(folders, title.local_file):
            title.local_file = library.find(folders, title.name, title.original_name)
            title.save(update_fields=['local_file'])
        ctx['has_folders'] = bool(folders)
        ctx['files'] = [] if title.local_file else library.scan(folders)

    if tab == 'episodes':
        watched = {(e.season, e.number): e.watched_at
                   for e in entry.episodes.all()}
        seasons, season_numbers = [], []
        if title.tmdb_id:
            d = tmdb.details('tv', title.tmdb_id)
            if d:
                seasons = [s for s in d.get('seasons', [])
                           if s.get('season_number')]
                season_numbers = [s['season_number'] for s in seasons]
                total = d.get('number_of_episodes')
                if total and title.total_episodes != total:
                    title.total_episodes = total
                    title.save(update_fields=['total_episodes'])

        requested = request.GET.get('season', '')
        if requested.isdigit() and (not season_numbers
                                    or int(requested) in season_numbers):
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
            episodes.append({**ep, 'watched_at': watched.get((current, ep['number']))})

        ctx.update({
            'seasons': seasons, 'season_numbers': season_numbers,
            'current_season': current, 'episodes': episodes,
            'watched_total': len(watched),
            'no_tmdb': not title.tmdb_id,
        })

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
                entry.save(update_fields=['status'])
        elif action == 'rating':
            try:
                value = int(request.POST.get('rating') or 0)
            except ValueError:
                value = 0
            entry.rating = value if 1 <= value <= 5 else None
            entry.save(update_fields=['rating'])
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
        _, created = Episode.objects.get_or_create(
            entry=entry, season=season, number=number,
            defaults={'watched_at': timezone.localdate()})
        if created and entry.status == 'planned':
            entry.status = 'watching'
            entry.save(update_fields=['status'])

    # все серии просмотрены — закрываем сериал
    if entry.title.total_episodes:
        watched_count = entry.episodes.count()
        if watched_count >= entry.title.total_episodes and entry.status != 'watched':
            entry.status = 'watched'
            entry.watched_at = timezone.localdate()
            entry.save(update_fields=['status', 'watched_at'])
    return redirect(back)


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
    return render(request, 'tracker/tmdb_search.html',
                  {'q': request.GET.get('q', '').strip()})


@login_required
def tmdb_results(request):
    q = request.GET.get('q', '').strip()
    results = tmdb.search(q) if len(q) >= 2 else []
    folders = library.user_folders(request.user)
    for r in results:
        r['local'] = bool(library.find(folders, r['title'], r['original']))
    return render(request, 'tracker/_tmdb_results.html', {'results': results, 'q': q})


@login_required
@require_POST
def tmdb_add(request, media_type, tmdb_id):
    if media_type not in ('movie', 'tv'):
        return redirect('tmdb_page')

    title = Title.objects.filter(tmdb_id=tmdb_id, tmdb_type=media_type).first()
    if not title:
        d = tmdb.details(media_type, tmdb_id)
        if not d:
            return redirect('tmdb_page')

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
        folders = library.user_folders(request.user)
        title.local_file = library.find(folders, title.name, title.original_name)
        title.save()
        for g in genre_names:
            genre, _ = Genre.objects.get_or_create(name=g.capitalize())
            title.genres.add(genre)
        ratings.enrich(title)  # рейтинги IMDb / Rotten Tomatoes / Metacritic

    entry, _ = Entry.objects.get_or_create(user=request.user, title=title)
    return redirect(f"{reverse('entry_detail', args=[entry.pk])}?tab=info")


# --- просмотр ----------------------------------------------------------------

@login_required
def watch(request, pk):
    """Страница просмотра перенесена во вкладку «Видеоплеер» карточки фильма."""
    title = get_object_or_404(Title, pk=pk)
    entry, _ = Entry.objects.get_or_create(user=request.user, title=title)
    return redirect(f"{reverse('entry_detail', args=[entry.pk])}?tab=player")


@login_required
def stream(request, pk):
    title = get_object_or_404(Title, pk=pk)
    path = library.safe_path(library.user_folders(request.user), title.local_file)
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
        with open(path, 'rb') as f:
            f.seek(start)
            left = length
            while left > 0:
                data = f.read(min(1024 * 1024, left))
                if not data:
                    break
                left -= len(data)
                yield data

    resp = StreamingHttpResponse(chunks(), status=status,
                                 content_type=mimetypes.guess_type(path.name)[0] or 'video/mp4')
    resp['Accept-Ranges'] = 'bytes'
    resp['Content-Length'] = str(length)
    if status == 206:
        resp['Content-Range'] = f'bytes {start}-{end}/{size}'
    return resp


# --- папки с фильмами --------------------------------------------------------

@login_required
def library_page(request):
    error = ''
    if request.method == 'POST':
        if request.POST.get('action') == 'remove':
            LibraryFolder.objects.filter(user=request.user,
                                         pk=request.POST.get('id')).delete()
        else:
            p = Path(request.POST.get('path', '').strip()).expanduser()
            if p.is_dir():
                LibraryFolder.objects.get_or_create(user=request.user, path=str(p.resolve()))
            else:
                error = 'Такой папки нет. Проверьте путь.'
        if not error:
            return redirect('library_page')
    folders = list(LibraryFolder.objects.filter(user=request.user))
    count = len(library.scan([f.path for f in folders], force=True))
    return render(request, 'tracker/library.html',
                  {'folders': folders, 'count': count, 'error': error})


@login_required
def browse(request):
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


@login_required
def profile(request):
    user = request.user
    sessions = (WatchSession.objects.filter(user=user)
                .select_related('title').prefetch_related('title__genres'))

    # --- часы: по месяцам, по жанрам, по типам -----------------------------
    per_month, genre_hours, type_hours = {}, {}, {}
    total_sec = 0
    for s in sessions:
        total_sec += s.seconds
        d = timezone.localtime(s.last_ping)
        per_month[(d.year, d.month)] = per_month.get((d.year, d.month), 0) + s.seconds
        for g in s.title.genres.all():
            genre_hours[g.name] = genre_hours.get(g.name, 0) + s.seconds
        type_hours[s.title.type] = type_hours.get(s.title.type, 0) + s.seconds

    months = _last_months(8)
    hours_values = [round(per_month.get(k, 0) / 3600, 1) for k in months]
    hours_labels = [f'{MONTHS_SHORT[m - 1]} {str(y)[2:]}' for y, m in months]
    hours_now = hours_values[-1]
    hours_avg = round(sum(hours_values) / len(hours_values), 1)

    # если плеером ещё не пользовались — показываем предпочтения по оценённому
    genre_unit = 'ч'
    if not genre_hours:
        genre_unit = 'шт'
        for e in Entry.objects.filter(user=user, status='watched').select_related(
                'title').prefetch_related('title__genres'):
            for g in e.title.genres.all():
                genre_hours[g.name] = genre_hours.get(g.name, 0) + 1
    genre_items = sorted(genre_hours.items(), key=lambda kv: kv[1], reverse=True)[:10]
    genre_labels = [k for k, _ in genre_items]
    genre_values = [round(v / 3600, 1) if genre_unit == 'ч' else v
                    for _, v in genre_items]

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
        'genres': {'labels': genre_labels, 'values': genre_values,
                   'unit': genre_unit},
        'types': {'labels': type_labels, 'values': type_values,
                  'unit': type_unit},
        'weeks': {'labels': week_labels, 'values': week_values},
        'has_sessions': total_sec > 0,
    }
    return render(request, 'tracker/profile.html', ctx)
