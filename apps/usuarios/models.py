from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone


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
