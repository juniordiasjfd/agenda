"""Regras de negócio de usuários: autocadastro, aprovação e convites.

As views só traduzem requisição/resposta; toda decisão fica aqui.
"""

import logging

from apps.usuarios.models import DominioAutocadastro, User

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domínios de autocadastro
# ---------------------------------------------------------------------------
def autocadastro_habilitado():
    """Habilitado somente se existir ao menos um domínio ativo."""
    return DominioAutocadastro.objects.filter(ativo=True).exists()


def dominio_do_email(email):
    """Parte após o último "@", em minúsculas; '' se não houver "@"."""
    email = User.objects.normalize_email(email)
    if '@' not in email:
        return ''
    return email.rpartition('@')[2]


def email_permitido(email):
    """O domínio do e-mail é IGUAL a um domínio ativo? Nunca por sufixo:
    ``x@sub.scriba.com.br`` e ``x@evilscriba.com.br`` não passam com
    ``scriba.com.br``."""
    dominio = dominio_do_email(email)
    if not dominio:
        return False
    return DominioAutocadastro.objects.filter(ativo=True, dominio=dominio).exists()
