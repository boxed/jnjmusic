"""
URL configuration for jnjmusic project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.template import Template
from django.urls import path
from django.utils.html import format_html
from iommi import (
    Fragment,
    Page,
    Table,
)

from recognition.models import (
    Song,
    Dancer,
    YouTubeVideo,
)

dancer_videos = Table(
    auto__model=YouTubeVideo,
    rows=lambda table, **_: Dancer.objects.get(pk=table.get_request().resolver_match.kwargs['pk']).videos.all(),
    title=lambda table, **_: f'Videos featuring {Dancer.objects.get(pk=table.get_request().resolver_match.kwargs["pk"]).name}',
    columns__title__cell__url=lambda row, **_: row.url,
    columns__duration__cell__format=lambda value, **_: f'{value // 60}:{value % 60:02d}' if value else '',
    columns__dancers__include=False,
    auto__exclude=['audio_file_path', 'audio_file_hash', 'error', 'processed'],
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', Page(parts__index=Fragment(template=Template('''
        <a href="events/">Events</a><br>
        <a href="songs/">Songs</a><br>
        <a href="dancers/">Dancers</a><br>
    '''))).as_view()),
    # path('events/', Table(
    #     auto__model=Event,
    # ).as_view()),
    path('songs/', Table(
        auto__model=Song,
        auto__exclude=['external_ids', 'genres'],
    ).as_view()),
    path('songs/spotify_playlist/', Table(
        auto__model=Song,
        auto__include=['spotify_id'],
        header__template=None,
        columns__spotify_id__cell__format=lambda value, **_: format_html('https://open.spotify.com/track/{}', value),
    ).as_view()),
    path('dancers/', Table(
        auto__model=Dancer,
        title='Dancers',
        columns__name__cell__url=lambda row, **_: f'/dancers/{row.pk}/',
        columns__videos__cell__value=lambda row, **_: row.videos.count(),
        columns__videos__display_name='Video Count',
    ).as_view()),
    path('dancers/<int:pk>/', dancer_videos.as_view()),
]
