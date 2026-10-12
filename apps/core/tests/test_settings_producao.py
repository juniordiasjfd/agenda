"""Settings de produção, carregados num subprocesso.

Dentro do pytest o bloco de produção fica desligado (TESTING), e os settings
são lidos uma vez só. Por isso cada cenário importa ``config.settings`` num
Python novo, com o ambiente controlado. Variáveis com valor vazio de propósito:
o ``load_dotenv`` não sobrescreve variável já definida, então o ``.env`` local
não interfere.
"""

import json
import os
import subprocess
import sys

from django.conf import settings

LER_SETTINGS = '''
import json
from django.conf import settings as s
print(json.dumps({
    'ALLOWED_HOSTS': s.ALLOWED_HOSTS,
    'CSRF_TRUSTED_ORIGINS': s.CSRF_TRUSTED_ORIGINS,
    'SECURE_SSL_REDIRECT': s.SECURE_SSL_REDIRECT,
    'SECURE_PROXY_SSL_HEADER': s.SECURE_PROXY_SSL_HEADER,
    'SESSION_COOKIE_SECURE': s.SESSION_COOKIE_SECURE,
    'CSRF_COOKIE_SECURE': s.CSRF_COOKIE_SECURE,
    'SECURE_HSTS_SECONDS': s.SECURE_HSTS_SECONDS,
    'CONN_MAX_AGE': s.DATABASES['default']['CONN_MAX_AGE'],
    'CONN_HEALTH_CHECKS': s.DATABASES['default']['CONN_HEALTH_CHECKS'],
    'NIVEL_APPS': s.LOGGING['loggers']['apps']['level'],
}))
'''

PRODUCAO = {
    'SECRET_KEY': 'chave-de-teste-' + 'x' * 50,
    'DEBUG': 'False',
    'ALLOWED_HOSTS': '',
    'CSRF_TRUSTED_ORIGINS': '',
    'RENDER_EXTERNAL_HOSTNAME': '',
    'HSTS_SECONDS': '',
    'SECURE_COOKIES': '',
    'LOG_LEVEL': '',
}


def _rodar(codigo, **variaveis):
    ambiente = {**os.environ, **PRODUCAO, **variaveis}
    ambiente['DJANGO_SETTINGS_MODULE'] = 'config.settings'
    ambiente['PYTHONIOENCODING'] = 'utf-8'
    return subprocess.run(
        [sys.executable, '-c', codigo], env=ambiente, cwd=settings.BASE_DIR,
        capture_output=True, encoding='utf-8', timeout=60,
    )


def _settings(**variaveis):
    processo = _rodar(LER_SETTINGS, **variaveis)
    assert processo.returncode == 0, processo.stderr
    return json.loads(processo.stdout)


def test_sem_secret_key_falha_em_producao():
    processo = _rodar(LER_SETTINGS, SECRET_KEY='', ALLOWED_HOSTS='agenda.onrender.com')

    assert processo.returncode != 0
    assert 'ImproperlyConfigured' in processo.stderr
    assert 'SECRET_KEY não está definida' in processo.stderr


def test_sem_host_falha_em_producao():
    processo = _rodar(LER_SETTINGS)

    assert processo.returncode != 0
    assert 'ALLOWED_HOSTS não está definida' in processo.stderr


def test_host_do_render_entra_em_hosts_e_origens():
    valores = _settings(RENDER_EXTERNAL_HOSTNAME='agenda.onrender.com')

    assert valores['ALLOWED_HOSTS'] == ['agenda.onrender.com']
    assert valores['CSRF_TRUSTED_ORIGINS'] == ['https://agenda.onrender.com']


def test_host_do_render_soma_com_as_variaveis_sem_duplicar():
    valores = _settings(
        RENDER_EXTERNAL_HOSTNAME='agenda.onrender.com',
        ALLOWED_HOSTS='agenda.scriba.com.br, agenda.onrender.com',
        CSRF_TRUSTED_ORIGINS='https://agenda.scriba.com.br',
    )

    assert valores['ALLOWED_HOSTS'] == ['agenda.scriba.com.br', 'agenda.onrender.com']
    assert valores['CSRF_TRUSTED_ORIGINS'] == [
        'https://agenda.scriba.com.br', 'https://agenda.onrender.com',
    ]


def test_seguranca_padrao_de_producao():
    valores = _settings(ALLOWED_HOSTS='agenda.onrender.com')

    assert valores['SECURE_SSL_REDIRECT'] is False
    assert valores['SECURE_PROXY_SSL_HEADER'] == ['HTTP_X_FORWARDED_PROTO', 'https']
    assert valores['SESSION_COOKIE_SECURE'] is True
    assert valores['CSRF_COOKIE_SECURE'] is True
    assert valores['SECURE_HSTS_SECONDS'] == 300
    assert valores['CONN_MAX_AGE'] == 60
    assert valores['CONN_HEALTH_CHECKS'] is True
    assert valores['NIVEL_APPS'] == 'INFO'


def test_hsts_e_nivel_de_log_por_variavel():
    valores = _settings(
        ALLOWED_HOSTS='agenda.onrender.com', HSTS_SECONDS='31536000', LOG_LEVEL='debug',
    )

    assert valores['SECURE_HSTS_SECONDS'] == 31536000
    assert valores['NIVEL_APPS'] == 'DEBUG'
