import os
import re
import time
from pathlib import Path

EXT = {'.mp4', '.webm', '.m4v', '.mov', '.mkv', '.avi'}
TTL = 120  # секунд хранить результат сканирования
_cache = {}


def norm(s):
    return re.sub(r'[\W_]+', '', (s or '').lower())


def user_folders(user):
    from .models import LibraryFolder
    return list(LibraryFolder.objects.filter(user=user).values_list('path', flat=True))


def scan(folders, force=False):
    """Список полных путей ко всем видеофайлам в папках (с кэшем)."""
    key = tuple(sorted(folders))
    hit = _cache.get(key)
    if hit and not force and time.time() - hit[0] < TTL:
        return hit[1]
    result = []
    for folder in key:
        if not os.path.isdir(folder):
            continue
        for dirpath, dirnames, filenames in os.walk(folder):
            dirnames[:] = [d for d in dirnames if not d.startswith('.')]
            for f in filenames:
                if Path(f).suffix.lower() in EXT and not f.startswith('.'):
                    result.append(os.path.join(dirpath, f))
    _cache[key] = (time.time(), result)
    return result


def find(folders, *names):
    """Полный путь к файлу, в имени которого есть одно из названий."""
    items = [(norm(Path(p).stem), p) for p in scan(folders)]
    for n in names:
        n = norm(n)
        if len(n) < 3:
            continue
        for stem, path in items:
            if n in stem:
                return path
    return ''


def safe_path(folders, path):
    """Файл можно отдавать, только если он лежит внутри папок пользователя."""
    if not path:
        return None
    try:
        p = Path(path).resolve()
        if not p.is_file():
            return None
        for f in folders:
            if Path(f).resolve() in p.parents:
                return p
    except OSError:
        pass
    return None
