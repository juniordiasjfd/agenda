"""``{% static_versionado %}``: URL de estático que o navegador não reaproveita
depois de o arquivo mudar.

Em produção o storage com manifesto (WhiteNoise) já põe o hash no nome do
arquivo: devolve a URL do ``{% static %}`` sem mexer. Em desenvolvimento o
runserver serve o arquivo sem hash e o navegador pode usar a cópia antiga por
horas (cache heurístico pelo Last-Modified): acrescenta ``?v=<mtime>``.
"""

import os

from django import template
from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import ManifestFilesMixin, staticfiles_storage
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def static_versionado(caminho):
    url = static(caminho)
    if isinstance(staticfiles_storage, ManifestFilesMixin):
        return url
    arquivo = finders.find(caminho)
    if not arquivo:
        return url
    return f'{url}?v={int(os.path.getmtime(arquivo))}'
