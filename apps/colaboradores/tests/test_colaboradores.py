import pytest
from django.urls import reverse

from apps.colaboradores.models import Colaborador, Departamento
from apps.usuarios.models import User

pytestmark = pytest.mark.django_db

URL_LISTA = reverse('colaboradores:colaboradores')
URL_CRIAR = reverse('colaboradores:colaborador_criar')


def _editar(colaborador):
    return reverse('colaboradores:colaborador_editar', args=[colaborador.pk])


def _ativar(colaborador):
    return reverse('colaboradores:colaborador_ativar', args=[colaborador.pk])


def _desativar(colaborador):
    return reverse('colaboradores:colaborador_desativar', args=[colaborador.pk])


def _nomes(response):
    return [c.nome for c in response.context['colaboradores']]


def _dados(**extra):
    return {'nome': 'Maria Souza', 'departamento': '', 'ativo': 'on', 'usuario': '', **extra}


# ---------------------------------------------------------------------------
# Acesso
# ---------------------------------------------------------------------------
def _rotas(colaborador):
    return [
        ('get', URL_LISTA),
        ('get', URL_CRIAR),
        ('post', URL_CRIAR),
        ('get', _editar(colaborador)),
        ('post', _editar(colaborador)),
        ('post', _ativar(colaborador)),
        ('post', _desativar(colaborador)),
    ]


def test_anonimo_vai_para_o_login(client, colaborador):
    for metodo, url in _rotas(colaborador):
        response = getattr(client, metodo)(url)
        assert response.status_code == 302, url
        assert response.url.startswith(reverse('usuarios:login')), url


def test_gestor_recebe_403(gestor_client, colaborador):
    for metodo, url in _rotas(colaborador):
        assert getattr(gestor_client, metodo)(url).status_code == 403, url
    colaborador.refresh_from_db()
    assert colaborador.ativo is True


def test_admin_acessa(admin_client, colaborador):
    for url in [URL_LISTA, URL_CRIAR, _editar(colaborador)]:
        assert admin_client.get(url).status_code == 200, url


def test_menu_do_admin_tem_colaboradores_e_departamentos(admin_client):
    conteudo = admin_client.get(URL_LISTA).content.decode()
    assert reverse('colaboradores:colaboradores') in conteudo
    assert reverse('colaboradores:departamentos') in conteudo


# ---------------------------------------------------------------------------
# Lista: busca e filtros
# ---------------------------------------------------------------------------
@pytest.fixture
def cenario(departamento):
    juridico = Departamento.objects.create(nome='Jurídico')
    Colaborador.objects.create(nome='José da Silva', departamento=departamento)
    Colaborador.objects.create(nome='Joana Prado', departamento=juridico)
    Colaborador.objects.create(nome='Ângela Moura')
    Colaborador.objects.create(nome='Antônio Lima', ativo=False)
    return {'financeiro': departamento, 'juridico': juridico}


def test_padrao_lista_so_ativos(admin_client, cenario):
    assert _nomes(admin_client.get(URL_LISTA)) == ['Ângela Moura', 'Joana Prado', 'José da Silva']


@pytest.mark.parametrize('busca, esperado', [
    ('jose', ['José da Silva']),
    ('JOSÉ  DA', ['José da Silva']),
    ('angela', ['Ângela Moura']),
    ('ÂNGELA', ['Ângela Moura']),
    ('jo', ['Joana Prado', 'José da Silva']),
    ('silva prado', []),
])
def test_busca_sem_acento_caixa_e_espacos(admin_client, cenario, busca, esperado):
    assert _nomes(admin_client.get(URL_LISTA, {'busca': busca})) == esperado


def test_filtro_por_departamento(admin_client, cenario):
    response = admin_client.get(URL_LISTA, {'departamento': cenario['juridico'].pk})
    assert _nomes(response) == ['Joana Prado']


def test_filtro_sem_departamento(admin_client, cenario):
    response = admin_client.get(URL_LISTA, {'departamento': 'sem', 'situacao': 'todos'})
    assert _nomes(response) == ['Ângela Moura', 'Antônio Lima']


@pytest.mark.parametrize('situacao, esperado', [
    ('inativos', ['Antônio Lima']),
    ('todos', ['Ângela Moura', 'Antônio Lima', 'Joana Prado', 'José da Silva']),
    ('ativos', ['Ângela Moura', 'Joana Prado', 'José da Silva']),
])
def test_filtro_por_situacao(admin_client, cenario, situacao, esperado):
    assert _nomes(admin_client.get(URL_LISTA, {'situacao': situacao})) == esperado


def test_filtros_combinados(admin_client, cenario):
    response = admin_client.get(URL_LISTA, {'busca': 'an', 'departamento': 'sem', 'situacao': 'todos'})
    assert _nomes(response) == ['Ângela Moura', 'Antônio Lima']


def test_filtro_invalido_cai_no_padrao(admin_client, cenario):
    response = admin_client.get(URL_LISTA, {'departamento': 'xyz', 'situacao': 'qualquer'})
    assert response.status_code == 200
    assert _nomes(response) == ['Ângela Moura', 'Joana Prado', 'José da Silva']


def test_contador_sem_departamento_conta_so_ativos(admin_client, cenario):
    response = admin_client.get(URL_LISTA)

    assert response.context['sem_departamento'] == 1
    assert '1 colaborador ativo' in response.content.decode()


def test_contador_some_quando_todos_tem_departamento(admin_client, colaborador):
    response = admin_client.get(URL_LISTA)

    assert response.context['sem_departamento'] == 0
    assert 'sem departamento.' not in response.content.decode()


def test_paginacao_mantem_filtros(admin_client):
    Colaborador.objects.bulk_create(
        Colaborador(nome=f'Pessoa {i:03d}', nome_normalizado=f'pessoa {i:03d}') for i in range(60)
    )

    pagina1 = admin_client.get(URL_LISTA, {'busca': 'pessoa'})
    pagina2 = admin_client.get(URL_LISTA, {'busca': 'pessoa', 'page': 2})

    assert len(pagina1.context['colaboradores']) == 50
    assert len(pagina2.context['colaboradores']) == 10
    assert '?busca=pessoa&amp;page=2' in pagina1.content.decode()


# ---------------------------------------------------------------------------
# Criar / editar
# ---------------------------------------------------------------------------
def test_criar(admin_client, admin, departamento):
    response = admin_client.post(URL_CRIAR, _dados(nome='  Maria   Souza ', departamento=departamento.pk))

    assert response.status_code == 302
    colaborador = Colaborador.objects.get()
    assert colaborador.nome == 'Maria Souza'
    assert colaborador.departamento == departamento
    assert colaborador.ativo is True
    assert colaborador.criado_por == admin


def test_criar_sem_departamento(admin_client):
    admin_client.post(URL_CRIAR, _dados())
    assert Colaborador.objects.get().departamento is None


@pytest.mark.parametrize('variacao', ['jose da silva', 'JOSÉ  DA SILVA', 'José da Sílva'])
def test_criar_nome_duplicado(admin_client, colaborador, variacao):
    response = admin_client.post(URL_CRIAR, _dados(nome=variacao))

    assert response.status_code == 200
    assert 'Já existe um colaborador com este nome' in response.context['form'].errors['nome'][0]
    assert Colaborador.objects.count() == 1


def test_editar(admin_client, admin, colaborador):
    response = admin_client.post(_editar(colaborador), _dados(nome='José da Silva Júnior'))

    assert response.status_code == 302
    colaborador.refresh_from_db()
    assert colaborador.nome == 'José da Silva Júnior'
    assert colaborador.departamento is None
    assert colaborador.atualizado_por == admin


def test_editar_mantendo_o_nome_com_outra_grafia(admin_client, colaborador):
    response = admin_client.post(_editar(colaborador), _dados(nome='JOSÉ DA SILVA'))

    assert response.status_code == 302
    colaborador.refresh_from_db()
    assert colaborador.nome == 'JOSÉ DA SILVA'


def test_editar_para_nome_de_outro(admin_client, colaborador):
    outro = Colaborador.objects.create(nome='Maria Souza')

    response = admin_client.post(_editar(outro), _dados(nome='jose da silva'))

    assert response.status_code == 200
    assert 'nome' in response.context['form'].errors


# ---------------------------------------------------------------------------
# Usuário vinculado
# ---------------------------------------------------------------------------
def test_select_de_usuario_so_tem_ativos_sem_colaborador(admin_client, admin, usuario_ativo, usuario_pendente,
                                                         usuario_desativado, gestor):
    Colaborador.objects.create(nome='Do Gestor', usuario=gestor)

    opcoes = set(admin_client.get(URL_CRIAR).context['form'].fields['usuario'].queryset)

    assert opcoes == {admin, usuario_ativo}


def test_select_de_usuario_inclui_o_atual_na_edicao(admin_client, admin, usuario_ativo, gestor):
    colaborador = Colaborador.objects.create(nome='Do Gestor', usuario=gestor)

    opcoes = set(admin_client.get(_editar(colaborador)).context['form'].fields['usuario'].queryset)

    assert opcoes == {admin, usuario_ativo, gestor}


def test_vincular_usuario(admin_client, usuario_ativo):
    admin_client.post(URL_CRIAR, _dados(usuario=usuario_ativo.pk))

    assert Colaborador.objects.get().usuario == usuario_ativo
    assert User.objects.get(pk=usuario_ativo.pk).colaborador.nome == 'Maria Souza'


def test_editar_mantem_usuario_atual(admin_client, gestor):
    colaborador = Colaborador.objects.create(nome='Do Gestor', usuario=gestor)

    response = admin_client.post(_editar(colaborador), _dados(nome='Do Gestor', usuario=gestor.pk))

    assert response.status_code == 302
    colaborador.refresh_from_db()
    assert colaborador.usuario == gestor


def test_desvincular_usuario(admin_client, gestor):
    colaborador = Colaborador.objects.create(nome='Do Gestor', usuario=gestor)

    admin_client.post(_editar(colaborador), _dados(nome='Do Gestor', usuario=''))

    colaborador.refresh_from_db()
    assert colaborador.usuario is None


def test_recusa_usuario_ja_vinculado_a_outro(admin_client, gestor):
    Colaborador.objects.create(nome='Do Gestor', usuario=gestor)

    response = admin_client.post(URL_CRIAR, _dados(usuario=gestor.pk))

    assert response.status_code == 200
    assert 'usuario' in response.context['form'].errors
    assert Colaborador.objects.count() == 1


def test_recusa_usuario_inativo(admin_client, usuario_pendente):
    response = admin_client.post(URL_CRIAR, _dados(usuario=usuario_pendente.pk))

    assert response.status_code == 200
    assert 'usuario' in response.context['form'].errors


# ---------------------------------------------------------------------------
# Ativar / desativar
# ---------------------------------------------------------------------------
def test_desativar(admin_client, admin, colaborador):
    response = admin_client.post(_desativar(colaborador))

    assert response.status_code == 302
    assert response.url == URL_LISTA
    colaborador.refresh_from_db()
    assert colaborador.ativo is False
    assert colaborador.atualizado_por == admin


def test_ativar(admin_client, colaborador):
    Colaborador.objects.filter(pk=colaborador.pk).update(ativo=False)

    admin_client.post(_ativar(colaborador))

    colaborador.refresh_from_db()
    assert colaborador.ativo is True


def test_ativar_desativar_so_por_post(admin_client, colaborador):
    assert admin_client.get(_desativar(colaborador)).status_code == 405
    assert admin_client.get(_ativar(colaborador)).status_code == 405
    colaborador.refresh_from_db()
    assert colaborador.ativo is True


def test_desativar_volta_para_a_lista_filtrada(admin_client, colaborador):
    destino = f'{URL_LISTA}?busca=jose&page=1'

    response = admin_client.post(_desativar(colaborador), {'next': destino})

    assert response.url == destino


def test_desativar_ignora_next_externo(admin_client, colaborador):
    response = admin_client.post(_desativar(colaborador), {'next': 'https://malicioso.example/'})

    assert response.url == URL_LISTA


def test_desativar_inexistente_404(admin_client):
    assert admin_client.post(reverse('colaboradores:colaborador_desativar', args=[999])).status_code == 404


def test_nao_ha_rota_de_exclusao_de_colaborador():
    from apps.colaboradores import urls

    assert not [p for p in urls.urlpatterns if 'colaborador' in p.name and 'exclu' in p.name]
