from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from apps.colaboradores.models import Colaborador
from apps.core.models import AuditoriaBase, SoftDeleteMixin
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


class Ausencia(SoftDeleteMixin, AuditoriaBase):
    """Cabeçalho de um envio: um colaborador, um tipo e um ou mais períodos.

    ``codigo`` é o SolicitacaoID do CSV: gerado por
    ``ausencias_service.gerar_codigo`` (8 caracteres) ou, na importação, o ID
    legado (até 32). Exclusão lógica pelo ``SoftDeleteMixin``: ``objects``
    oculta as excluídas, ``todos`` inclui. Gravar sempre pelo serviço, que
    valida a sobreposição.
    """
    colaborador = models.ForeignKey(
        Colaborador,
        on_delete=models.PROTECT,
        related_name='ausencias',
        verbose_name='Colaborador',
    )
    tipo = models.ForeignKey(
        TipoAusencia,
        on_delete=models.PROTECT,
        related_name='ausencias',
        verbose_name='Tipo',
    )
    observacoes = models.TextField(blank=True, verbose_name='Observações')
    codigo = models.CharField(
        max_length=32,
        unique=True,
        verbose_name='Código',
        error_messages={'unique': 'Já existe uma ausência com este código.'},
    )

    class Meta:
        verbose_name = 'ausência'
        verbose_name_plural = 'ausências'
        ordering = ['-criado_em']
        # O índice em colaborador é o da própria FK (db_index).

    def __str__(self):
        return f'{self.codigo} — {self.titulo}'

    @property
    def titulo(self):
        """"Colaborador - Tipo" (coluna Titulo do CSV)."""
        return f'{self.colaborador} - {self.tipo}'

    # Usam ``periodos.all()``: com ``prefetch_related`` não consultam o banco.
    @property
    def total_dias(self):
        return sum(periodo.dias for periodo in self.periodos.all())

    @property
    def situacoes(self):
        """Situações dos períodos, sem repetir, na ordem em que aparecem."""
        return list(dict.fromkeys(periodo.situacao for periodo in self.periodos.all()))


class PeriodoAusencia(AuditoriaBase):
    """Intervalo de datas de uma ausência, com fim INCLUSIVO (10 a 10 = 1 dia).

    A sobreposição com outros períodos do mesmo colaborador é verificada no
    serviço (``ausencias_service.validar_periodos``), não no banco.
    """
    ausencia = models.ForeignKey(
        Ausencia,
        on_delete=models.CASCADE,
        related_name='periodos',
        verbose_name='Ausência',
    )
    data_inicio = models.DateField(verbose_name='Início')
    data_fim = models.DateField(verbose_name='Fim')
    situacao = models.ForeignKey(
        SituacaoAusencia,
        on_delete=models.PROTECT,
        related_name='periodos',
        verbose_name='Situação',
    )

    class Meta:
        verbose_name = 'período'
        verbose_name_plural = 'períodos'
        ordering = ['data_inicio', 'data_fim', 'pk']
        # O índice em ausencia é o da própria FK (db_index).
        indexes = [
            models.Index(fields=['data_inicio', 'data_fim'], name='ausencias_periodo_datas_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(data_fim__gte=models.F('data_inicio')),
                name='ausencias_periodo_fim_apos_inicio',
                violation_error_message='A data de fim deve ser igual ou posterior à de início.',
            ),
        ]

    def __str__(self):
        return f'{self.data_inicio:%d/%m/%Y} a {self.data_fim:%d/%m/%Y}'

    @property
    def dias(self):
        """Dias corridos, contando início e fim."""
        return (self.data_fim - self.data_inicio).days + 1
