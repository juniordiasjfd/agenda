import pytest
from django.urls import reverse

from apps.colaboradores.models import Departamento

pytestmark = pytest.mark.django_db

URL_LISTA = reverse('colaboradores:departamentos')
URL_CRIAR = reverse('colaboradores:departamento_criar')


def _editar(departamento):
    return reverse('colaboradores:departamento_editar', args=[departamento.pk])


def _excluir(departamento):
    return reverse('colaboradores:departamento_excluir', args=[departamento.pk])


def _mensagens(response):
    return [str(m) for m in response.wsgi_request._messages]


# ---------------------------------------------------------------------------
# Acesso
# ---------------------------------------------------------------------------
def _rotas(departamento):
    return [
        ('get', URL_LISTA),
        ('get', URL_CRIAR),
        ('post', URL_CRIAR),
        ('get', _editar(departamento)),
        ('post', _editar(departamento)),
        ('post', _excluir(departamento)),
    ]


def test_anonimo_vai_para_o_login(client, departamento):
    for metodo, url in _rotas(departamento):
        response = getattr(client, metodo)(url)
        assert response.status_code == 302, url
        assert response.url.startswith(reverse('usuarios:login')), url


def test_gestor_recebe_403(gestor_client, departamento):
    for metodo, url in _rotas(departamento):
        assert getattr(gestor_client, metodo)(url).status_code == 403, url
    assert Departamento.objects.filter(pk=departamento.pk).exists()


def test_admin_acessa(admin_client, departamento):
    for url in [URL_LISTA, URL_CRIAR, _editar(departamento)]:
        assert admin_client.get(url).status_code == 200, url


def test_excluir_so_por_post(admin_client, departamento):
    assert admin_client.get(_excluir(departamento)).status_code == 405
    assert Departamento.objects.filter(pk=departamento.pk).exists()


# ---------------------------------------------------------------------------
# Lista
# ---------------------------------------------------------------------------
def test_lista_mostra_total_de_colaboradores(admin_client, colaborador, departamento):
    Departamento.objects.create(nome='Vazio')

    response = admin_client.get(URL_LISTA)

    totais = {d.nome: d.total_colaboradores for d in response.context['departamentos']}
    assert totais == {'Financeiro': 1, 'Vazio': 0}


# ---------------------------------------------------------------------------
# Criar / editar
# ---------------------------------------------------------------------------
def test_criar(admin_client, admin):
    response = admin_client.post(URL_CRIAR, {'nome': '  Recursos   Humanos '})

    assert response.status_code == 302
    assert response.url == URL_LISTA
    departamento = Departamento.objects.get()
    assert departamento.nome == 'Recursos Humanos'
    assert departamento.criado_por == admin
    assert departamento.atualizado_por == admin


def test_criar_nome_duplicado_sem_diferenca_de_caixa(admin_client, departamento):
    response = admin_client.post(URL_CRIAR, {'nome': 'FINANCEIRO'})

    assert response.status_code == 200
    assert response.context['form'].errors == {'nome': ['Já existe um departamento com este nome.']}
    assert Departamento.objects.count() == 1


def test_editar(admin_client, admin, departamento):
    response = admin_client.post(_editar(departamento), {'nome': 'Finanças'})

    assert response.status_code == 302
    departamento.refresh_from_db()
    assert departamento.nome == 'Finanças'
    assert departamento.atualizado_por == admin


def test_editar_mantendo_o_nome_com_outra_caixa(admin_client, departamento):
    response = admin_client.post(_editar(departamento), {'nome': 'FINANCEIRO'})

    assert response.status_code == 302
    departamento.refresh_from_db()
    assert departamento.nome == 'FINANCEIRO'


def test_editar_para_nome_de_outro(admin_client, departamento):
    outro = Departamento.objects.create(nome='Jurídico')

    response = admin_client.post(_editar(outro), {'nome': 'financeiro'})

    assert response.status_code == 200
    assert 'nome' in response.context['form'].errors


# ---------------------------------------------------------------------------
# Excluir
# ---------------------------------------------------------------------------
def test_excluir_sem_colaboradores(admin_client, departamento):
    response = admin_client.post(_excluir(departamento))

    assert response.status_code == 302
    assert not Departamento.objects.exists()
    assert 'Departamento "Financeiro" excluído.' in _mensagens(response)


def test_excluir_com_colaboradores_e_recusado(admin_client, colaborador, departamento):
    response = admin_client.post(_excluir(departamento))

    assert response.status_code == 302
    assert Departamento.objects.filter(pk=departamento.pk).exists()
    assert 'não pode ser excluído' in _mensagens(response)[0]


def test_excluir_com_colaborador_inativo_e_recusado(admin_client, colaborador, departamento):
    colaborador.ativo = False
    colaborador.save()

    admin_client.post(_excluir(departamento))

    assert Departamento.objects.filter(pk=departamento.pk).exists()


def test_excluir_inexistente_404(admin_client):
    assert admin_client.post(reverse('colaboradores:departamento_excluir', args=[999])).status_code == 404
