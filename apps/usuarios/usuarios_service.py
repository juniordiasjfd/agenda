"""Regras de negócio de usuários: autocadastro, aprovação e convites.

As views só traduzem requisição/resposta; toda decisão fica aqui.
"""

import logging

from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, transaction

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


# ---------------------------------------------------------------------------
# Autocadastro
# ---------------------------------------------------------------------------
class EmailNaoPermitido(Exception):
    """E-mail fora dos domínios ativos (ou autocadastro desligado)."""


def registrar_autocadastro(nome, email, senha):
    """Cria o usuário pendente (inativo, sem ``aprovado_em``, sem grupo).

    Devolve o usuário criado, ou ``None`` se o e-mail já existia (qualquer
    caixa). Quem chama dá a MESMA resposta nos dois casos, para não revelar
    quem tem conta. O hash da senha é gerado sempre, para o tempo de resposta
    também não denunciar o e-mail existente.
    """
    email = User.objects.normalize_email(email)
    if not email_permitido(email):
        raise EmailNaoPermitido(email)

    senha_hash = make_password(senha)
    if User.objects.filter(email__iexact=email).exists():
        logger.info('Autocadastro ignorado: e-mail já cadastrado (%s).', email)
        return None
    try:
        with transaction.atomic():
            usuario = User.objects.create(
                email=email, nome=nome, password=senha_hash, is_active=False, aprovado_em=None,
            )
    except IntegrityError:
        # Corrida com outro cadastro do mesmo e-mail: mesma resposta neutra.
        logger.info('Autocadastro ignorado: e-mail já cadastrado (%s).', email)
        return None
    logger.info('Autocadastro recebido: %s aguardando aprovação.', email)
    return usuario
