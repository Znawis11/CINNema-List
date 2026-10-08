"""Работа с видеофайлами: поиск, сканирование папок, безопасные пути."""
import os
import re
import time
from pathlib import Path

EXT = {'.mp4', '.webm', '.m4v', '.mov', '.mkv', '.avi'}
# форматы, которые предлагает проводник файлов
PICK_EXT = {'.mp4', '.mkv', '.avi'}
TTL = 120  # секунд хранить результат сканирования
_cache = {}


def norm(s):
    """Нормализация названия для сравнения: без знаков и в нижнем регистре."""
    return re.sub(r'[\W_]+', '', (s or '').lower())


def user_folders(user):
    """Список папок пользователя, в которых ищутся фильмы."""
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


def resolve(path):
    """Путь, выбранный в проводнике: файл существует и расширение видео.

    Путь хранится в БД (Title.local_file / Episode.local_file) и в запрос
    не подставляется, поэтому дополнительно проверять «внутри папок» не нужно.
    """
    if not path:
        return None
    try:
        p = Path(path).expanduser().resolve()
        if p.is_file() and p.suffix.lower() in EXT:
            return p
    except OSError:
        pass
    return None


# --- поиск файла по имени (когда путь из браузера недоступен) ---------------

SKIP_DIRS = {'Library', 'Applications', 'node_modules', '.git', '.cache',
             '__pycache__', 'System', 'private'}
LOCATE_MAX_MATCHES = 5     # собрать не больше и остановиться
LOCATE_MAX_ENTRIES = 150000  # предохранитель по объёму обхода
LOCATE_SECONDS = 8         # и по времени


def locate(filename, size=None, roots=(), limit=LOCATE_MAX_MATCHES):
    """Быстрый обход диска в поисках файла с точным именем (и размером).

    Браузер не может отдать серверу путь выбранного файла — сервер ищет его
    сам: идёт только по списку корней (папки пользователя, домашняя папка,
    внешние диски), пропуская служебные каталоги, и останавливается после
    limit совпадений или бюджета по времени/количеству записей.
    """
    matches, seen = [], 0
    deadline = time.time() + LOCATE_SECONDS
    # корни обходим строго по очереди: папки пользователя, потом домашняя
    # папка и внешние диски — как только файл найден в корне, остальные
    # не смотрим (и не тратим лимит на обход всего диска)
    for root in (Path(r) for r in roots if r):
        stack = [root]
        while (stack and len(matches) < limit
               and seen < LOCATE_MAX_ENTRIES and time.time() < deadline):
            d = stack.pop()
            try:
                with os.scandir(d) as it:
                    for e in it:
                        if e.name.startswith('.'):
                            continue
                        seen += 1
                        try:
                            if e.is_dir(follow_symlinks=False):
                                if e.name not in SKIP_DIRS:
                                    stack.append(Path(e.path))
                            elif (e.is_file() and e.name == filename
                                  and (size is None or e.stat().st_size == size)):
                                matches.append(e.path)
                                if len(matches) >= limit:
                                    break
                        except OSError:
                            continue
            except OSError:
                continue
        if matches:
            break
    return matches
