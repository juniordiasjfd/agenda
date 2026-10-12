"""Configuração do gunicorn (lida automaticamente da raiz do projeto).

Start no Render: ``gunicorn config.wsgi``. Tudo vem do ambiente:
- PORT: injetada pelo Render;
- WEB_CONCURRENCY: número de workers (padrão 2; Starter tem 512 MB);
- GUNICORN_TIMEOUT: segundos até matar um worker travado (padrão 30).
"""

import os

bind = f"0.0.0.0:{os.getenv('PORT') or '8000'}"
workers = int(os.getenv('WEB_CONCURRENCY') or 2)
timeout = int(os.getenv('GUNICORN_TIMEOUT') or 30)
# Erros do gunicorn no stderr (coletado pelo Render). Sem access log: o Render
# já registra as requisições, e o healthcheck encheria o log a cada poucos
# segundos.
errorlog = '-'
