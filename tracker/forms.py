from django import forms
from .models import Entry, Title, Tag, Genre


class EntryForm(forms.ModelForm):
    name = forms.CharField(label='Название', max_length=255)
    director = forms.CharField(label='Режиссёр', required=False)
    type = forms.ChoiceField(label='Тип', choices=Title.TYPES)
    year = forms.IntegerField(label='Год', required=False)
    genres = forms.ModelMultipleChoiceField(
        label='Жанры', queryset=Genre.objects.all(), required=False,
        widget=forms.CheckboxSelectMultiple)
    poster_url = forms.URLField(label='Ссылка на постер', required=False)
    new_tags = forms.CharField(label='Новые теги (через запятую)', required=False)

    class Meta:
        model = Entry
        fields = ['status', 'rating', 'review', 'tags', 'watched_at']
        labels = {'status': 'Статус', 'rating': 'Оценка (1-5)',
                  'review': 'Рецензия', 'tags': 'Теги',
                  'watched_at': 'Дата просмотра'}
        widgets = {
            'watched_at': forms.DateInput(attrs={'type': 'date'}),
            'tags': forms.CheckboxSelectMultiple,
            'review': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields['tags'].queryset = Tag.objects.filter(user=user)
        if self.instance.pk:
            t = self.instance.title
            self.fields['name'].initial = t.name
            self.fields['director'].initial = t.director
            self.fields['type'].initial = t.type
            self.fields['year'].initial = t.year
            self.fields['poster_url'].initial = t.poster_url
            self.fields['genres'].initial = t.genres.all()
        for f in self.fields.values():
            if not isinstance(f.widget, forms.CheckboxSelectMultiple):
                f.widget.attrs.setdefault('class', 'form-control')

    def clean_rating(self):
        r = self.cleaned_data.get('rating')
        if r is not None and not 1 <= r <= 5:
            raise forms.ValidationError('Оценка от 1 до 5')
        return r

    def save(self, commit=True):
        entry = super().save(commit=False)
        title = entry.title if entry.pk else Title()
        d = self.cleaned_data
        title.name = d['name']
        title.director = d['director']
        title.type = d['type']
        title.year = d['year']
        title.poster_url = d['poster_url']
        title.save()
        title.genres.set(d['genres'])

        entry.title = title
        entry.user = self.user
        entry.save()
        self.save_m2m()

        for tag_name in d['new_tags'].split(','):
            tag_name = tag_name.strip()
            if tag_name:
                tag, _ = Tag.objects.get_or_create(user=self.user, name=tag_name)
                entry.tags.add(tag)
        return entry