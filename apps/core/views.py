import logging

from django.db import connection
from django.http import HttpResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe
from django.views.generic import RedirectView

logger = logging.getLogger(__name__)


class HomeView(RedirectView):
    """A página inicial é o painel de ausências (que exige login)."""
    pattern_name = 'painel:painel'


@never_cache
@require_safe
def saude_banco(request):
    """Readiness: 200 "ok" se o banco responde a ``SELECT 1``, senão 503.

    Sem login. O corpo nunca traz o erro (a rota é pública); o detalhe vai
    para o log. A liveness (``/saude/``) é respondida pelo SaudeMiddleware.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except Exception:
        logger.exception('Healthcheck do banco falhou.')
        return HttpResponse('indisponivel', status=503, content_type='text/plain; charset=utf-8')
    return HttpResponse('ok', content_type='text/plain; charset=utf-8')
