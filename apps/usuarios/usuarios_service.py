"""Regras de negócio de usuários: autocadastro, aprovação e convites.

As views só traduzem requisição/resposta; toda decisão fica aqui.
"""

import logging
import uuid
from datetime import timedelta

from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.colaboradores.models import Colaborador
from apps.core.email_service import enviar_email
from apps.usuarios.models import Convite, DominioAutocadastro, User

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


class VinculoRecusado(Exception):
    """O colaborador escolhido não pode ser vinculado; a mensagem vai para o
    administrador e nada é alterado."""


def aprovar_usuario(usuario_id, url_login, colaborador_id=None, aprovado_por=None):
    """Ativa o pendente, grava ``aprovado_em``, põe no grupo Gestor e avisa o
    usuário por e-mail (``url_login``: link absoluto do login).

    Com ``colaborador_id``, vincula o usuário a esse colaborador na mesma
    transação, com o colaborador travado: se ele não existir, estiver inativo
    ou já tiver sido vinculado a outro usuário, ``VinculoRecusado`` e a
    aprovação NÃO acontece. ``aprovado_por`` fica como ``atualizado_por`` do
    colaborador.

    Idempotente: se já estiver aprovado e ativo, não altera nada (nem o
    vínculo) e devolve ``(usuario, False)``. Usuário desativado não é
    "reaprovado" por aqui (``UsuarioNaoPendente``) — reativar é no /admin/.
    ``User.DoesNotExist`` se o id não existir.
    """
    with transaction.atomic():
        usuario = User.objects.select_for_update().get(pk=usuario_id)
        if usuario.is_active and usuario.aprovado_em is not None:
            return usuario, False
        if not eh_pendente(usuario):
            raise UsuarioNaoPendente(usuario.email)
        colaborador = None
        if colaborador_id is not None:
            colaborador = Colaborador.objects.select_for_update().filter(pk=colaborador_id).first()
            if colaborador is None:
                raise VinculoRecusado('O colaborador escolhido não existe mais.')
            if not colaborador.ativo:
                raise VinculoRecusado(f'O colaborador "{colaborador.nome}" está inativo.')
            if colaborador.usuario_id is not None:
                raise VinculoRecusado(
                    f'O colaborador "{colaborador.nome}" já está vinculado a outro usuário.'
                )
        usuario.is_active = True
        usuario.aprovado_em = timezone.now()
        usuario.save(update_fields=['is_active', 'aprovado_em'])
        usuario.groups.add(Group.objects.get(name=NOME_GRUPO_GESTOR))
        if colaborador is not None:
            colaborador.usuario = usuario
            colaborador.atualizado_por = aprovado_por
            colaborador.save(update_fields=['usuario', 'atualizado_por', 'atualizado_em'])
    logger.info(
        'Cadastro aprovado: %s%s.', usuario.email,
        f' (vinculado ao colaborador "{colaborador.nome}")' if colaborador else '',
    )
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


# ---------------------------------------------------------------------------
# Convites
# ---------------------------------------------------------------------------
class ConviteInvalido(Exception):
    """Token inexistente, expirado ou já usado (a interface não diz qual)."""


class EmailJaCadastrado(Exception):
    """Já existe usuário com o e-mail do convite; o convite não é consumido."""


def _parse_token(token):
    try:
        return uuid.UUID(str(token))
    except (TypeError, ValueError):
        return None


def _colaborador_tomado(convite):
    """O colaborador do convite já foi vinculado a outro usuário?"""
    colaborador = convite.colaborador
    return colaborador is not None and colaborador.usuario_id is not None


def obter_convite_valido(token):
    """O convite pendente (não usado e não expirado) do token, ou ``None``.

    Também ``None`` se o colaborador do convite já tiver sido vinculado a outro
    usuário: o aceite seria recusado, então a página já mostra o aviso neutro.
    """
    token = _parse_token(token)
    if token is None:
        return None
    convite = Convite.objects.select_related('colaborador').filter(token=token).first()
    if convite is None or not convite.pendente or _colaborador_tomado(convite):
        return None
    return convite


def aceitar_convite(token, nome, senha):
    """Cria o usuário do convite (ativo, aprovado, Gestor), vincula ao
    colaborador do convite (se houver) e marca ``usado_em``.

    Tudo numa transação com o convite travado (``select_for_update``): dois
    aceites simultâneos do mesmo token são serializados e o segundo encontra o
    convite já usado (``ConviteInvalido``). Se o e-mail já tiver usuário,
    ``EmailJaCadastrado`` e o convite continua pendente.

    O colaborador também é travado: se ele já tiver sido vinculado a outro
    usuário nesse meio-tempo, ``ConviteInvalido`` SEM consumir o convite (a
    interface mostra a mesma página neutra) e o caso fica no log.
    """
    token = _parse_token(token)
    if token is None:
        raise ConviteInvalido()
    with transaction.atomic():
        convite = Convite.objects.select_for_update().filter(token=token).first()
        if convite is None or not convite.pendente:
            raise ConviteInvalido()
        colaborador = None
        if convite.colaborador_id is not None:
            colaborador = Colaborador.objects.select_for_update().get(pk=convite.colaborador_id)
            if colaborador.usuario_id is not None:
                logger.warning(
                    'Convite %s (%s) não aceito: o colaborador "%s" já está vinculado a outro usuário.',
                    convite.pk, convite.email, colaborador.nome,
                )
                raise ConviteInvalido()
        if User.objects.filter(email__iexact=convite.email).exists():
            raise EmailJaCadastrado(convite.email)
        try:
            with transaction.atomic():
                # Ativo => o UserManager já preenche aprovado_em.
                usuario = User.objects.create_user(convite.email, senha, nome=nome, is_active=True)
        except IntegrityError:
            raise EmailJaCadastrado(convite.email)
        usuario.groups.add(Group.objects.get(name=NOME_GRUPO_GESTOR))
        if colaborador is not None:
            colaborador.usuario = usuario
            colaborador.save(update_fields=['usuario', 'atualizado_em'])
        convite.usado_em = timezone.now()
        convite.save(update_fields=['usado_em', 'atualizado_em'])
    logger.info(
        'Convite aceito: %s%s.', usuario.email,
        f' (vinculado ao colaborador "{colaborador.nome}")' if colaborador else '',
    )
    return usuario


# ---------------------------------------------------------------------------
# Convites: gestão (só administrador)
# ---------------------------------------------------------------------------
VALIDADE_PADRAO_DIAS = 7


class ConviteRecusado(Exception):
    """Operação de convite não permitida; a mensagem vai para o usuário.
    ``campo``: campo do formulário a que o erro se refere (padrão: e-mail)."""

    def __init__(self, mensagem, campo='email'):
        super().__init__(mensagem)
        self.campo = campo


def _convites_pendentes():
    return Convite.objects.filter(usado_em__isnull=True, expira_em__gt=timezone.now())


def listar_convites():
    return Convite.objects.select_related('criado_por', 'colaborador').order_by('-criado_em', '-pk')


def criar_convite(email, validade_dias, criado_por, colaborador=None):
    """Cria convite para ``email`` válido por ``validade_dias``, opcionalmente
    para vincular a ``colaborador`` no aceite.

    Recusa (``ConviteRecusado``) e-mail que já tem usuário ou que já tem
    convite pendente não expirado; e colaborador inativo, já vinculado a um
    usuário ou que já tem convite pendente não expirado. Não depende dos
    domínios de autocadastro: o administrador pode convidar qualquer e-mail.
    """
    email = User.objects.normalize_email(email)
    if User.objects.filter(email__iexact=email).exists():
        raise ConviteRecusado('Já existe um usuário com este e-mail.')
    if _convites_pendentes().filter(email__iexact=email).exists():
        raise ConviteRecusado(
            'Já existe um convite pendente para este e-mail. Reenvie ou revogue o convite existente.'
        )
    with transaction.atomic():
        if colaborador is not None:
            # Travado: dois convites simultâneos para o mesmo colaborador são
            # serializados e o segundo vê o primeiro como pendente.
            colaborador = Colaborador.objects.select_for_update().get(pk=colaborador.pk)
            if not colaborador.ativo:
                raise ConviteRecusado('O colaborador escolhido está inativo.', campo='colaborador')
            if colaborador.usuario_id is not None:
                raise ConviteRecusado('O colaborador escolhido já está vinculado a um usuário.', campo='colaborador')
            if _convites_pendentes().filter(colaborador=colaborador).exists():
                raise ConviteRecusado(
                    'Já existe um convite pendente para este colaborador. Reenvie ou revogue o convite existente.',
                    campo='colaborador',
                )
        convite = Convite.objects.create(
            email=email,
            colaborador=colaborador,
            expira_em=timezone.now() + timedelta(days=validade_dias),
            criado_por=criado_por,
            atualizado_por=criado_por,
        )
    logger.info('Convite criado para %s por %s.', email, getattr(criado_por, 'email', None))
    return convite


def enviar_convite(convite, url_aceite):
    """Envia o link (absoluto) do convite por e-mail. Só convite pendente
    (senão ``ConviteInvalido``). Devolve se o envio deu certo; falha de SMTP
    não propaga."""
    if not convite.pendente:
        raise ConviteInvalido()
    return enviar_email(
        'usuarios/emails/convite_assunto.txt',
        'usuarios/emails/convite.txt',
        {'convite': convite, 'url_aceite': url_aceite},
        [convite.email],
    )


def revogar_convite(convite_id):
    """Exclui convite ainda não usado (pendente ou expirado). Convite usado
    fica como histórico (``ConviteRecusado``). Devolve o e-mail do convite."""
    with transaction.atomic():
        convite = Convite.objects.select_for_update().get(pk=convite_id)
        if convite.usado_em is not None:
            raise ConviteRecusado('Este convite já foi usado e não pode ser revogado.')
        email = convite.email
        convite.delete()
    logger.info('Convite revogado: %s.', email)
    return email
