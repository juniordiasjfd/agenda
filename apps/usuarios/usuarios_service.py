"""Regras de negócio de usuários: autocadastro, aprovação e convites.

As views só traduzem requisição/resposta; toda decisão fica aqui.
"""

import logging

from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.email_service import enviar_email
from apps.usuarios.models import DominioAutocadastro, User

logger = logging.getLogger(__name__)

NOME_GRUPO_GESTOR = 'Gestor'


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


def registrar_autocadastro(nome, email, senha, url_pendentes):
    """Cria o usuário pendente (inativo, sem ``aprovado_em``, sem grupo) e
    avisa os administradores (``url_pendentes``: link absoluto da tela).

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
    notificar_admins_pendencia(usuario, url_pendentes)
    return usuario


def notificar_admins_pendencia(usuario, url_pendentes):
    """E-mail aos superusers ativos com e-mail. Tolerante a falha."""
    destinatarios = list(
        User.objects.filter(is_superuser=True, is_active=True).exclude(email='').values_list('email', flat=True)
    )
    return enviar_email(
        'usuarios/emails/novo_cadastro_pendente_assunto.txt',
        'usuarios/emails/novo_cadastro_pendente.txt',
        {'usuario': usuario, 'url_pendentes': url_pendentes},
        destinatarios,
    )


# ---------------------------------------------------------------------------
# Cadastros pendentes (só administrador)
# ---------------------------------------------------------------------------
class UsuarioNaoPendente(Exception):
    """O usuário não está (mais) aguardando aprovação."""


def eh_pendente(usuario):
    """Pendente = inativo, sem ``aprovado_em`` e não superuser."""
    return not usuario.is_active and usuario.aprovado_em is None and not usuario.is_superuser


def _pendentes():
    return User.objects.filter(is_active=False, aprovado_em__isnull=True, is_superuser=False)


def listar_pendentes():
    return _pendentes().order_by('date_joined', 'pk')


def contar_pendentes():
    return _pendentes().count()


def aprovar_usuario(usuario_id, url_login):
    """Ativa o pendente, grava ``aprovado_em``, põe no grupo Gestor e avisa o
    usuário por e-mail (``url_login``: link absoluto do login).

    Idempotente: se já estiver aprovado e ativo, não altera nada e devolve
    ``(usuario, False)``. Usuário desativado não é "reaprovado" por aqui
    (``UsuarioNaoPendente``) — reativar é no /admin/. ``User.DoesNotExist`` se
    o id não existir.
    """
    with transaction.atomic():
        usuario = User.objects.select_for_update().get(pk=usuario_id)
        if usuario.is_active and usuario.aprovado_em is not None:
            return usuario, False
        if not eh_pendente(usuario):
            raise UsuarioNaoPendente(usuario.email)
        usuario.is_active = True
        usuario.aprovado_em = timezone.now()
        usuario.save(update_fields=['is_active', 'aprovado_em'])
        usuario.groups.add(Group.objects.get(name=NOME_GRUPO_GESTOR))
    logger.info('Cadastro aprovado: %s.', usuario.email)
    enviar_email(
        'usuarios/emails/cadastro_aprovado_assunto.txt',
        'usuarios/emails/cadastro_aprovado.txt',
        {'usuario': usuario, 'url_login': url_login},
        [usuario.email],
    )
    return usuario, True


def rejeitar_usuario(usuario_id):
    """Exclui o usuário — SÓ se ainda for pendente; senão
    ``UsuarioNaoPendente`` e nada é apagado. Devolve o e-mail excluído."""
    with transaction.atomic():
        usuario = User.objects.select_for_update().get(pk=usuario_id)
        if not eh_pendente(usuario):
            raise UsuarioNaoPendente(usuario.email)
        email = usuario.email
        usuario.delete()
    logger.info('Cadastro rejeitado e excluído: %s.', email)
    return email
