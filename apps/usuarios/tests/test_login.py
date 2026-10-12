import pytest
from django.contrib.auth import SESSION_KEY, authenticate
from django.test import RequestFactory
from django.urls import reverse

pytestmark = pytest.mark.django_db

URL_LOGIN = reverse('usuarios:login')
# Depois do login: o painel (página inicial).
URL_HOME = reverse('painel:painel')

MSG_PENDENTE = 'Seu cadastro está aguardando aprovação do administrador.'
MSG_DESATIVADO = 'Este usuário está desativado.'
MSG_GENERICA = 'E-mail ou senha incorretos.'


def _entrar(client, email, senha):
    return client.post(URL_LOGIN, {'username': email, 'password': senha})


def _erros(response):
    return response.context['form'].non_field_errors()


def test_login_com_sucesso(client, usuario_ativo, senha):
    response = _entrar(client, usuario_ativo.email, senha)

    assert response.status_code == 302
    assert response.url == URL_HOME
    assert client.session[SESSION_KEY] == str(usuario_ativo.pk)


def test_login_ignora_caixa_do_email(client, usuario_ativo, senha):
    response = _entrar(client, 'ATIVO@Scriba.com.br', senha)

    assert response.status_code == 302
    assert client.session[SESSION_KEY] == str(usuario_ativo.pk)


def test_login_respeita_next(client, usuario_ativo, senha):
    destino = reverse('usuarios:password_change')
    response = client.post(f'{URL_LOGIN}?next={destino}', {
        'username': usuario_ativo.email, 'password': senha, 'next': destino,
    })

    assert response.status_code == 302
    assert response.url == destino


def test_login_senha_errada(client, usuario_ativo):
    response = _entrar(client, usuario_ativo.email, 'senha-errada')

    assert response.status_code == 200
    assert _erros(response) == [MSG_GENERICA]
    assert SESSION_KEY not in client.session


def test_login_email_inexistente_mesma_mensagem(client):
    response = _entrar(client, 'ninguem@scriba.com.br', 'qualquer-coisa')

    assert response.status_code == 200
    assert _erros(response) == [MSG_GENERICA]


def test_login_usuario_pendente(client, usuario_pendente, senha):
    response = _entrar(client, usuario_pendente.email, senha)

    assert response.status_code == 200
    assert _erros(response) == [MSG_PENDENTE]
    assert SESSION_KEY not in client.session


def test_login_usuario_desativado(client, usuario_desativado, senha):
    response = _entrar(client, usuario_desativado.email, senha)

    assert response.status_code == 200
    assert _erros(response) == [MSG_DESATIVADO]
    assert SESSION_KEY not in client.session


@pytest.mark.parametrize('fixture', ['usuario_pendente', 'usuario_desativado'])
def test_inativo_com_senha_errada_recebe_mensagem_generica(client, request, fixture):
    """Sem a senha certa, não se revela a situação da conta."""
    usuario = request.getfixturevalue(fixture)

    response = _entrar(client, usuario.email, 'senha-errada')

    assert _erros(response) == [MSG_GENERICA]


@pytest.mark.parametrize('fixture', ['usuario_pendente', 'usuario_desativado'])
def test_inativo_nunca_fica_autenticado(client, request, fixture, senha):
    usuario = request.getfixturevalue(fixture)

    # O backend devolve o inativo no authenticate() (para a mensagem)...
    # (O backend do django-axes exige o request no authenticate().)
    request = RequestFactory().post(URL_LOGIN)
    assert authenticate(request, username=usuario.email, password=senha) == usuario
    # ...mas o login não acontece e a home continua fechada.
    _entrar(client, usuario.email, senha)
    assert SESSION_KEY not in client.session
    response = client.get(URL_HOME)
    assert response.status_code == 302
    assert response.url.startswith(URL_LOGIN)


def test_inativo_com_sessao_forcada_nao_e_reconhecido(client, usuario_desativado):
    """Mesmo com a sessão criada à força, o backend não devolve inativo."""
    client.force_login(usuario_desativado)

    response = client.get(URL_HOME)

    assert response.status_code == 302
    assert response.url.startswith(URL_LOGIN)


def test_usuario_desativado_apos_login_perde_acesso(client, usuario_ativo, senha):
    _entrar(client, usuario_ativo.email, senha)
    assert client.get(URL_HOME).status_code == 200

    usuario_ativo.is_active = False
    usuario_ativo.save()

    response = client.get(URL_HOME)
    assert response.status_code == 302
    assert response.url.startswith(URL_LOGIN)


def test_pagina_protegida_redireciona_para_login(client):
    response = client.get(URL_HOME)

    assert response.status_code == 302
    assert response.url == f'{URL_LOGIN}?next={URL_HOME}'


def test_home_logado(client, usuario_ativo):
    client.force_login(usuario_ativo)

    response = client.get(URL_HOME)

    assert response.status_code == 200
    assert 'Usuária' in response.content.decode()


def test_usuario_logado_no_login_vai_para_home(client, usuario_ativo):
    client.force_login(usuario_ativo)

    response = client.get(URL_LOGIN)

    assert response.status_code == 302
    assert response.url == URL_HOME


def test_logout_via_post(client, usuario_ativo):
    client.force_login(usuario_ativo)

    response = client.post(reverse('usuarios:logout'))

    assert response.status_code == 302
    assert response.url == URL_LOGIN
    assert SESSION_KEY not in client.session


def test_logout_via_get_nao_permitido(client, usuario_ativo):
    client.force_login(usuario_ativo)

    response = client.get(reverse('usuarios:logout'))

    assert response.status_code == 405
    assert client.session[SESSION_KEY] == str(usuario_ativo.pk)
