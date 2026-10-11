"""Regras de negócio de departamentos e colaboradores.

As views só traduzem requisição/resposta; toda decisão fica aqui.
"""

import logging

from django.db import transaction
from django.db.models import Count

from apps.colaboradores.models import Departamento

logger = logging.getLogger(__name__)


def _gravar_com_auditoria(objeto, usuario):
    """Salva preenchendo ``criado_por`` (se novo) e ``atualizado_por``."""
    if objeto.pk is None:
        objeto.criado_por = usuario
    objeto.atualizado_por = usuario
    objeto.save()
    return objeto


# ---------------------------------------------------------------------------
# Departamentos
# ---------------------------------------------------------------------------
class DepartamentoEmUso(Exception):
    """Departamento com colaboradores (ativos ou não) não pode ser excluído."""


def listar_departamentos():
    """Todos, com ``total_colaboradores`` (inclui inativos)."""
    return Departamento.objects.annotate(total_colaboradores=Count('colaboradores'))


def salvar_departamento(departamento, usuario):
    return _gravar_com_auditoria(departamento, usuario)


def excluir_departamento(departamento_id):
    """Exclui o departamento SÓ se não tiver colaboradores; senão
    ``DepartamentoEmUso`` e nada é apagado. Devolve o nome excluído.

    O ``on_delete=PROTECT`` de ``Colaborador.departamento`` continua como
    trava no banco caso alguém vincule um colaborador ao mesmo tempo.
    """
    with transaction.atomic():
        departamento = Departamento.objects.select_for_update().get(pk=departamento_id)
        if departamento.colaboradores.exists():
            raise DepartamentoEmUso(departamento.nome)
        nome = departamento.nome
        departamento.delete()
    logger.info('Departamento excluído: %s.', nome)
    return nome
