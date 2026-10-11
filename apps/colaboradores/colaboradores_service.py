"""Regras de negócio de departamentos e colaboradores.

As views só traduzem requisição/resposta; toda decisão fica aqui.
"""

import logging

from django.db import transaction
from django.db.models import Count

from apps.colaboradores.models import Colaborador, Departamento
from apps.core.utils import normalizar_nome
from apps.usuarios.models import User

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


# ---------------------------------------------------------------------------
# Colaboradores
# ---------------------------------------------------------------------------
# Valor do filtro de departamento que seleciona quem não tem departamento.
SEM_DEPARTAMENTO = 'sem'

SITUACAO_ATIVOS = 'ativos'
SITUACAO_INATIVOS = 'inativos'
SITUACAO_TODOS = 'todos'


def filtrar_colaboradores(busca='', departamento='', situacao=SITUACAO_ATIVOS):
    """Lista do administrador.

    ``busca``: trecho do nome, sem considerar acentos, maiúsculas e espaços
    duplos (compara com ``nome_normalizado``). ``departamento``: id,
    ``SEM_DEPARTAMENTO`` ou vazio (todos). ``situacao``: ativos, inativos ou
    todos.
    """
    colaboradores = Colaborador.objects.select_related('departamento', 'usuario')
    termo = normalizar_nome(busca)
    if termo:
        colaboradores = colaboradores.filter(nome_normalizado__contains=termo)
    if departamento == SEM_DEPARTAMENTO:
        colaboradores = colaboradores.filter(departamento__isnull=True)
    elif departamento:
        colaboradores = colaboradores.filter(departamento_id=departamento)
    if situacao == SITUACAO_ATIVOS:
        colaboradores = colaboradores.filter(ativo=True)
    elif situacao == SITUACAO_INATIVOS:
        colaboradores = colaboradores.filter(ativo=False)
    return colaboradores


def contar_sem_departamento():
    """Colaboradores ATIVOS sem departamento (cadastro a completar)."""
    return Colaborador.objects.filter(ativo=True, departamento__isnull=True).count()


def usuarios_vinculaveis(atual=None):
    """Usuários que podem ser vinculados a um colaborador: ativos e ainda sem
    colaborador, mais ``atual`` (o já vinculado, na edição)."""
    usuarios = User.objects.filter(is_active=True, colaborador__isnull=True)
    if atual is not None:
        usuarios = usuarios | User.objects.filter(pk=atual.pk)
    return usuarios.order_by('nome', 'email')


def salvar_colaborador(colaborador, usuario):
    return _gravar_com_auditoria(colaborador, usuario)


def alterar_ativo(colaborador_id, ativo, usuario):
    """Ativa ou desativa (nunca exclui). ``Colaborador.DoesNotExist`` se o id
    não existir."""
    colaborador = Colaborador.objects.get(pk=colaborador_id)
    colaborador.ativo = ativo
    colaborador.atualizado_por = usuario
    colaborador.save(update_fields=['ativo', 'atualizado_por', 'atualizado_em'])
    logger.info('Colaborador %s %s.', colaborador.nome, 'ativado' if ativo else 'desativado')
    return colaborador
