"""Regras de negócio de ausências.

As views (etapa 5), o admin e a importação de CSV (etapa 6) só traduzem
entrada/saída; toda decisão fica aqui.
"""

import logging

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.ausencias.models import SituacaoAusencia

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Situação padrão
# ---------------------------------------------------------------------------
def situacao_padrao():
    """A situação marcada como padrão, ou ``None`` se não houver."""
    return SituacaoAusencia.objects.filter(padrao=True).first()


def validar_alteracao_situacao(atual, padrao, ativo):
    """Regras da situação padrão ao salvar uma situação. ``atual`` é a
    situação como está no banco (``None`` se nova); ``padrao``/``ativo`` são
    os valores pretendidos. ``ValidationError`` por campo.

    - a padrão não pode ficar inativa (nem nascer inativa);
    - a padrão não pode perder a flag: outra situação precisa assumir
      (marcar outra como padrão desmarca esta automaticamente).
    """
    erros = {}
    if padrao and not ativo:
        erros['ativo'] = 'A situação padrão não pode ser desativada. Marque outra situação como padrão antes.'
    if atual is not None and atual.padrao and not padrao:
        erros['padrao'] = (
            'Esta é a situação padrão. Para trocar, marque outra situação como '
            'padrão: esta será desmarcada automaticamente.'
        )
    if erros:
        raise ValidationError(erros)


def salvar_situacao(situacao, usuario):
    """Grava a situação com auditoria. Se ela vier marcada como padrão, a
    anterior é desmarcada na mesma transação (antes, por causa da constraint
    de padrão única)."""
    atual = SituacaoAusencia.objects.filter(pk=situacao.pk).first() if situacao.pk else None
    validar_alteracao_situacao(atual, situacao.padrao, situacao.ativo)
    with transaction.atomic():
        if situacao.padrao:
            _desmarcar_padrao(exceto=situacao)
        if situacao.pk is None:
            situacao.criado_por = usuario
        situacao.atualizado_por = usuario
        situacao.save()
    return situacao


def definir_situacao_padrao(situacao, usuario=None):
    """Torna ``situacao`` a padrão (desmarcando a anterior). Situação inativa
    não pode ser padrão (``ValidationError``)."""
    with transaction.atomic():
        situacao = SituacaoAusencia.objects.select_for_update().get(pk=situacao.pk)
        if not situacao.ativo:
            raise ValidationError('Situação inativa não pode ser a padrão. Ative-a antes.')
        if situacao.padrao:
            return situacao
        _desmarcar_padrao(exceto=situacao)
        situacao.padrao = True
        situacao.atualizado_por = usuario
        situacao.save(update_fields=['padrao', 'atualizado_por', 'atualizado_em'])
    logger.info('Situação padrão de ausência agora é "%s".', situacao.nome)
    return situacao


def _desmarcar_padrao(exceto):
    # select_for_update serializa duas trocas simultâneas de padrão.
    anteriores = SituacaoAusencia.objects.select_for_update().filter(padrao=True).exclude(pk=exceto.pk)
    for anterior in anteriores:
        anterior.padrao = False
        anterior.save(update_fields=['padrao', 'atualizado_em'])
