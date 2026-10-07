from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.decorators import login_required
from .models import Entry
from .forms import EntryForm
from django.views.decorators.http import require_POST
from .models import Entry, Title, Genre
from . import tmdb


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
               .prefetch_related('title__genres', 'tags')
               .order_by('-added_at'))

    status = request.GET.get('status', '')
    if status:
        entries = entries.filter(status=status)

    entries = list(entries)

    # Поиск в Python: SQLite не умеет регистронезависимый поиск по кириллице
    q = request.GET.get('q', '').strip().lower()
    if q:
        entries = [e for e in entries if
                   q in e.title.name.lower()
                   or q in e.title.director.lower()
                   or any(q in g.name.lower() for g in e.title.genres.all())
                   or any(q in t.name.lower() for t in e.tags.all())]

    ctx = {'entries': entries, 'q': q, 'status': status}
    if request.headers.get('HX-Request'):
        return render(request, 'tracker/_entry_cards.html', ctx)
    return render(request, 'tracker/entry_list.html', ctx)


@login_required
def entry_create(request):
    form = EntryForm(request.POST or None, user=request.user)
    if form.is_valid():
        form.save()
        return redirect('entry_list')
    return render(request, 'tracker/entry_form.html',
                  {'form': form, 'heading': 'Добавить'})


@login_required
def entry_update(request, pk):
    entry = get_object_or_404(Entry, pk=pk, user=request.user)
    form = EntryForm(request.POST or None, instance=entry, user=request.user)
    if form.is_valid():
        form.save()
        return redirect('entry_list')
    return render(request, 'tracker/entry_form.html',
                  {'form': form, 'heading': 'Изменить'})


@login_required
def entry_delete(request, pk):
    entry = get_object_or_404(Entry, pk=pk, user=request.user)
    if request.method == 'POST':
        entry.delete()
        return redirect('entry_list')
    return render(request, 'tracker/entry_confirm_delete.html', {'entry': entry})

@login_required
def tmdb_page(request):
    return render(request, 'tracker/tmdb_search.html')


@login_required
def tmdb_results(request):
    q = request.GET.get('q', '').strip()
    results = tmdb.search(q) if len(q) >= 2 else []
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
        )
        for g in genre_names:
            genre, _ = Genre.objects.get_or_create(name=g.capitalize())
            title.genres.add(genre)

    entry, _ = Entry.objects.get_or_create(user=request.user, title=title)
    return redirect('entry_update', pk=entry.pk)