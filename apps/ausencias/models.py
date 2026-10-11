from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from apps.core.models import AuditoriaBase
from apps.core.utils import colapsar_espacos

REGEX_COR = r'^#[0-9A-Fa-f]{6}$'
validar_cor = RegexValidator(REGEX_COR, 'Informe a cor no formato hexadecimal #RRGGBB (ex.: #2f5fd0).')


class NomeUnicoMixin:
    """Nome com espaços colapsados e único sem diferença de maiúsculas (a
    constraint em ``Lower('nome')`` garante no banco; o ``clean`` põe a
    mensagem no campo)."""

    mensagem_nome_duplicado = 'Já existe um registro com este nome.'

    def _validar_nome_unico(self):
        self.nome = colapsar_espacos(self.nome)
        duplicados = type(self).objects.filter(nome__iexact=self.nome).exclude(pk=self.pk)
        if self.nome and duplicados.exists():
            raise ValidationError({'nome': self.mensagem_nome_duplicado})


class TipoAusencia(NomeUnicoMixin, AuditoriaBase):
    """Férias, Banco de horas... ``cor`` é a da barra no painel e da legenda.

    Em uso (há ausências com ele) não pode ser excluído (PROTECT): só
    inativado. Inativo não pode ser escolhido em registros novos.
    """
    nome = models.CharField(max_length=60, verbose_name='Nome')
    cor = models.CharField(max_length=7, validators=[validar_cor], verbose_name='Cor')
    ativo = models.BooleanField(default=True, verbose_name='Ativo')
    ordem = models.IntegerField(default=0, verbose_name='Ordem')

    mensagem_nome_duplicado = 'Já existe um tipo de ausência com este nome.'

    class Meta:
        verbose_name = 'tipo de ausência'
        verbose_name_plural = 'tipos de ausência'
        ordering = ['ordem', 'nome']
        constraints = [
            models.UniqueConstraint(
                Lower('nome'),
                name='ausencias_tipo_nome_ci_unico',
                violation_error_message='Já existe um tipo de ausência com este nome.',
            ),
            models.CheckConstraint(
                condition=Q(cor__regex=REGEX_COR),
                name='ausencias_tipo_cor_hex',
                violation_error_message='Cor inválida: use #RRGGBB.',
            ),
        ]

    def __str__(self):
        return self.nome

    def clean(self):
        super().clean()
        self._validar_nome_unico()

    def save(self, *args, **kwargs):
        self.nome = colapsar_espacos(self.nome)
        super().save(*args, **kwargs)


class SituacaoAusencia(NomeUnicoMixin, AuditoriaBase):
    """Planejado, Aprovado, Realizado, Cancelado...

    ``padrao``: no máximo uma (constraint condicional); é a usada quando o
    período não informa situação. Trocar a padrão passa por
    ``ausencias_service.definir_situacao_padrao``.
    ``conta_como_ausencia``: desmarcada, os períodos com esta situação somem
    do painel e não geram conflito de sobreposição.
    """
    nome = models.CharField(max_length=60, verbose_name='Nome')
    ativo = models.BooleanField(default=True, verbose_name='Ativo')
    ordem = models.IntegerField(default=0, verbose_name='Ordem')
    padrao = models.BooleanField(default=False, verbose_name='Padrão')
    conta_como_ausencia = models.BooleanField(default=True, verbose_name='Conta como ausência')

    mensagem_nome_duplicado = 'Já existe uma situação com este nome.'

    def validate_constraints(self, exclude=None):
        # Marcar uma nova padrão é válido: o serviço desmarca a anterior antes
        # de gravar. A constraint no banco continua garantindo a unicidade.
        super().validate_constraints(exclude={*(exclude or ()), 'padrao'})

    class Meta:
        verbose_name = 'situação de ausência'
        verbose_name_plural = 'situações de ausência'
        ordering = ['ordem', 'nome']
        constraints = [
            models.UniqueConstraint(
                Lower('nome'),
                name='ausencias_situacao_nome_ci_unico',
                violation_error_message='Já existe uma situação com este nome.',
            ),
            models.UniqueConstraint(
                fields=['padrao'],
                condition=Q(padrao=True),
                name='ausencias_situacao_padrao_unica',
                violation_error_message='Só pode haver uma situação padrão.',
            ),
        ]

    def __str__(self):
        return self.nome

    def clean(self):
        super().clean()
        self._validar_nome_unico()

    def save(self, *args, **kwargs):
        self.nome = colapsar_espacos(self.nome)
        super().save(*args, **kwargs)
