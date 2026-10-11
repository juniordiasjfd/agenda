"""Página do painel (``GET painel/``): filtros, página inicial e menu."""

import pytest
from django.urls import reverse

from apps.ausencias.painel_service import rotulo_departamentos
from apps.colaboradores.models import Departamento

pytestmark = pytest.mark.django_db

URL = reverse('painel:painel')


@pytest.fixture
def logado(client, usuario_ativo):
    client.force_login(usuario_ativo)
    return client


@pytest.fixture
def ti(db):
    return Departamento.objects.create(nome='TI')


@pytest.fixture
def rh(db):
    return Departamento.objects.create(nome='RH')


def html(client, **parametros):
    resposta = client.get(URL, parametros)
    assert resposta.status_code == 200
    return resposta.content.decode()


# ---------------------------------------------------------------------------
# Acesso e página inicial
# ---------------------------------------------------------------------------
def test_anonimo_vai_para_o_login(client):
    resposta = client.get(URL)

    assert resposta.status_code == 302
    assert resposta.url.startswith(reverse('usuarios:login'))


@pytest.mark.parametrize('perfil', ['usuario_ativo', 'gestor', 'admin'])
def test_qualquer_autenticado(client, request, perfil):
    client.force_login(request.getfixturevalue(perfil))

    assert client.get(URL).status_code == 200


def test_inicio_redireciona_para_o_painel(logado):
    resposta = logado.get(reverse('core:home'))

    assert resposta.status_code == 302
    assert resposta.url == URL


def test_login_leva_ao_painel(client, usuario_ativo, senha):
    resposta = client.post(reverse('usuarios:login'), {'username': usuario_ativo.email, 'password': senha})

    assert resposta.url == URL


def test_menu_marca_o_painel(logado):
    resposta = logado.get(URL)

    assert resposta.context['active_nav'] == 'painel'
    assert f'href="{URL}"' in resposta.content.decode()


def test_botao_registrar_so_para_gestor(client, usuario_ativo, gestor):
    client.force_login(usuario_ativo)
    assert reverse('ausencias:registrar') not in html(client)

    client.force_login(gestor)
    assert reverse('ausencias:registrar') in html(client)


# ---------------------------------------------------------------------------
# Formulário de filtros
# ---------------------------------------------------------------------------
def test_formulario_get_com_url_dos_dados_e_aviso_sem_javascript(logado):
    conteudo = html(logado)

    assert 'method="get"' in conteudo
    assert f'data-url-dados="{reverse("painel:dados")}"' in conteudo
    assert '<noscript>' in conteudo
    assert 'css/painel.css' in conteudo


def test_painel_css_depois_do_agenda_css(logado):
    conteudo = html(logado)

    assert conteudo.index('css/agenda.css') < conteudo.index('css/painel.css')


def test_campos_mostram_o_que_veio_na_url(logado):
    conteudo = html(logado, q='ana', ausente_de='2026-03-10', presente_ate='2026-04-01')

    assert 'name="q" id="filtro-q" class="form-control" value="ana"' in conteudo
    assert 'name="ausente_de" class="form-control" value="2026-03-10"' in conteudo
    assert 'name="presente_ate" class="form-control" value="2026-04-01"' in conteudo


def test_sem_registros_marcado_por_padrao(logado):
    conteudo = html(logado)

    assert 'name="sem_registros" value="1"\n                 checked' in conteudo


@pytest.mark.parametrize('valores', [['0'], '0'])
def test_sem_registros_desmarcado(logado, valores):
    conteudo = html(logado, sem_registros=valores)

    assert 'name="sem_registros" value="1"\n                 checked' not in conteudo


def test_hidden_mais_caixa_marcada_continua_marcado(logado):
    assert 'name="sem_registros" value="1"\n                 checked' in html(logado, sem_registros=['0', '1'])


def test_departamentos_todos_sem_parametro(logado, ti, rh):
    conteudo = html(logado)

    assert 'data-todos\n                     checked' in conteudo
    assert '<span data-resumo>Todos</span>' in conteudo
    # "Sem departamento" é a última opção.
    assert conteudo.index('>RH<') < conteudo.index('>TI<') < conteudo.index('Sem departamento\n')


def test_departamentos_marcados(logado, ti, rh):
    conteudo = html(logado, departamento=[ti.pk, 'sem'])

    assert f'value="{ti.pk}"\n                     data-nome="TI"\n                     checked' in conteudo
    assert f'value="{rh.pk}"\n                     data-nome="RH"\n                     checked' not in conteudo
    assert 'data-nome="Sem departamento" checked' in conteudo
    assert 'data-todos\n                     checked' not in conteudo
    assert '<span data-resumo>2 departamentos</span>' in conteudo


def test_avisos_aparecem_na_pagina(logado):
    conteudo = html(logado, ausente_de='2026-02-31')

    assert 'alert alert-warning' in conteudo
    assert 'O filtro &quot;Ausência em&quot; foi ignorado' in conteudo


def test_nome_de_departamento_escapado(logado):
    Departamento.objects.create(nome='<script>alert(1)</script>')

    conteudo = html(logado)

    assert '<script>alert(1)</script>' not in conteudo
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in conteudo


# ---------------------------------------------------------------------------
# Rótulo da multisseleção
# ---------------------------------------------------------------------------
def test_rotulo_departamentos(ti, rh):
    departamentos = [ti, rh]

    assert rotulo_departamentos((), departamentos) == 'Todos'
    assert rotulo_departamentos((ti.pk,), departamentos) == 'TI'
    assert rotulo_departamentos(('sem',), departamentos) == 'Sem departamento'
    assert rotulo_departamentos((ti.pk, 'sem'), departamentos) == '2 departamentos'
    assert rotulo_departamentos((ti.pk, rh.pk, 'sem'), departamentos) == '3 departamentos'
    # Id que não existe não conta.
    assert rotulo_departamentos((999999,), departamentos) == 'Todos'
    assert rotulo_departamentos((999999, rh.pk), departamentos) == 'RH'
