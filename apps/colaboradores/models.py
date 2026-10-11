from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower

from apps.core.models import AuditoriaBase
from apps.core.utils import colapsar_espacos, normalizar_nome


class Departamento(AuditoriaBase):
    """Departamento do colaborador. Nome único sem diferença de maiúsculas.

    Só pode ser excluído sem colaboradores (``Colaborador.departamento`` é
    PROTECT; a tela verifica antes em ``colaboradores_service``).
    """
    nome = models.CharField(max_length=100, verbose_name='Nome')

    class Meta:
        verbose_name = 'departamento'
        verbose_name_plural = 'departamentos'
        ordering = [Lower('nome')]
        constraints = [
            models.UniqueConstraint(
                Lower('nome'),
                name='colaboradores_departamento_nome_ci_unico',
                violation_error_message='Já existe um departamento com este nome.',
            ),
        ]

    def __str__(self):
        return self.nome

    def clean(self):
        super().clean()
        self.nome = colapsar_espacos(self.nome)
        # Mensagem no campo (a constraint daria erro geral do formulário).
        duplicados = Departamento.objects.filter(nome__iexact=self.nome).exclude(pk=self.pk)
        if self.nome and duplicados.exists():
            raise ValidationError({'nome': 'Já existe um departamento com este nome.'})

    def save(self, *args, **kwargs):
        self.nome = colapsar_espacos(self.nome)
        super().save(*args, **kwargs)


class Colaborador(AuditoriaBase):
    """Pessoa que registra ausências. Nunca é excluído pela interface: só
    ativado/desativado (``ativo``); inativo some do formulário e do painel.

    ``nome`` guarda o texto exibido (espaços colapsados, caixa e acentos
    preservados). ``nome_normalizado`` (sem acento, minúsculo) é a chave
    única: "José  Silva" e "jose silva" são o mesmo colaborador.
    """
    nome = models.CharField(max_length=150, verbose_name='Nome')
    nome_normalizado = models.CharField(
        max_length=150,
        unique=True,
        editable=False,
        verbose_name='Nome normalizado',
        error_messages={'unique': 'Já existe um colaborador com este nome.'},
    )
    departamento = models.ForeignKey(
        Departamento,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='colaboradores',
        verbose_name='Departamento',
    )
    ativo = models.BooleanField(default=True, verbose_name='Ativo')
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='colaborador',
        verbose_name='Usuário vinculado',
        error_messages={'unique': 'Este usuário já está vinculado a outro colaborador.'},
    )

    class Meta:
        verbose_name = 'colaborador'
        verbose_name_plural = 'colaboradores'
        ordering = ['nome_normalizado']

    def __str__(self):
        return self.nome

    def _normalizar(self):
        self.nome = colapsar_espacos(self.nome)
        self.nome_normalizado = normalizar_nome(self.nome)

    def clean(self):
        super().clean()
        self._normalizar()
        # nome_normalizado não é campo de formulário (editable=False), então o
        # validate_unique do ModelForm não o verifica: a checagem fica aqui,
        # com a mensagem no campo "nome".
        duplicados = Colaborador.objects.filter(nome_normalizado=self.nome_normalizado).exclude(pk=self.pk)
        if self.nome_normalizado and duplicados.exists():
            raise ValidationError({
                'nome': 'Já existe um colaborador com este nome (sem considerar acentos, maiúsculas e espaços).',
            })

    def save(self, *args, **kwargs):
        self._normalizar()
        update_fields = kwargs.get('update_fields')
        if update_fields is not None and 'nome' in update_fields:
            kwargs['update_fields'] = {*update_fields, 'nome_normalizado'}
        super().save(*args, **kwargs)
