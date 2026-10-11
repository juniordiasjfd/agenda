import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.usuarios import usuarios_service
from apps.usuarios.models import DominioAutocadastro, User

pytestmark = pytest.mark.django_db


def test_data_migration_criou_scriba_ativo():
    dominio = DominioAutocadastro.objects.get(dominio='scriba.com.br')
    assert dominio.ativo


def test_save_normaliza():
    dominio = DominioAutocadastro.objects.create(dominio='  @Exemplo. COM.br ')

    dominio.refresh_from_db()
    assert dominio.dominio == 'exemplo.com.br'


@pytest.mark.parametrize('valor', ['exemplo', 'exemplo.c', '-exemplo.com', 'exe_mplo.com', 'a@b.com', 'exemplo..com', '.com'])
def test_clean_recusa_formato_invalido(valor):
    with pytest.raises(ValidationError) as erro:
        DominioAutocadastro(dominio=valor).full_clean()

    assert 'dominio' in erro.value.message_dict


def test_clean_aceita_e_normaliza():
    dominio = DominioAutocadastro(dominio='@Sub.Exemplo.com.br')

    dominio.full_clean()

    assert dominio.dominio == 'sub.exemplo.com.br'


def test_clean_recusa_duplicado_com_caixa_diferente():
    with pytest.raises(ValidationError) as erro:
        DominioAutocadastro(dominio='SCRIBA.com.br').full_clean()

    assert erro.value.message_dict['dominio'] == ['Este domínio já está cadastrado.']


@pytest.mark.parametrize('email', ['fulana@scriba.com.br', 'Fulana@SCRIBA.com.br', ' fulana@scriba.com.br '])
def test_email_do_dominio_ativo_passa(email):
    assert usuarios_service.email_permitido(email)


@pytest.mark.parametrize('email', [
    'x@scriba.com.br.evil.com',
    'x@evilscriba.com.br',
    'x@sub.scriba.com.br',
    'x@scriba.com',
    'scriba.com.br',
    'x@evil.com@scriba.com.br.evil.com',
    '',
])
def test_email_fora_do_dominio_nao_passa(email):
    assert not usuarios_service.email_permitido(email)


def test_usa_o_ultimo_arroba():
    assert usuarios_service.dominio_do_email('"a@b"@scriba.com.br') == 'scriba.com.br'


def test_dominio_inativo_nao_vale():
    DominioAutocadastro.objects.filter(dominio='scriba.com.br').update(ativo=False)
    DominioAutocadastro.objects.create(dominio='outro.com.br')

    assert not usuarios_service.email_permitido('x@scriba.com.br')
    assert usuarios_service.email_permitido('x@outro.com.br')


def test_habilitado_com_dominio_ativo():
    assert usuarios_service.autocadastro_habilitado()


def test_sem_dominio_ativo_desabilita():
    DominioAutocadastro.objects.update(ativo=False)

    assert not usuarios_service.autocadastro_habilitado()
    assert not usuarios_service.email_permitido('x@scriba.com.br')


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
@pytest.fixture
def admin_client(client, senha):
    admin = User.objects.create_superuser('admin@scriba.com.br', senha, nome='Admin')
    client.force_login(admin)
    return client


def test_admin_cria_dominio_normalizado_com_auditoria(admin_client):
    response = admin_client.post(
        reverse('admin:usuarios_dominioautocadastro_add'), {'dominio': ' @Novo.COM.br', 'ativo': 'on'},
    )

    assert response.status_code == 302
    dominio = DominioAutocadastro.objects.get(dominio='novo.com.br')
    assert dominio.criado_por.email == 'admin@scriba.com.br'
    assert dominio.atualizado_por.email == 'admin@scriba.com.br'


def test_admin_recusa_dominio_invalido(admin_client):
    response = admin_client.post(
        reverse('admin:usuarios_dominioautocadastro_add'), {'dominio': 'nao é domínio', 'ativo': 'on'},
    )

    assert response.status_code == 200
    assert not DominioAutocadastro.objects.exclude(dominio='scriba.com.br').exists()


def test_admin_lista_e_filtra(admin_client):
    response = admin_client.get(reverse('admin:usuarios_dominioautocadastro_changelist'), {'ativo__exact': '1'})

    assert response.status_code == 200
    assert 'scriba.com.br' in response.content.decode()
