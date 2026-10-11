"""Guarda contra comentário de template vazando para a tela.

``{# ... #}`` do Django só vale numa linha: com o ``#}`` em outra linha, o
texto todo é renderizado. Comentário de várias linhas é ``{% comment %}``.
"""

from datetime import date
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse

from apps.ausencias import ausencias_service
from apps.ausencias.models import TipoAusencia
from apps.colaboradores.models import Colaborador


def _templates_do_projeto():
    pastas = [Path(pasta) for config in settings.TEMPLATES for pasta in config['DIRS']]
    pastas += list((Path(settings.BASE_DIR) / 'apps').glob('*/templates'))
    return sorted(arquivo for pasta in pastas for arquivo in pasta.rglob('*.html'))


def test_ha_templates_para_verificar():
    nomes = {arquivo.name for arquivo in _templates_do_projeto()}
    assert {'base.html', 'ausencia_form.html', 'painel.html'} <= nomes


def test_nenhum_comentario_curto_ocupa_mais_de_uma_linha():
    problemas = []
    for arquivo in _templates_do_projeto():
        for numero, texto in enumerate(arquivo.read_text(encoding='utf-8').splitlines(), start=1):
            # Cada "{#" precisa fechar com "#}" na mesma linha.
            resto = texto
            while '{#' in resto:
                resto = resto[resto.index('{#') + 2:]
                if '#}' not in resto:
                    problemas.append(f'{arquivo.relative_to(settings.BASE_DIR)}:{numero}')
                    break
                resto = resto[resto.index('#}') + 2:]
    assert not problemas, 'Use {% comment %} para comentário de várias linhas: ' + ', '.join(problemas)


@pytest.fixture
def ausencia(db, admin):
    colaborador = Colaborador.objects.create(nome='Ana Souza')
    return ausencias_service.criar_ausencia(
        colaborador, TipoAusencia.objects.get(nome='Férias'),
        [ausencias_service.PeriodoInformado(date(2026, 3, 2), date(2026, 3, 6))], 'obs', admin,
    )


@pytest.mark.django_db
def test_paginas_principais_nao_mostram_marcas_de_comentario(client, admin, ausencia):
    client.force_login(admin)
    urls = [
        reverse('painel:painel'),
        reverse('ausencias:lista'),
        reverse('ausencias:registrar'),
        reverse('ausencias:detalhe', args=[ausencia.pk]),
        reverse('ausencias:editar', args=[ausencia.pk]),
        reverse('ausencias:excluir', args=[ausencia.pk]),
        reverse('ausencias:lixeira'),
        reverse('ausencias:importar'),
        reverse('colaboradores:colaboradores'),
        reverse('colaboradores:departamentos'),
        reverse('usuarios:pendentes'),
        reverse('usuarios:convites'),
        reverse('usuarios:password_change'),
    ]
    for url in urls:
        resposta = client.get(url)
        assert resposta.status_code == 200, url
        html = resposta.content.decode()
        assert '{#' not in html and '#}' not in html, url


@pytest.mark.django_db
def test_paginas_publicas_nao_mostram_marcas_de_comentario(client):
    for url in [reverse('usuarios:login'), reverse('usuarios:cadastro'), reverse('usuarios:password_reset')]:
        resposta = client.get(url)
        assert resposta.status_code == 200, url
        html = resposta.content.decode()
        assert '{#' not in html and '#}' not in html, url
