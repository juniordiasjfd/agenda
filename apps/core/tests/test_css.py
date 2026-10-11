"""Guardas do CSS do projeto sobre o Tabler e o Tom Select.

O dropdown do Tom Select já saiu transparente duas vezes: o tema usa
variáveis --bs-* que o Tabler não define, e o CSS dele, carregado depois do
agenda.css, vencia regras de mesma especificidade.
"""

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse

from apps.colaboradores.models import Colaborador

PASTA_CSS = Path(settings.BASE_DIR) / 'static' / 'css'
AGENDA_CSS = PASTA_CSS / 'agenda.css'


def _regras(css):
    """{seletor: corpo} de cada regra (sem @media; o agenda.css não aninha)."""
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    return {
        ' '.join(seletor.split()): corpo
        for seletor, corpo in re.findall(r'([^{}]+)\{([^{}]*)\}', css)
    }


def _regra_com(seletor_procurado, css):
    """Declarações de todas as regras cujo grupo de seletores inclui
    ``seletor_procurado``, concatenadas."""
    corpos = [
        corpo for seletor, corpo in _regras(css).items()
        if seletor_procurado in [s.strip() for s in seletor.split(',')]
    ]
    assert corpos, f'Nenhuma regra para {seletor_procurado!r}'
    return '\n'.join(corpos)


def test_dropdown_do_tom_select_tem_fundo_opaco_com_important():
    css = AGENDA_CSS.read_text(encoding='utf-8')
    for seletor in ('body .ts-dropdown', 'body .ts-dropdown .ts-dropdown-content'):
        corpo = _regra_com(seletor, css)
        assert re.search(r'background-color:\s*var\(--tblr-bg-surface,\s*#fff\)\s*!important', corpo), seletor


def test_dropdown_do_tom_select_tem_fundo_escuro_de_reserva():
    corpo = _regra_com('[data-bs-theme=dark] .ts-dropdown', AGENDA_CSS.read_text(encoding='utf-8'))
    assert re.search(r'background-color:\s*var\(--tblr-bg-surface,\s*#182433\)\s*!important', corpo)


def test_variaveis_bs_do_tema_mapeadas_para_o_tabler():
    corpo = _regra_com('.ts-dropdown', AGENDA_CSS.read_text(encoding='utf-8'))
    for variavel in ('--bs-body-bg', '--bs-body-color', '--bs-tertiary-bg', '--bs-border-color'):
        assert re.search(rf'{variavel}:[^;]*var\(--tblr-', corpo), variavel


def test_dropdown_acima_dos_cards_e_do_modal():
    corpo = _regra_com('.ts-wrapper .ts-dropdown', AGENDA_CSS.read_text(encoding='utf-8'))
    assert re.search(r'z-index:\s*1060', corpo)


@pytest.mark.parametrize('arquivo', sorted(PASTA_CSS.glob('*.css')), ids=lambda p: p.name)
def test_toda_variavel_do_tabler_tem_valor_de_reserva(arquivo):
    css = re.sub(r'/\*.*?\*/', '', arquivo.read_text(encoding='utf-8'), flags=re.S)
    sem_reserva = re.findall(r'var\(--tblr-[\w-]+\)', css)
    assert sem_reserva == []


# ---------------------------------------------------------------------------
# Ordem de carga no HTML renderizado
# ---------------------------------------------------------------------------
def _posicao(html, trecho):
    assert trecho in html, trecho
    return html.index(trecho)


@pytest.mark.django_db
def test_agenda_css_carrega_depois_do_tema_do_tom_select(client, gestor):
    Colaborador.objects.create(nome='Ana Souza')
    client.force_login(gestor)

    html = client.get(reverse('ausencias:registrar')).content.decode()

    assert _posicao(html, 'tabler.min.css') < _posicao(html, 'tom-select.bootstrap5.min.css') < _posicao(html, 'css/agenda.css')


@pytest.mark.django_db
def test_agenda_css_tem_versao_no_link_em_desenvolvimento(client, gestor):
    client.force_login(gestor)

    html = client.get(reverse('ausencias:registrar')).content.decode()

    assert re.search(r'css/agenda\.css\?v=\d+"', html)
    assert re.search(r'js/ausencia_form\.js\?v=\d+"', html)


@pytest.mark.django_db
def test_pagina_publica_tambem_carrega_o_agenda_css(client):
    html = client.get(reverse('usuarios:login')).content.decode()

    assert _posicao(html, 'tabler.min.css') < _posicao(html, 'css/agenda.css')
