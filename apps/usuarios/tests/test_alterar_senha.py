import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

URL_ALTERAR = reverse('usuarios:password_change')
URL_CONCLUIDO = reverse('usuarios:password_change_done')
NOVA_SENHA = 'Outra-Senha-Forte-77'


@pytest.mark.parametrize('url', [URL_ALTERAR, URL_CONCLUIDO])
def test_exige_login(client, url):
    response = client.get(url)

    assert response.status_code == 302
    assert response.url.startswith(reverse('usuarios:login'))


def test_alterar_senha(client, usuario_ativo, senha):
    client.force_login(usuario_ativo)
    assert client.get(URL_ALTERAR).status_code == 200

    response = client.post(URL_ALTERAR, {
        'old_password': senha, 'new_password1': NOVA_SENHA, 'new_password2': NOVA_SENHA,
    })

    assert response.status_code == 302
    assert response.url == URL_CONCLUIDO
    usuario_ativo.refresh_from_db()
    assert usuario_ativo.check_password(NOVA_SENHA)
    # A sessão continua válida depois da troca.
    assert client.get(reverse('painel:painel')).status_code == 200


def test_senha_atual_errada(client, usuario_ativo, senha):
    client.force_login(usuario_ativo)

    response = client.post(URL_ALTERAR, {
        'old_password': 'errada', 'new_password1': NOVA_SENHA, 'new_password2': NOVA_SENHA,
    })

    assert response.status_code == 200
    assert response.context['form'].errors['old_password']
    usuario_ativo.refresh_from_db()
    assert usuario_ativo.check_password(senha)


def test_senha_fraca_recusada(client, usuario_ativo, senha):
    client.force_login(usuario_ativo)

    response = client.post(URL_ALTERAR, {
        'old_password': senha, 'new_password1': 'abc', 'new_password2': 'abc',
    })

    assert response.status_code == 200
    assert response.context['form'].errors['new_password2']
