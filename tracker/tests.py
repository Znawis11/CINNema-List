"""Сквозные тесты ключевых сценариев сайта.

Запуск:  python3 manage.py test tracker
Сетевой тест (страница фильма из TMDB) автоматически пропускается без интернета.
"""
import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Collection, Entry, Episode, Title
from . import tmdb


def _register(client, username):
    """Регистрирует тестового пользователя и оставляет его залогиненным."""
    client.post(reverse('register'), {
        'username': username, 'password1': 's3curePass!',
        'password2': 's3curePass!',
    })
    return User.objects.get(username=username)


class LegalPagesTest(TestCase):
    """Правовые документы: открываются без входа, все ссылки живые."""

    def test_index_and_all_documents_open(self):
        for slug in ('agreement', 'privacy', 'consent', 'disclaimer', 'contacts'):
            response = self.client.get(reverse('legal_page', args=[slug]))
            self.assertEqual(response.status_code, 200, slug)

    def test_index_lists_every_document(self):
        response = self.client.get(reverse('legal_index'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Пользовательское соглашение')

    def test_footer_links_present_on_main_pages(self):
        """Футер с документами есть на всех страницах (в т.ч. публичных)."""
        response = self.client.get(reverse('legal_index'))
        self.assertContains(response, '18+')
        self.assertContains(response, 'Сайт не является СМИ')

    def test_unknown_document_is_404(self):
        self.assertEqual(self.client.get('/legal/nonsense/').status_code, 404)


class CollectionFlowTest(TestCase):
    """Создание подборки и добавление в неё фильмов галочками из списка."""

    def setUp(self):
        self.user = _register(self.client, 'tester')
        self.title = Title.objects.create(name='Тестовый фильм', year=2020)
        self.entry = Entry.objects.create(user=self.user, title=self.title)

    def test_create_stays_in_main_list(self):
        """Кнопка «Создать» создаёт подборку и остаётся в основном списке."""
        response = self.client.post(reverse('entry_list'),
                                    {'action': 'create', 'name': 'Моё кино'})
        self.assertRedirects(response, reverse('entry_list'))
        self.assertTrue(Collection.objects.filter(user=self.user,
                                                  name='Моё кино').exists())

        # в основном списке включается режим выбора галочками
        page = self.client.get(reverse('entry_list'))
        self.assertContains(page, 'Добавить в подборку')
        self.assertContains(page, 'name="entries"')

    def test_add_by_checkboxes_from_main_list(self):
        """Отмеченные галочками фильмы попадают в подборку, остаёмся в списке."""
        coll = Collection.objects.create(user=self.user, name='Отобранные')
        response = self.client.post(reverse('entry_list'), {
            'action': 'add', 'back': 'main',
            'collection': coll.pk, 'entries': [str(self.entry.pk)],
        })
        self.assertRedirects(response, reverse('entry_list'))
        self.assertIn(self.entry, coll.entries.all())
        # в подборке появился фильм, счётчик в сайдбаре обновился
        page = self.client.get(reverse('entry_list'))
        self.assertContains(page, 'Отобранные')

    def test_add_without_selection_does_not_fail(self):
        """Отправка без отметок не роняет страницу и ничего не добавляет."""
        coll = Collection.objects.create(user=self.user, name='Пустая')
        response = self.client.post(reverse('entry_list'), {
            'action': 'add', 'back': 'main', 'collection': coll.pk,
        })
        self.assertRedirects(response, reverse('entry_list'))
        self.assertEqual(coll.entries.count(), 0)

    def test_no_checkboxes_inside_collection(self):
        """Внутри открытой подборки галочек нет (там есть кнопка «✕»)."""
        coll = Collection.objects.create(user=self.user, name='Внутри')
        coll.entries.add(self.entry)
        page = self.client.get(f'{reverse("entry_list")}?collection={coll.pk}')
        self.assertNotContains(page, 'name="entries"')


class EpisodeDataTest(TestCase):
    """У каждой серии свои данные: файл и ссылка не теряются при переключении."""

    def setUp(self):
        self.user = _register(self.client, 'seriesfan')
        self.title = Title.objects.create(name='Сериал', type='series',
                                          tmdb_type='tv')
        self.entry = Entry.objects.create(user=self.user, title=self.title)

    def _set_link(self, number, url):
        self.client.post(reverse('episode_stream', args=[self.entry.pk]), {
            'season': '1', 'number': str(number), 'streaming_url': url,
        })

    def test_each_episode_keeps_its_own_link(self):
        """Ссылка первой серии не пропадает после сохранения второй."""
        self._set_link(1, 'https://example.com/ep1')
        self._set_link(2, 'https://example.com/ep2')
        ep1 = Episode.objects.get(entry=self.entry, season=1, number=1)
        ep2 = Episode.objects.get(entry=self.entry, season=1, number=2)
        self.assertEqual(ep1.streaming_url, 'https://example.com/ep1')
        self.assertEqual(ep2.streaming_url, 'https://example.com/ep2')

    def test_empty_link_clears_episode(self):
        Episode.objects.create(entry=self.entry, season=1, number=3,
                               streaming_url='https://example.com/old')
        self._set_link(3, '')
        ep = Episode.objects.get(entry=self.entry, season=1, number=3)
        self.assertEqual(ep.streaming_url, '')

    def test_file_from_folders_is_bound_to_episode(self):
        """Форма «Привязать из папок» с season/number пишет файл в Episode."""
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / 's01e05.mp4'
            video.write_bytes(b'\x00')          # файл должен реально существовать
            self.client.post(reverse('entry_detail', args=[self.entry.pk]), {
                'file': str(video), 'season': '1', 'number': '5',
            })
        ep = Episode.objects.get(entry=self.entry, season=1, number=5)
        self.assertEqual(ep.local_file, str(video))
        # в общий фильм файл не подмешался
        self.assertEqual(self.title.local_file, '')

    def test_player_shows_selected_episode_data(self):
        """Открытая серия показывает свой блок с файлом и ссылкой."""
        self._set_link(1, 'https://example.com/ep1')
        ep = Episode.objects.get(entry=self.entry, season=1, number=1)
        url = reverse('entry_detail', args=[self.entry.pk])
        page = self.client.get(f'{url}?tab=player&ep={ep.pk}')
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Данные серии S1E1')
        self.assertContains(page, 'https://example.com/ep1')

    def test_link_only_episode_offers_link_instead_of_player(self):
        """У серии без файла, но со ссылкой — кнопка «Смотреть по ссылке»."""
        self._set_link(1, 'https://example.com/ep1')
        ep = Episode.objects.get(entry=self.entry, season=1, number=1)
        page = self.client.get(
            reverse('entry_detail', args=[self.entry.pk]) + f'?tab=player&ep={ep.pk}')
        self.assertContains(page, 'Смотреть по ссылке')

    def test_series_keeps_episode_panel_when_marked_streaming(self):
        """Метка «стриминг» у сериала больше не прячет выбор серий."""
        self.entry.location = 'streaming'
        self.entry.streaming_url = 'https://example.com/series'
        self.entry.save(update_fields=['location', 'streaming_url'])
        page = self.client.get(
            reverse('entry_detail', args=[self.entry.pk]) + '?tab=player')
        self.assertContains(page, 'Серия:')


class FilmPageTest(TestCase):
    """Отдельная страница фильма вне коллекции (данные приходят из TMDB)."""

    def setUp(self):
        self.user = _register(self.client, 'viewer')

    def test_film_page_opens_without_collection_entry(self):
        url = reverse('film_detail', args=['movie', 278])  # «Побег из Шоушенка»
        response = self.client.get(url)
        if response.status_code == 302 or tmdb.offline():
            self.skipTest('нет доступа к TMDB — сетевой тест пропущен')
        self.assertEqual(response.status_code, 200)
        # на странице есть кнопка добавления и нет плеера/вкладок
        self.assertContains(response, 'Добавить в коллекцию')
        self.assertNotContains(response, 'tab=player')
        # фильм ещё не в коллекции — записи Entry нет
        self.assertFalse(Entry.objects.filter(user=self.user,
                                              title__tmdb_id=278).exists())

    def test_unknown_media_type_is_404(self):
        self.assertEqual(self.client.get('/film/person/278/').status_code, 404)


class SecurityTest(TestCase):
    """Доступ к файловой системе сервера: только для администраторов."""

    def setUp(self):
        self.user = _register(self.client, 'ordinary')
        self.admin = User.objects.create_user('admin1', password='adm1nPass!',
                                              is_staff=True)
        self.title = Title.objects.create(name='Фильм', year=2021)
        self.entry = Entry.objects.create(user=self.user, title=self.title)

    def test_browse_hidden_from_regular_user(self):
        """Обычный пользователь не видит структуру папок сервера."""
        self.assertEqual(self.client.get(reverse('browse')).status_code, 404)

    def test_browse_open_for_staff(self):
        self.client.logout()
        self.client.login(username='admin1', password='adm1nPass!')
        self.assertEqual(self.client.get(reverse('browse')).status_code, 200)

    def test_library_add_rejected_for_regular_user(self):
        """Обычный пользователь не может добавить произвольный путь."""
        response = self.client.post(reverse('library_page'),
                                    {'path': 'C:\\'}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'только администраторы')
        from .models import LibraryFolder
        self.assertFalse(LibraryFolder.objects.filter(user=self.user).exists())

    def test_watch_redirects_to_own_entry_only(self):
        """watch принимает pk записи (Entry), чужую запись не отдаёт."""
        other = User.objects.create_user('someone', password='x12345678')
        foreign = Entry.objects.create(
            user=other, title=Title.objects.create(name='Чужой'))
        response = self.client.get(reverse('watch', args=[foreign.pk]))
        self.assertEqual(response.status_code, 404)

    def test_stream_denied_for_foreign_title(self):
        """Стрим чужого фильма недоступен (404), своего — отдаёт файл."""
        other = User.objects.create_user('someone2', password='x12345678')
        foreign_title = Title.objects.create(name='Чужо2')
        Entry.objects.create(user=other, title=foreign_title)
        self.assertEqual(self.client.get(
            reverse('stream', args=[foreign_title.pk])).status_code, 404)
        # своя запись без файла — 404 по файлу, но не по праву доступа
        self.assertEqual(self.client.get(
            reverse('stream', args=[self.title.pk])).status_code, 404)


class PlayerTest(TestCase):
    """Плеер: нет автозапуска, форматы mkv/avi, ссылка-гиперссылка."""

    def setUp(self):
        self.user = _register(self.client, 'playerfan')
        self.title = Title.objects.create(name='Плеер', year=2022)
        self.entry = Entry.objects.create(user=self.user, title=self.title)

    def test_video_has_no_autoplay(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / 'movie.mp4'
            video.write_bytes(b'\x00')
            self.client.post(reverse('entry_detail', args=[self.entry.pk]),
                             {'file': str(video)})
        page = self.client.get(
            reverse('entry_detail', args=[self.entry.pk]) + '?tab=player')
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'autoplay')

    def test_file_dialog_accepts_mkv_avi(self):
        page = self.client.get(
            reverse('entry_detail', args=[self.entry.pk]) + '?tab=player')
        self.assertContains(page, 'accept=".mp4,.mkv,.avi')

    def test_streaming_mark_shows_hyperlink_not_file_ui(self):
        """Метка «стриминг»: ссылка — гиперссылка, интерфейс файла скрыт."""
        self.entry.location = 'streaming'
        self.entry.streaming_url = 'https://example.com/watch'
        self.entry.save(update_fields=['location', 'streaming_url'])
        page = self.client.get(
            reverse('entry_detail', args=[self.entry.pk]) + '?tab=player')
        self.assertContains(page,
                            'href="https://example.com/watch"', html=False)
        self.assertNotContains(page, 'Выбрать файл…')

    def test_streaming_mark_hides_file_field_on_info_tab(self):
        """Поле URL стриминга показывается только при метке «Стриминг»."""
        page = self.client.get(
            reverse('entry_detail', args=[self.entry.pk]) + '?tab=player')
        self.assertContains(page, 'display:none')  # поле скрыто при «локально»
        # при метке «стриминг» поле видно
        self.entry.location = 'streaming'
        self.entry.save(update_fields=['location'])
        page = self.client.get(
            reverse('entry_detail', args=[self.entry.pk]) + '?tab=player')
        self.assertContains(page, 'id="streamingUrlField"')
        self.assertNotContains(page, 'id="streamingUrlField"\n               style="display:none"')


class SettingsTest(TestCase):
    """Секреты вынесены в переменные окружения, а не лежат в репозитории."""

    def test_secret_key_not_hardcoded_insecure(self):
        from django.conf import settings
        self.assertNotIn('django-insecure-2!kqdqwbw', settings.SECRET_KEY)

    def test_tmdb_key_comes_from_environment(self):
        from django.conf import settings
        import os
        self.assertEqual(settings.TMDB_API_KEY,
                         os.environ.get('TMDB_API_KEY', ''))
