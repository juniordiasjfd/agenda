from datetime import timedelta

import pytest
from axes.models import AccessAttempt
from django.contrib.auth import SESSION_KEY
from django.test import RequestFactory
from django.urls import reverse

from apps.usuarios.limite_login import email_da_tentativa, ip_do_cliente

URL_LOGIN = reverse('usuarios:login')
URL_HOME = reverse('painel:painel')
LIMITE = 3
IP_A = '203.0.113.10'
IP_B = '198.51.100.20'
# REMOTE_ADDR que o proxy do Render (balanceador) apresentaria ao gunicorn.
IP_PROXY = '10.0.0.5'


@pytest.fixture(autouse=True)
def _limite(settings):
    settings.AXES_FAILURE_LIMIT = LIMITE
    settings.AXES_COOLOFF_TIME = timedelta(minutes=15)
    settings.PROXY_COUNT = 1


def _entrar(client, email, senha, ip=IP_A, encaminhado=None):
    return client.post(
        URL_LOGIN, {'username': email, 'password': senha},
        REMOTE_ADDR=IP_PROXY,
        HTTP_X_FORWARDED_FOR=encaminhado if encaminhado is not None else ip,
    )


def _errar_ate_bloquear(client, email, **kwargs):
    respostas = [_entrar(client, email, 'senha-errada', **kwargs) for _ in range(LIMITE)]
    return respostas


# ---------------------------------------------------------------------------
# Bloqueio
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_bloqueia_ao_atingir_o_limite(client, usuario_ativo):
    respostas = _errar_ate_bloquear(client, usuario_ativo.email)

    assert [r.status_code for r in respostas[:-1]] == [200] * (LIMITE - 1)
    bloqueio = respostas[-1]
    assert bloqueio.status_code == 429
    conteudo = bloqueio.content.decode()
    assert 'Muitas tentativas de login' in conteudo
    assert f'depois de {LIMITE} tentativas sem sucesso' in conteudo
    assert 'bloqueado por\n    15 minutos' in conteudo


@pytest.mark.django_db
def test_bloqueado_nao_entra_nem_com_a_senha_certa(client, usuario_ativo, senha):
    _errar_ate_bloquear(client, usuario_ativo.email)

    resposta = _entrar(client, usuario_ativo.email, senha)

    assert resposta.status_code == 429
    assert SESSION_KEY not in client.session


@pytest.mark.django_db
def test_usuario_bloqueado_nao_bloqueia_os_demais_no_mesmo_ip(client, usuario_ativo, gestor, senha):
    _errar_ate_bloquear(client, usuario_ativo.email)

    resposta = _entrar(client, gestor.email, senha)

    assert resposta.status_code == 302
    assert resposta.url == URL_HOME
    assert client.session[SESSION_KEY] == str(gestor.pk)


@pytest.mark.django_db
def test_mesmo_usuario_em_outro_ip_nao_fica_bloqueado(client, usuario_ativo, senha):
    _errar_ate_bloquear(client, usuario_ativo.email, ip=IP_A)

    resposta = _entrar(client, usuario_ativo.email, senha, ip=IP_B)

    assert resposta.status_code == 302


@pytest.mark.django_db
def test_variar_a_caixa_do_email_nao_abre_nova_cota(client, usuario_ativo, senha):
    for email in ('ativo@scriba.com.br', 'ATIVO@Scriba.com.br', ' Ativo@SCRIBA.com.br '):
        _entrar(client, email, 'senha-errada')

    assert _entrar(client, usuario_ativo.email, senha).status_code == 429


@pytest.mark.django_db
def test_login_certo_zera_a_contagem(client, usuario_ativo, senha):
    for _ in range(LIMITE - 1):
        _entrar(client, usuario_ativo.email, 'senha-errada')
    assert _entrar(client, usuario_ativo.email, senha).status_code == 302
    client.post(reverse('usuarios:logout'))

    respostas = [_entrar(client, usuario_ativo.email, 'senha-errada') for _ in range(LIMITE - 1)]

    assert {r.status_code for r in respostas} == {200}


@pytest.mark.django_db
def test_libera_depois_do_tempo_de_bloqueio(client, usuario_ativo, senha):
    _errar_ate_bloquear(client, usuario_ativo.email)
    assert _entrar(client, usuario_ativo.email, senha).status_code == 429

    # Tempo controlado: as tentativas passam a ter 16 min (bloqueio de 15).
    for tentativa in AccessAttempt.objects.all():
        AccessAttempt.objects.filter(pk=tentativa.pk).update(
            attempt_time=tentativa.attempt_time - timedelta(minutes=16),
        )

    assert _entrar(client, usuario_ativo.email, senha).status_code == 302


@pytest.mark.django_db
def test_email_inexistente_tambem_e_limitado(client):
    respostas = _errar_ate_bloquear(client, 'ninguem@scriba.com.br')

    assert respostas[-1].status_code == 429


@pytest.mark.django_db
def test_pendente_com_senha_certa_nao_conta_como_falha(client, usuario_pendente, senha):
    for _ in range(LIMITE + 1):
        resposta = _entrar(client, usuario_pendente.email, senha)

    assert resposta.status_code == 200
    assert not AccessAttempt.objects.exists()


@pytest.mark.django_db
def test_login_do_admin_tambem_e_limitado(client, admin):
    url = reverse('admin:login')
    for _ in range(LIMITE):
        resposta = client.post(
            url, {'username': admin.email, 'password': 'senha-errada'},
            REMOTE_ADDR=IP_PROXY, HTTP_X_FORWARDED_FOR=IP_A,
        )

    assert resposta.status_code == 429


# ---------------------------------------------------------------------------
# IP real atrás do proxy
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_registra_o_ip_do_x_forwarded_for(client, usuario_ativo):
    _entrar(client, usuario_ativo.email, 'senha-errada', ip=IP_A)

    tentativa = AccessAttempt.objects.get()
    assert tentativa.ip_address == IP_A
    assert tentativa.username == 'ativo@scriba.com.br'


@pytest.mark.django_db
def test_inicio_forjado_do_x_forwarded_for_nao_escapa_do_bloqueio(client, usuario_ativo, senha):
    # O cliente inventa o começo do cabeçalho; o proxy acrescenta o IP real.
    for falso in ('1.1.1.1', '2.2.2.2', '3.3.3.3'):
        _entrar(client, usuario_ativo.email, 'senha-errada', encaminhado=f'{falso}, {IP_A}')

    resposta = _entrar(client, usuario_ativo.email, senha, encaminhado=f'4.4.4.4, {IP_A}')

    assert resposta.status_code == 429


def _requisicao(remoto='10.0.0.5', encaminhado=None):
    extra = {'REMOTE_ADDR': remoto}
    if encaminhado is not None:
        extra['HTTP_X_FORWARDED_FOR'] = encaminhado
    return RequestFactory().post('/entrar/', **extra)


@pytest.mark.parametrize('proxies, encaminhado, esperado', [
    (1, IP_A, IP_A),
    (1, f'1.1.1.1, {IP_A}', IP_A),
    (1, f' 1.1.1.1 ,{IP_A} ', IP_A),
    (2, f'{IP_A}, 172.16.0.1', IP_A),
    (1, '2001:db8::1', '2001:db8::1'),
    # Sem cabeçalho, curto demais, lixo ou proxy desligado: REMOTE_ADDR.
    (1, None, '10.0.0.5'),
    (2, IP_A, '10.0.0.5'),
    (1, 'não-é-ip', '10.0.0.5'),
    (0, IP_A, '10.0.0.5'),
])
def test_ip_do_cliente(settings, proxies, encaminhado, esperado):
    settings.PROXY_COUNT = proxies

    assert ip_do_cliente(_requisicao(encaminhado=encaminhado)) == esperado


def test_email_da_tentativa_normaliza():
    assert email_da_tentativa(None, {'username': '  Fulana@SCRIBA.com.br '}) == 'fulana@scriba.com.br'
    assert email_da_tentativa(_requisicao(), None) == ''
