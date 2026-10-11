import re
import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from apps.core.models import AuditoriaBase


class UserManager(BaseUserManager):
    use_in_migrations = True

    @classmethod
    def normalize_email(cls, email):
        """E-mail inteiro em minúsculas e sem espaços nas pontas (o padrão do
        Django só baixa o domínio)."""
        return (email or '').strip().lower()

    def get_by_natural_key(self, email):
        # Login sem diferença de maiúsculas: o e-mail gravado já é minúsculo.
        return self.get(**{self.model.USERNAME_FIELD: self.normalize_email(email)})

    def _create_user(self, email, password, **extra_fields):
        email = self.normalize_email(email)
        if not email:
            raise ValueError('Informe o e-mail.')
        # Usuário criado já ativo é, por definição, aprovado. Quem cria um
        # usuário pendente (autocadastro) passa is_active=False e fica sem
        # aprovado_em.
        if extra_fields.get('is_active', True):
            extra_fields.setdefault('aprovado_em', timezone.now())
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('aprovado_em', timezone.now())

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superusuário precisa ter is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superusuário precisa ter is_superuser=True.')
        if extra_fields.get('is_active') is not True:
            raise ValueError('Superusuário precisa ter is_active=True.')

        return self._create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """Usuário do sistema, identificado pelo e-mail.

    Não herda AuditoriaBase (FKs para o próprio User criariam referência
    circular); usa campos de data próprios.

    Situação de acesso:
      is_active=True                          -> pode entrar
      is_active=False e aprovado_em nulo      -> aguardando aprovação
      is_active=False e aprovado_em preenchido -> desativado
    """
    email = models.EmailField(
        unique=True,
        verbose_name='E-mail',
        error_messages={'unique': 'Já existe um usuário com este e-mail.'},
    )
    nome = models.CharField(max_length=150, verbose_name='Nome')
    is_active = models.BooleanField(
        default=True,
        verbose_name='Ativo',
        help_text='Desmarque para bloquear o acesso sem apagar o usuário.',
    )
    is_staff = models.BooleanField(
        default=False,
        verbose_name='Acesso ao admin',
        help_text='Permite entrar no site de administração do Django.',
    )
    aprovado_em = models.DateTimeField(null=True, blank=True, verbose_name='Aprovado em')
    date_joined = models.DateTimeField(default=timezone.now, verbose_name='Cadastrado em')

    objects = UserManager()

    EMAIL_FIELD = 'email'
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['nome']

    class Meta:
        verbose_name = 'usuário'
        verbose_name_plural = 'usuários'
        ordering = ['nome', 'email']
        constraints = [
            # unique=True no campo continua (o Django exige no USERNAME_FIELD);
            # esta garante no banco que não haja o mesmo e-mail com caixa
            # diferente, mesmo que alguém grave sem passar pela normalização.
            models.UniqueConstraint(
                Lower('email'),
                name='usuarios_user_email_ci_unico',
                violation_error_message='Já existe um usuário com este e-mail.',
            ),
        ]

    def __str__(self):
        return self.nome or self.email

    def clean(self):
        super().clean()
        self.email = self.__class__.objects.normalize_email(self.email)

    def save(self, *args, **kwargs):
        self.email = self.__class__.objects.normalize_email(self.email)
        super().save(*args, **kwargs)

    def get_full_name(self):
        return self.nome or self.email

    def get_short_name(self):
        return (self.nome.split()[0] if self.nome.strip() else self.email)

    @property
    def aguardando_aprovacao(self):
        return not self.is_active and self.aprovado_em is None

    @property
    def eh_gestor(self):
        """Gestor ou administrador: cria, edita, exclui e restaura ausências."""
        # Import tardio: core.permissions carrega auth.mixins, que precisa
        # do AUTH_USER_MODEL já registrado.
        from apps.core.permissions import eh_gestor
        return eh_gestor(self)


# ---------------------------------------------------------------------------
# Autocadastro
# ---------------------------------------------------------------------------
# Rótulos de 1 a 63 caracteres (letras, dígitos e hífen, sem hífen nas
# pontas), ao menos um ponto e TLD só de letras. Aplicado ao valor já
# normalizado (minúsculas).
DOMINIO_RE = re.compile(r'^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$')


def normalizar_dominio(valor):
    """Minúsculas, sem espaços e sem "@" inicial: ' @Scriba.com.br ' -> 'scriba.com.br'."""
    return ''.join((valor or '').split()).lower().lstrip('@')


class DominioAutocadastro(AuditoriaBase):
    """Domínio de e-mail autorizado a fazer autocadastro.

    O autocadastro só fica habilitado se houver ao menos um domínio ativo, e o
    e-mail só é aceito se o domínio (parte após o último "@") for IGUAL a um
    domínio ativo — nunca por sufixo. Ver ``usuarios_service.email_permitido``.
    """
    dominio = models.CharField(
        max_length=253,
        unique=True,
        verbose_name='Domínio',
        help_text='Ex.: scriba.com.br (sem "@"). Só e-mails exatamente deste domínio são aceitos; subdomínios não.',
        error_messages={'unique': 'Este domínio já está cadastrado.'},
    )
    ativo = models.BooleanField(default=True, verbose_name='Ativo')

    class Meta:
        verbose_name = 'domínio de autocadastro'
        verbose_name_plural = 'domínios de autocadastro'
        ordering = ['dominio']

    def __str__(self):
        return self.dominio

    def clean(self):
        super().clean()
        self.dominio = normalizar_dominio(self.dominio)
        if not DOMINIO_RE.match(self.dominio):
            raise ValidationError({'dominio': 'Informe um domínio válido, por exemplo: scriba.com.br.'})

    def save(self, *args, **kwargs):
        self.dominio = normalizar_dominio(self.dominio)
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Convite
# ---------------------------------------------------------------------------
class Convite(AuditoriaBase):
    """Convite do administrador: quem aceita vira usuário ativo, aprovado e
    Gestor, com o e-mail do convite. Regras em ``usuarios_service``."""
    PENDENTE = 'pendente'
    USADO = 'usado'
    EXPIRADO = 'expirado'
    ROTULOS_ESTADO = {PENDENTE: 'Pendente', USADO: 'Usado', EXPIRADO: 'Expirado'}

    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, verbose_name='Token')
    email = models.EmailField(verbose_name='E-mail do convidado')
    expira_em = models.DateTimeField(verbose_name='Expira em')
    usado_em = models.DateTimeField(null=True, blank=True, verbose_name='Usado em')
    colaborador = models.ForeignKey(
        'colaboradores.Colaborador',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='convites',
        verbose_name='Colaborador',
        help_text='Se informado, o usuário criado no aceite fica vinculado a este colaborador.',
    )

    class Meta:
        verbose_name = 'convite'
        verbose_name_plural = 'convites'
        ordering = ['-criado_em']

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        self.email = User.objects.normalize_email(self.email)
        super().save(*args, **kwargs)

    @property
    def estado(self):
        if self.usado_em is not None:
            return self.USADO
        if self.expira_em <= timezone.now():
            return self.EXPIRADO
        return self.PENDENTE

    @property
    def estado_rotulo(self):
        return self.ROTULOS_ESTADO[self.estado]

    @property
    def pendente(self):
        return self.estado == self.PENDENTE
