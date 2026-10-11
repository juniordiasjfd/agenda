from datetime import timedelta

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from apps.usuarios import usuarios_service
from apps.usuarios.models import Convite

pytestmark = pytest.mark.django_db

URL_CONVITES = reverse('usuarios:convites')
URL_LOGIN = reverse('usuarios:login')


def _novo_convite(email='convidada@exemplo.com', dias=7, usado=False):
    return Convite.objects.create(
        email=email,
        expira_em=timezone.now() + timedelta(days=dias),
        usado_em=timezone.now() if usado else None,
    )


def _criar(client, email='Convidada@Exemplo.com', validade=7, enviar=False):
    dados = {'email': email, 'validade_dias': validade}
    if enviar:
        dados['enviar_por_email'] = 'on'
    return client.post(URL_CONVITES, dados)


def _link(convite):
    return f"http://testserver{reverse('usuarios:convite_aceitar', args=[convite.token])}"


def _mensagens(response):
    return [str(m) for m in response.wsgi_request._messages]


@pytest.fixture
def admin_client(client, admin):
    client.force_login(admin)
    return client


# ---------------------------------------------------------------------------
# Acesso
# ---------------------------------------------------------------------------
def _rotas(convite):
    return [
        ('get', URL_CONVITES),
        ('post', URL_CONVITES),
        ('get', reverse('usuarios:convite_detalhe', args=[convite.pk])),
        ('post', reverse('usuarios:convite_reenviar', args=[convite.pk])),
        ('post', reverse('usuarios:convite_revogar', args=[convite.pk])),
    ]


def test_anonimo_vai_para_login(client):
    convite = _novo_convite()

    for metodo, url in _rotas(convite):
        response = getattr(client, metodo)(url)
        assert response.status_code == 302
        assert response.url.startswith(URL_LOGIN)
    assert Convite.objects.filter(pk=convite.pk).exists()


def test_gestor_recebe_403(client, gestor):
    convite = _novo_convite()
    client.force_login(gestor)

    for metodo, url in _rotas(convite):
        assert getattr(client, metodo)(url).status_code == 403
    assert Convite.objects.filter(pk=convite.pk).exists()
    assert mail.outbox == []


def test_admin_ve_a_lista_com_estados(admin_client):
    _novo_convite('p@x.com')
    _novo_convite('e@x.com', dias=-1)
    _novo_convite('u@x.com', usado=True)

    response = admin_client.get(URL_CONVITES)

    assert response.status_code == 200
    conteudo = response.content.decode()
    for texto in ('p@x.com', 'e@x.com', 'u@x.com', 'Pendente', 'Expirado', 'Usado'):
        assert texto in conteudo
    # Validade padrão: 7 dias.
    assert response.context['form']['validade_dias'].value() == 7


@pytest.mark.parametrize('rota', ['convite_reenviar', 'convite_revogar'])
def test_acoes_so_por_post(admin_client, rota):
    convite = _novo_convite()

    assert admin_client.get(reverse(f'usuarios:{rota}', args=[convite.pk])).status_code == 405


# ---------------------------------------------------------------------------
# Criação
# ---------------------------------------------------------------------------
def test_criar_convite_sem_enviar(admin_client, admin):
    response = _criar(admin_client)

    convite = Convite.objects.get()
    assert response.status_code == 302
    assert response.url == reverse('usuarios:convite_detalhe', args=[convite.pk])
    assert convite.email == 'convidada@exemplo.com'
    assert convite.criado_por == admin
    assert convite.usado_em is None
    assert convite.pendente
    esperado = timezone.now() + timedelta(days=7)
    assert abs((convite.expira_em - esperado).total_seconds()) < 60
    assert mail.outbox == []


def test_detalhe_mostra_link_completo_para_copiar(admin_client):
    convite = _novo_convite()

    response = admin_client.get(reverse('usuarios:convite_detalhe', args=[convite.pk]))

    conteudo = response.content.decode()
    assert _link(convite) in conteudo
    assert 'Copiar' in conteudo


def test_detalhe_de_convite_usado_nao_mostra_link(admin_client):
    convite = _novo_convite(usado=True)

    response = admin_client.get(reverse('usuarios:convite_detalhe', args=[convite.pk]))

    assert _link(convite) not in response.content.decode()


def test_criar_convite_com_validade_e_envio(admin_client):
    _criar(admin_client, validade=3, enviar=True)

    convite = Convite.objects.get()
    esperado = timezone.now() + timedelta(days=3)
    assert abs((convite.expira_em - esperado).total_seconds()) < 60
    assert len(mail.outbox) == 1
    mensagem = mail.outbox[0]
    assert mensagem.to == ['convidada@exemplo.com']
    assert 'convite' in mensagem.subject
    assert _link(convite) in mensagem.body


@pytest.mark.parametrize('validade', [0, 91, ''])
def test_validade_fora_do_intervalo(admin_client, validade):
    response = _criar(admin_client, validade=validade)

    assert response.status_code == 200
    assert response.context['form'].errors['validade_dias']
    assert not Convite.objects.exists()


def test_nao_cria_para_email_com_usuario(admin_client, usuario_ativo):
    response = _criar(admin_client, email='ATIVO@scriba.com.br')

    assert response.status_code == 200
    assert response.context['form'].errors['email'] == ['Já existe um usuário com este e-mail.']
    assert not Convite.objects.exists()


def test_nao_cria_para_email_de_usuario_pendente(admin_client, usuario_pendente):
    response = _criar(admin_client, email=usuario_pendente.email)

    assert response.context['form'].errors['email'] == ['Já existe um usuário com este e-mail.']


def test_nao_cria_com_convite_pendente(admin_client):
    _novo_convite()

    response = _criar(admin_client, email='CONVIDADA@exemplo.com')

    assert response.status_code == 200
    assert 'Já existe um convite pendente' in response.context['form'].errors['email'][0]
    assert Convite.objects.count() == 1


@pytest.mark.parametrize('kwargs', [{'dias': -1}, {'usado': True}])
def test_cria_se_o_anterior_expirou_ou_foi_usado(admin_client, kwargs):
    # "usado" sem usuário existente: ex. o usuário foi apagado depois.
    _novo_convite(**kwargs)

    response = _criar(admin_client)

    assert response.status_code == 302
    assert Convite.objects.count() == 2


def test_convite_ignora_dominios_de_autocadastro(admin_client):
    response = _criar(admin_client, email='externa@gmail.com')

    assert response.status_code == 302
    assert Convite.objects.filter(email='externa@gmail.com').exists()


def test_falha_de_smtp_na_criacao_mantem_convite(admin_client, monkeypatch):
    def explode(*args, **kwargs):
        raise ConnectionRefusedError('SMTP fora do ar')

    monkeypatch.setattr('apps.core.email_service.send_mail', explode)

    response = _criar(admin_client, enviar=True)

    assert response.status_code == 302
    assert Convite.objects.exists()
    assert any('Não foi possível enviar' in m for m in _mensagens(response))


# ---------------------------------------------------------------------------
# Reenviar e revogar
# ---------------------------------------------------------------------------
def test_reenviar_pendente(admin_client):
    convite = _novo_convite()

    response = admin_client.post(reverse('usuarios:convite_reenviar', args=[convite.pk]))

    assert response.status_code == 302
    assert len(mail.outbox) == 1
    assert _link(convite) in mail.outbox[0].body


@pytest.mark.parametrize('kwargs', [{'dias': -1}, {'usado': True}])
def test_nao_reenvia_expirado_nem_usado(admin_client, kwargs):
    convite = _novo_convite(**kwargs)

    response = admin_client.post(reverse('usuarios:convite_reenviar', args=[convite.pk]))

    assert response.status_code == 302
    assert mail.outbox == []
    assert 'Só é possível enviar convites pendentes.' in _mensagens(response)


def test_reenviar_inexistente_404(admin_client):
    assert admin_client.post(reverse('usuarios:convite_reenviar', args=[999999])).status_code == 404


@pytest.mark.parametrize('kwargs', [{}, {'dias': -1}])
def test_revogar_convite_nao_usado(admin_client, client, kwargs):
    convite = _novo_convite(**kwargs)

    response = admin_client.post(reverse('usuarios:convite_revogar', args=[convite.pk]))

    assert response.status_code == 302
    assert response.url == URL_CONVITES
    assert not Convite.objects.filter(pk=convite.pk).exists()


def test_link_revogado_deixa_de_funcionar(admin_client, client):
    convite = _novo_convite()
    admin_client.post(reverse('usuarios:convite_revogar', args=[convite.pk]))
    admin_client.logout()

    response = client.get(reverse('usuarios:convite_aceitar', args=[convite.token]))

    assert 'Este link de convite não é válido.' in response.content.decode()


def test_nao_revoga_convite_usado(admin_client):
    convite = _novo_convite(usado=True)

    response = admin_client.post(reverse('usuarios:convite_revogar', args=[convite.pk]))

    assert response.status_code == 302
    assert Convite.objects.filter(pk=convite.pk).exists()
    assert 'já foi usado' in _mensagens(response)[0]


def test_revogar_inexistente_404(admin_client):
    assert admin_client.post(reverse('usuarios:convite_revogar', args=[999999])).status_code == 404


def test_service_enviar_convite_recusa_nao_pendente():
    with pytest.raises(usuarios_service.ConviteInvalido):
        usuarios_service.enviar_convite(_novo_convite(usado=True), 'http://testserver/x/')


# ---------------------------------------------------------------------------
# Fluxo completo: criar -> e-mail -> aceitar -> login
# ---------------------------------------------------------------------------
def test_fluxo_convite_ate_o_login(admin_client, client):
    _criar(admin_client, enviar=True)
    convite = Convite.objects.get()
    assert _link(convite) in mail.outbox[0].body
    admin_client.logout()

    senha_nova = 'Convite-Forte-2026!'
    response = client.post(
        reverse('usuarios:convite_aceitar', args=[convite.token]),
        {'nome': 'Convidada', 'password1': senha_nova, 'password2': senha_nova},
    )
    assert response.url == URL_LOGIN

    response = client.post(URL_LOGIN, {'username': 'convidada@exemplo.com', 'password': senha_nova})
    assert response.status_code == 302
    assert response.url == reverse('core:home')
