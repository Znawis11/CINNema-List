"""Фильтры шаблонов приложения tracker."""
from django import template

register = template.Library()

# Типовые размеры кадров TMDB: w92, w154, w185, w342, w500, original
_POSTER_SIZES = ('w92', 'w154', 'w185', 'w342', 'w500', 'original')


@register.filter
def poster(url, size='w500'):
    """Постер нужного размера: не грузим w500 там, где хватает мелкого.

    В базе хранится ссылка вида https://image.tmdb.org/t/p/w500/<path>.
    Размер подменяется на лету, поэтому старые записи тоже работают.
    Ссылки других источников (например, IMDb) не трогаем.
    """
    if not url or size not in _POSTER_SIZES or '/t/p/' not in url:
        return url
    head, tail = url.split('/t/p/', 1)
    tail = tail.split('/', 1)[1] if '/' in tail else ''
    return f'{head}/t/p/{size}/{tail}'