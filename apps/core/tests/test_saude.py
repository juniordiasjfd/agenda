import pytest
from django.conf import settings
from django.db import OperationalError


# ---------------------------------------------------------------------------
# /saude/ (liveness, SaudeMiddleware)
# ---------------------------------------------------------------------------
def test_middleware_e_o_primeiro_da_lista():
    assert settings.MIDDLEWARE[0] == 'apps.core.middleware.SaudeMiddleware'


def test_saude_responde_ok_sem_login_e_sem_banco(client):
    # Sem marcador django_db: se a rota tocasse o banco, o pytest-django
    # falharia o teste.
    resposta = client.get('/saude/')

    assert resposta.status_code == 200
    assert resposta.content == b'ok'
    assert resposta['Cache-Control'] == 'no-store'
    assert 'Set-Cookie' not in resposta


def test_saude_ignora_validacao_de_host(client, settings):
    # O healthcheck do Render chega pelo IP interno, fora do ALLOWED_HOSTS.
    settings.ALLOWED_HOSTS = ['agenda.onrender.com']

    resposta = client.get('/saude/', HTTP_HOST='10.0.0.7:10000')

    assert resposta.status_code == 200
    assert resposta.content == b'ok'


def test_host_invalido_continua_barrado_nas_demais_rotas(client, settings):
    settings.ALLOWED_HOSTS = ['agenda.onrender.com']

    resposta = client.get('/saude/banco/', HTTP_HOST='10.0.0.7:10000')

    assert resposta.status_code == 400


def test_so_o_caminho_exato(client):
    # /saude/qualquer-coisa não é liveness: segue o fluxo normal (404).
    assert client.get('/saude/x/').status_code == 404


# ---------------------------------------------------------------------------
# /saude/banco/ (readiness)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_saude_banco_ok_sem_login(client):
    resposta = client.get('/saude/banco/')

    assert resposta.status_code == 200
    assert resposta.content == b'ok'
    assert 'no-cache' in resposta['Cache-Control']


@pytest.mark.django_db
def test_saude_banco_indisponivel_devolve_503_sem_detalhe(client, monkeypatch, caplog):
    class ConexaoFora:
        def cursor(self):
            raise OperationalError('senha errada para o usuário agenda')

    monkeypatch.setattr('apps.core.views.connection', ConexaoFora())

    resposta = client.get('/saude/banco/')

    assert resposta.status_code == 503
    assert b'senha' not in resposta.content
    assert 'Healthcheck do banco falhou' in caplog.text


@pytest.mark.django_db
def test_saude_banco_recusa_post(client):
    assert client.post('/saude/banco/').status_code == 405
