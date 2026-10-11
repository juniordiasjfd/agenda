import threading
from datetime import timedelta

import pytest
from django.db import connection
from django.urls import reverse
from django.utils import timezone

from apps.usuarios import usuarios_service
from apps.usuarios.models import Convite, User

URL_LOGIN = reverse('usuarios:login')
SENHA_NOVA = 'Convite-Forte-2026!'
TEXTO_NEUTRO = 'Este link de convite não é válido.'


def _url(convite_ou_token):
    token = getattr(convite_ou_token, 'token', convite_ou_token)
    return reverse('usuarios:convite_aceitar', args=[token])


def _dados(**extra):
    dados = {'nome': 'Convidada  Nova', 'password1': SENHA_NOVA, 'password2': SENHA_NOVA}
    dados.update(extra)
    return dados


def _novo_convite(email='convidada@exemplo.com', dias=7, usado=False):
    return Convite.objects.create(
        email=email,
        expira_em=timezone.now() + timedelta(days=dias),
        usado_em=timezone.now() if usado else None,
    )


@pytest.fixture
def convite(db):
    return _novo_convite()


# ---------------------------------------------------------------------------
# Estado
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_estado_do_convite():
    assert _novo_convite('a@x.com').estado == Convite.PENDENTE
    assert _novo_convite('b@x.com', dias=-1).estado == Convite.EXPIRADO
    assert _novo_convite('c@x.com', usado=True).estado == Convite.USADO
    # Usado prevalece sobre expirado.
    assert _novo_convite('d@x.com', dias=-1, usado=True).estado_rotulo == 'Usado'


@pytest.mark.django_db
def test_email_do_convite_normalizado():
    assert _novo_convite(' Fulana@Exemplo.COM ').email == 'fulana@exemplo.com'


@pytest.mark.django_db
def test_token_gerado_e_unico():
    a, b = _novo_convite('a@x.com'), _novo_convite('b@x.com')
    assert a.token and b.token and a.token != b.token


# ---------------------------------------------------------------------------
# Página pública
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_convite_valido_mostra_formulario_com_email(client, convite):
    response = client.get(_url(convite))

    assert response.status_code == 200
    conteudo = response.content.decode()
    assert 'convidada@exemplo.com' in conteudo
    assert 'readonly' in conteudo
    assert 'email' not in response.context['form'].fields


@pytest.mark.django_db
@pytest.mark.parametrize('caso', ['inexistente', 'malformado', 'expirado', 'usado'])
def test_token_invalido_resposta_neutra_e_identica(client, caso):
    tokens = {
        'inexistente': '6f1c2b8e-0000-4000-8000-000000000000',
        'malformado': 'nao-e-um-uuid',
        'expirado': _novo_convite('e@x.com', dias=-1).token,
        'usado': _novo_convite('u@x.com', usado=True).token,
    }

    for metodo in (client.get, client.post):
        response = metodo(_url(tokens[caso]), _dados() if metodo == client.post else None)
        assert response.status_code == 200
        assert response.templates[0].name == 'usuarios/convite_invalido.html'
        assert TEXTO_NEUTRO in response.content.decode()
    assert not User.objects.filter(nome='Convidada Nova').exists()


@pytest.mark.django_db
def test_aceitar_cria_usuario_ativo_aprovado_gestor(client, convite):
    response = client.post(_url(convite), _dados())

    assert response.status_code == 302
    assert response.url == URL_LOGIN
    usuario = User.objects.get(email='convidada@exemplo.com')
    assert usuario.nome == 'Convidada Nova'
    assert usuario.is_active
    assert usuario.aprovado_em is not None
    assert list(usuario.groups.values_list('name', flat=True)) == ['Gestor']
    assert not usuario.is_staff and not usuario.is_superuser
    convite.refresh_from_db()
    assert convite.usado_em is not None
    assert convite.estado == Convite.USADO


@pytest.mark.django_db
def test_aceitar_nao_loga_e_permite_entrar(client, convite):
    response = client.post(_url(convite), _dados(), follow=True)

    assert not response.context['user'].is_authenticated
    assert 'Conta criada!' in response.content.decode()
    response = client.post(URL_LOGIN, {'username': 'convidada@exemplo.com', 'password': SENHA_NOVA})
    assert response.status_code == 302


@pytest.mark.django_db
def test_segundo_uso_do_token_falha(client, convite):
    client.post(_url(convite), _dados())

    response = client.post(_url(convite), _dados(nome='Outra Pessoa'))

    assert TEXTO_NEUTRO in response.content.decode()
    assert User.objects.filter(email='convidada@exemplo.com').count() == 1
    assert User.objects.get(email='convidada@exemplo.com').nome == 'Convidada Nova'


@pytest.mark.django_db
def test_email_no_post_e_ignorado(client, convite):
    client.post(_url(convite), _dados(email='intrusa@scriba.com.br'))

    assert User.objects.filter(email='convidada@exemplo.com').exists()
    assert not User.objects.filter(email='intrusa@scriba.com.br').exists()


@pytest.mark.django_db
def test_email_que_passou_a_existir_nao_consome_convite(client, convite, senha):
    # A página abre com o convite válido; antes do aceite alguém cria a conta.
    assert client.get(_url(convite)).status_code == 200
    User.objects.create_user('Convidada@Exemplo.com', senha, nome='Já Existe')

    response = client.post(_url(convite), _dados())

    assert response.status_code == 200
    assert 'Já existe uma conta com este e-mail' in response.context['form'].non_field_errors()[0]
    convite.refresh_from_db()
    assert convite.usado_em is None
    assert User.objects.get(email='convidada@exemplo.com').nome == 'Já Existe'


@pytest.mark.django_db
@pytest.mark.parametrize('senha_fraca', ['123', 'password123', 'convidadanova'])
def test_senha_fraca_recusada(client, convite, senha_fraca):
    response = client.post(_url(convite), _dados(password1=senha_fraca, password2=senha_fraca))

    assert response.status_code == 200
    assert response.context['form'].errors['password2']
    convite.refresh_from_db()
    assert convite.usado_em is None


@pytest.mark.django_db
def test_usuario_logado_e_redirecionado(client, convite, usuario_ativo):
    client.force_login(usuario_ativo)

    response = client.post(_url(convite), _dados())

    assert response.status_code == 302
    assert response.url == reverse('core:home')
    convite.refresh_from_db()
    assert convite.usado_em is None


@pytest.mark.django_db
def test_service_token_invalido():
    with pytest.raises(usuarios_service.ConviteInvalido):
        usuarios_service.aceitar_convite('xyz', 'Nome', SENHA_NOVA)


# ---------------------------------------------------------------------------
# Concorrência: dois aceites simultâneos do mesmo token
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_aceites_simultaneos_criam_um_usuario_so():
    convite = _novo_convite()
    barreira = threading.Barrier(2)
    resultados = []

    def aceitar(nome):
        try:
            barreira.wait(timeout=5)
            usuarios_service.aceitar_convite(convite.token, nome, SENHA_NOVA)
            resultados.append('ok')
        except usuarios_service.ConviteInvalido:
            resultados.append('invalido')
        except usuarios_service.EmailJaCadastrado:
            resultados.append('email')
        finally:
            connection.close()

    threads = [threading.Thread(target=aceitar, args=(f'Pessoa {i}',)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert sorted(resultados) == ['invalido', 'ok']
    assert User.objects.filter(email='convidada@exemplo.com').count() == 1
