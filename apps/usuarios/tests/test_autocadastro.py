import pytest
from django.contrib.auth.hashers import check_password
from django.urls import reverse

from apps.usuarios import usuarios_service
from apps.usuarios.models import DominioAutocadastro, User

pytestmark = pytest.mark.django_db

URL_CADASTRO = reverse('usuarios:cadastro')
URL_RECEBIDO = reverse('usuarios:cadastro_recebido')
URL_LOGIN = reverse('usuarios:login')
SENHA_NOVA = 'Cadastro-Forte-2026!'
MSG_DOMINIO = 'Somente e-mails de domínios autorizados podem se cadastrar.'


def _dados(**extra):
    dados = {
        'nome': '  Nova   Pessoa ',
        'email': 'Nova@Scriba.com.br',
        'password1': SENHA_NOVA,
        'password2': SENHA_NOVA,
    }
    dados.update(extra)
    return dados


def test_pagina_de_cadastro_abre(client):
    response = client.get(URL_CADASTRO)

    assert response.status_code == 200
    assert 'Criar conta' in response.content.decode()


def test_cadastro_cria_usuario_pendente(client):
    response = client.post(URL_CADASTRO, _dados())

    assert response.status_code == 302
    assert response.url == URL_RECEBIDO
    usuario = User.objects.get(email='nova@scriba.com.br')
    assert usuario.nome == 'Nova Pessoa'
    assert usuario.is_active is False
    assert usuario.aprovado_em is None
    assert not usuario.groups.exists()
    assert not usuario.is_staff and not usuario.is_superuser
    assert usuario.aguardando_aprovacao
    assert check_password(SENHA_NOVA, usuario.password)


def test_pagina_recebido_fala_de_aprovacao(client):
    response = client.get(URL_RECEBIDO)

    assert 'aguarda a aprovação do administrador' in response.content.decode()


@pytest.mark.parametrize('email', ['x@gmail.com', 'x@sub.scriba.com.br', 'x@scriba.com.br.evil.com'])
def test_email_fora_do_dominio_recusado(client, email):
    response = client.post(URL_CADASTRO, _dados(email=email))

    assert response.status_code == 200
    erros = response.context['form'].errors['email']
    assert erros[0].startswith(MSG_DOMINIO)
    # Não lista os domínios autorizados.
    assert 'scriba.com.br' not in erros[0]
    assert not User.objects.filter(email=email).exists()


@pytest.mark.parametrize('email', ['ativo@scriba.com.br', 'ATIVO@Scriba.COM.br'])
def test_email_duplicado_mesma_resposta_e_nada_criado(client, usuario_ativo, email):
    senha_antes = usuario_ativo.password
    total_antes = User.objects.count()

    response = client.post(URL_CADASTRO, _dados(email=email))

    assert response.status_code == 302
    assert response.url == URL_RECEBIDO
    assert User.objects.count() == total_antes
    usuario_ativo.refresh_from_db()
    assert usuario_ativo.password == senha_antes
    assert usuario_ativo.nome == 'Usuária Ativa'


def test_email_duplicado_registra_em_log(client, usuario_ativo, caplog):
    with caplog.at_level('INFO', logger='apps.usuarios.usuarios_service'):
        client.post(URL_CADASTRO, _dados(email='ativo@scriba.com.br'))

    assert 'e-mail já cadastrado' in caplog.text


@pytest.mark.parametrize('senha_fraca', ['123', '12345678901', 'password123', 'novapessoa1'])
def test_senha_fraca_recusada(client, senha_fraca):
    response = client.post(URL_CADASTRO, _dados(password1=senha_fraca, password2=senha_fraca))

    assert response.status_code == 200
    assert response.context['form'].errors['password2']
    assert not User.objects.filter(email='nova@scriba.com.br').exists()


def test_confirmacao_diferente_recusada(client):
    response = client.post(URL_CADASTRO, _dados(password2='Outra-Senha-2026!'))

    assert response.status_code == 200
    assert response.context['form'].errors['password2']
    assert not User.objects.filter(email='nova@scriba.com.br').exists()


def test_usuario_logado_vai_para_home(client, usuario_ativo):
    client.force_login(usuario_ativo)

    response = client.get(URL_CADASTRO)

    assert response.status_code == 302
    assert response.url == reverse('core:home')


def test_pendente_tentando_entrar_ve_mensagem_de_aprovacao(client):
    client.post(URL_CADASTRO, _dados())

    response = client.post(URL_LOGIN, {'username': 'nova@scriba.com.br', 'password': SENHA_NOVA})

    assert response.status_code == 200
    assert response.context['form'].non_field_errors() == [
        'Seu cadastro está aguardando aprovação do administrador.'
    ]


def test_service_recusa_email_nao_permitido():
    with pytest.raises(usuarios_service.EmailNaoPermitido):
        usuarios_service.registrar_autocadastro('X', 'x@gmail.com', SENHA_NOVA, 'http://testserver/')


# ---------------------------------------------------------------------------
# Autocadastro desligado (nenhum domínio ativo)
# ---------------------------------------------------------------------------
@pytest.fixture
def sem_dominio_ativo(db):
    DominioAutocadastro.objects.update(ativo=False)


def test_login_mostra_link_com_autocadastro_habilitado(client):
    response = client.get(URL_LOGIN)

    assert URL_CADASTRO in response.content.decode()


def test_login_sem_link_com_autocadastro_desligado(client, sem_dominio_ativo):
    response = client.get(URL_LOGIN)

    assert URL_CADASTRO not in response.content.decode()


def test_pagina_explica_cadastro_desligado(client, sem_dominio_ativo):
    response = client.get(URL_CADASTRO)

    assert response.status_code == 200
    assert 'Cadastro indisponível' in response.content.decode()
    assert 'form' not in response.context


def test_post_com_cadastro_desligado_nao_cria(client, sem_dominio_ativo):
    response = client.post(URL_CADASTRO, _dados())

    assert response.status_code == 200
    assert 'Cadastro indisponível' in response.content.decode()
    assert not User.objects.filter(email='nova@scriba.com.br').exists()
