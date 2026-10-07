from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.decorators import login_required
from .models import Entry
from .forms import EntryForm
from django.views.decorators.http import require_POST
from .models import Entry, Title, Genre
from . import imdb


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
def imdb_page(request):
    return render(request, 'tracker/imdb_search.html')


@login_required
def imdb_results(request):
    q = request.GET.get('q', '').strip()
    results = imdb.search(q) if len(q) >= 2 else []
    return render(request, 'tracker/_imdb_results.html', {'results': results, 'q': q})


@login_required
@require_POST
def imdb_add(request, imdb_id):
    d = imdb.details(imdb_id)
    if not d:
        return redirect('imdb_page')

    title = Title.objects.filter(imdb_id=imdb_id).first()
    if not title:
        year = d.get('Year', '')[:4]
        runtime = d.get('Runtime', '').split(' ')[0]
        genre_names = [g.strip() for g in d.get('Genre', '').split(',') if g.strip()]
        is_doc = 'Documentary' in genre_names
        title = Title.objects.create(
            name=d.get('Title', ''),
            director=d.get('Director', '') if d.get('Director') != 'N/A' else '',
            type='doc' if is_doc else ('series' if d.get('Type') == 'series' else 'movie'),
            year=int(year) if year.isdigit() else None,
            poster_url=d.get('Poster', '') if d.get('Poster') != 'N/A' else '',
            duration_min=int(runtime) if runtime.isdigit() else 100,
            imdb_id=imdb_id,
        )
        for g in genre_names:
            genre, _ = Genre.objects.get_or_create(name=imdb.GENRES_RU.get(g, g))
            title.genres.add(genre)

    entry, _ = Entry.objects.get_or_create(user=request.user, title=title)
    return redirect('entry_update', pk=entry.pk)