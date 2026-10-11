import pytest
from django.urls import reverse

from apps.usuarios.models import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client(client, senha):
    admin = User.objects.create_superuser('admin@scriba.com.br', senha, nome='Admin')
    client.force_login(admin)
    return client


def test_lista_e_busca(admin_client, usuario_ativo):
    response = admin_client.get(reverse('admin:usuarios_user_changelist'), {'q': 'ativo@'})

    assert response.status_code == 200
    assert usuario_ativo.email in response.content.decode()


def test_criar_usuario_pelo_admin(admin_client):
    response = admin_client.post(reverse('admin:usuarios_user_add'), {
        'email': 'Novo@Scriba.com.br',
        'nome': 'Novo Usuário',
        'usable_password': 'true',
        'password1': 'Senha-Forte-Admin-1',
        'password2': 'Senha-Forte-Admin-1',
    })

    assert response.status_code == 302
    novo = User.objects.get(email='novo@scriba.com.br')
    assert novo.is_active
    assert novo.aprovado_em is not None


def test_admin_recusa_email_duplicado_com_caixa_diferente(admin_client, usuario_ativo):
    response = admin_client.post(reverse('admin:usuarios_user_add'), {
        'email': 'ATIVO@scriba.com.br',
        'nome': 'Duplicado',
        'usable_password': 'true',
        'password1': 'Senha-Forte-Admin-1',
        'password2': 'Senha-Forte-Admin-1',
    })

    assert response.status_code == 200
    assert 'email' in response.context['adminform'].form.errors
