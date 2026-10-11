"""Envio de e-mail tolerante a falha.

Ponto único de envio dos e-mails do sistema. O envio nunca pode quebrar o
fluxo de quem chamou: qualquer exceção (SMTP fora do ar, timeout, template com
erro) é registrada com ``logger.exception`` e a função devolve ``False``.
"""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def enviar_email(assunto_template, corpo_template, contexto, destinatarios):
    """Renderiza assunto e corpo (texto simples) e envia aos destinatários.

    ``assunto_template``/``corpo_template`` são caminhos de template; o assunto
    é reduzido a uma linha. Devolve ``True`` se o envio foi aceito pelo backend
    e ``False`` se não havia destinatário ou se houve falha (já registrada em
    log).
    """
    destinatarios = [email for email in destinatarios if email]
    if not destinatarios:
        return False
    try:
        assunto = ' '.join(render_to_string(assunto_template, contexto).split())
        corpo = render_to_string(corpo_template, contexto)
        send_mail(assunto, corpo, settings.DEFAULT_FROM_EMAIL, destinatarios)
    except Exception:
        logger.exception(
            'Falha ao enviar e-mail (%s) para %s.', corpo_template, ', '.join(destinatarios),
        )
        return False
    return True
