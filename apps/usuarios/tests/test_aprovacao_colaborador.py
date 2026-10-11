"""Vínculo usuário↔colaborador na aprovação de cadastros pendentes (etapa 3)."""

import pytest
from django.urls import reverse

from apps.colaboradores.models import Colaborador
from apps.usuarios import usuarios_service
from apps.usuarios.models import User

pytestmark = pytest.mark.django_db

URL_PENDENTES = reverse('usuarios:pendentes')
URL_LOGIN = 'http://testserver/entrar/'


def _aprovar(client, usuario, colaborador=None):
    dados = {'colaborador': colaborador.pk if colaborador else ''}
    return client.post(reverse('usuarios:aprovar_usuario', args=[usuario.pk]), dados)


def _mensagens(response):
    return [str(m) for m in response.wsgi_request._messages]


def _pendente(nome, email):
    return User.objects.create_user(email, 'x', nome=nome, is_active=False)


@pytest.fixture
def admin_client(client, admin):
    client.force_login(admin)
    return client


@pytest.fixture
def colaborador(db):
    return Colaborador.objects.create(nome='Pendente')


# ---------------------------------------------------------------------------
# Aprovar com e sem vínculo
# ---------------------------------------------------------------------------
def test_aprovar_com_vinculo(admin_client, admin, usuario_pendente, colaborador):
    response = _aprovar(admin_client, usuario_pendente, colaborador)

    assert response.status_code == 302
    usuario_pendente.refresh_from_db()
    colaborador.refresh_from_db()
    assert usuario_pendente.is_active is True
    assert usuario_pendente.groups.filter(name='Gestor').exists()
    assert colaborador.usuario == usuario_pendente
    assert colaborador.atualizado_por == admin
    assert 'aprovado e vinculado a "Pendente"' in _mensagens(response)[0]


def test_aprovar_sem_vinculo(admin_client, usuario_pendente, colaborador):
    response = _aprovar(admin_client, usuario_pendente)

    usuario_pendente.refresh_from_db()
    assert usuario_pendente.is_active is True
    assert not Colaborador.objects.filter(usuario=usuario_pendente).exists()
    assert _mensagens(response) == [f'Cadastro de {usuario_pendente.email} aprovado.']


def test_aprovar_sem_campo_colaborador_no_post(admin_client, usuario_pendente):
    # POST antigo (etapa 2), sem o campo: continua aprovando.
    admin_client.post(reverse('usuarios:aprovar_usuario', args=[usuario_pendente.pk]))

    usuario_pendente.refresh_from_db()
    assert usuario_pendente.is_active is True


@pytest.mark.parametrize('valor', ['abc', '-1', '0'])
def test_colaborador_invalido_nao_aprova(admin_client, usuario_pendente, valor):
    response = admin_client.post(reverse('usuarios:aprovar_usuario', args=[usuario_pendente.pk]), {'colaborador': valor})

    usuario_pendente.refresh_from_db()
    assert usuario_pendente.is_active is False
    assert 'Colaborador inválido' in _mensagens(response)[0]


def test_vinculo_concorrente_recusa_a_aprovacao(admin_client, usuario_pendente, colaborador, gestor):
    # A tela foi aberta com o colaborador livre; antes do clique, outro
    # usuário foi vinculado a ele.
    Colaborador.objects.filter(pk=colaborador.pk).update(usuario=gestor)

    response = _aprovar(admin_client, usuario_pendente, colaborador)

    usuario_pendente.refresh_from_db()
    assert usuario_pendente.is_active is False
    assert usuario_pendente.aprovado_em is None
    assert not usuario_pendente.groups.exists()
    colaborador.refresh_from_db()
    assert colaborador.usuario == gestor
    assert _mensagens(response) == [
        'O colaborador "Pendente" já está vinculado a outro usuário. '
        'O cadastro não foi aprovado; escolha outro colaborador ou nenhum.'
    ]


def test_colaborador_inativo_recusa_a_aprovacao(admin_client, usuario_pendente, colaborador):
    Colaborador.objects.filter(pk=colaborador.pk).update(ativo=False)

    response = _aprovar(admin_client, usuario_pendente, colaborador)

    usuario_pendente.refresh_from_db()
    assert usuario_pendente.is_active is False
    assert 'está inativo' in _mensagens(response)[0]


def test_colaborador_inexistente_recusa_a_aprovacao(admin, usuario_pendente):
    with pytest.raises(usuarios_service.VinculoRecusado, match='não existe mais'):
        usuarios_service.aprovar_usuario(usuario_pendente.pk, URL_LOGIN, colaborador_id=999999)

    usuario_pendente.refresh_from_db()
    assert usuario_pendente.is_active is False


def test_aprovacao_idempotente_nao_altera_vinculo(usuario_pendente, colaborador):
    usuarios_service.aprovar_usuario(usuario_pendente.pk, URL_LOGIN)
    outro = Colaborador.objects.create(nome='Outro')

    usuario, aprovado_agora = usuarios_service.aprovar_usuario(usuario_pendente.pk, URL_LOGIN, colaborador_id=outro.pk)

    assert aprovado_agora is False
    outro.refresh_from_db()
    assert outro.usuario is None


def test_desativado_continua_recusado_com_colaborador(usuario_desativado, colaborador):
    with pytest.raises(usuarios_service.UsuarioNaoPendente):
        usuarios_service.aprovar_usuario(usuario_desativado.pk, URL_LOGIN, colaborador_id=colaborador.pk)

    colaborador.refresh_from_db()
    assert colaborador.usuario is None


def test_gestor_nao_aprova_nem_vincula(client, gestor, usuario_pendente, colaborador):
    client.force_login(gestor)

    assert _aprovar(client, usuario_pendente, colaborador).status_code == 403
    colaborador.refresh_from_db()
    assert colaborador.usuario is None


# ---------------------------------------------------------------------------
# Tela: select e pré-seleção
# ---------------------------------------------------------------------------
def _sugestoes(response):
    return {p.email: p.colaborador_sugerido for p in response.context['pendentes']}


def test_select_lista_so_colaboradores_ativos_sem_usuario(admin_client, usuario_pendente, colaborador, gestor):
    Colaborador.objects.create(nome='Inativa', ativo=False)
    Colaborador.objects.create(nome='Já Vinculada', usuario=gestor)

    response = admin_client.get(URL_PENDENTES)

    assert response.context['colaboradores_vinculaveis'] == [colaborador]


def test_pre_seleciona_pelo_nome_normalizado(admin_client):
    esperado = Colaborador.objects.create(nome='José da Silva')
    _pendente('  JOSE  da silva ', 'jose@scriba.com.br')

    response = admin_client.get(URL_PENDENTES)

    assert _sugestoes(response) == {'jose@scriba.com.br': esperado}
    assert f'<option value="{esperado.pk}" selected>José da Silva</option>' in response.content.decode()
    assert 'Sugerido pelo nome' in response.content.decode()


def test_sem_homonimo_nao_pre_seleciona(admin_client, usuario_pendente):
    Colaborador.objects.create(nome='Outra Pessoa')

    response = admin_client.get(URL_PENDENTES)

    assert _sugestoes(response) == {usuario_pendente.email: None}
    assert ' selected>' not in response.content.decode()


def test_homonimo_inativo_nao_pre_seleciona(admin_client, usuario_pendente):
    Colaborador.objects.create(nome='Pendente', ativo=False)

    assert _sugestoes(admin_client.get(URL_PENDENTES)) == {usuario_pendente.email: None}


def test_homonimo_ja_vinculado_nao_pre_seleciona(admin_client, usuario_pendente, gestor):
    Colaborador.objects.create(nome='Pendente', usuario=gestor)

    assert _sugestoes(admin_client.get(URL_PENDENTES)) == {usuario_pendente.email: None}


def test_nome_parcial_nao_pre_seleciona(admin_client):
    Colaborador.objects.create(nome='José da Silva Júnior')
    _pendente('José da Silva', 'jose@scriba.com.br')

    assert _sugestoes(admin_client.get(URL_PENDENTES)) == {'jose@scriba.com.br': None}


def test_varios_candidatos_e_impossivel_por_construcao():
    # "Vários candidatos" não ocorre: nome_normalizado é único, então há no
    # máximo um homônimo. A função ainda exige exatamente um.
    field = Colaborador._meta.get_field('nome_normalizado')
    assert field.unique is True


def test_pre_selecao_nao_vincula_sem_confirmar(admin_client, usuario_pendente, colaborador):
    admin_client.get(URL_PENDENTES)

    colaborador.refresh_from_db()
    assert colaborador.usuario is None


def test_sem_pendentes_a_tela_continua_funcionando(admin_client):
    response = admin_client.get(URL_PENDENTES)

    assert response.status_code == 200
    assert 'Nenhum cadastro aguardando aprovação.' in response.content.decode()
