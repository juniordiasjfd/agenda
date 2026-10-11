"""Regras de negócio de departamentos e colaboradores.

As views só traduzem requisição/resposta; toda decisão fica aqui.
"""

import json
import logging
import re
from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import Count

from apps.colaboradores.models import Colaborador, Departamento
from apps.core.utils import colapsar_espacos, normalizar_nome
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


def alterar_departamento(colaborador_id, departamento_id, usuario):
    """Troca só o departamento (edição rápida na lista). ``departamento_id``
    vazio/``None`` = sem departamento. ``Colaborador.DoesNotExist`` ou
    ``Departamento.DoesNotExist`` se algum id não existir."""
    departamento = Departamento.objects.get(pk=departamento_id) if departamento_id else None
    colaborador = Colaborador.objects.select_related('usuario').get(pk=colaborador_id)
    colaborador.departamento = departamento
    colaborador.atualizado_por = usuario
    colaborador.save(update_fields=['departamento', 'atualizado_por', 'atualizado_em'])
    return colaborador


def alterar_ativo(colaborador_id, ativo, usuario):
    """Ativa ou desativa (nunca exclui). ``Colaborador.DoesNotExist`` se o id
    não existir."""
    colaborador = Colaborador.objects.get(pk=colaborador_id)
    colaborador.ativo = ativo
    colaborador.atualizado_por = usuario
    colaborador.save(update_fields=['ativo', 'atualizado_por', 'atualizado_em'])
    logger.info('Colaborador %s %s.', colaborador.nome, 'ativado' if ativo else 'desativado')
    return colaborador



# ---------------------------------------------------------------------------
# Carga inicial (comando carregar_colaboradores)
# ---------------------------------------------------------------------------
class ArquivoNomesInvalido(Exception):
    """O conteúdo não tem um array de nomes reconhecível."""


# String JavaScript entre aspas duplas (com escapes), sem quebra de linha.
_RE_STRING = r'"(?:[^"\\\n]|\\.)*"'
# Primeiro array: strings ou qualquer coisa que não seja "]" nem aspas.
_RE_ARRAY = re.compile(r'\[((?:' + _RE_STRING + r'|[^\]"])*)\]')


def ler_nomes_js(texto):
    """Extrai os nomes de um arquivo no formato ``legado/referencias/funcionarios.js``
    (``window.FUNCIONARIOS = [ "Nome", ... ];``) SEM executar JavaScript.

    Ignora linhas de comentário (``//``) e BOM e tolera vírgula final. Cada
    string é decodificada com ``json.loads`` (escapes como ``\u00e9``). Só
    aceita strings entre aspas duplas separadas por vírgulas; qualquer outra
    coisa dentro do array é ``ArquivoNomesInvalido``.
    """
    texto = texto.lstrip('\ufeff')
    linhas = [linha for linha in texto.splitlines() if not linha.lstrip().startswith('//')]
    achado = _RE_ARRAY.search('\n'.join(linhas))
    if achado is None:
        raise ArquivoNomesInvalido('Nenhum array de nomes ([ "Nome", ... ]) encontrado no arquivo.')
    conteudo = achado.group(1)
    sobra = re.sub(_RE_STRING, '', conteudo)
    if sobra.replace(',', '').strip():
        raise ArquivoNomesInvalido(
            'O array tem conteúdo que não é nome entre aspas duplas: '
            f'{sobra.replace(",", " ").split()[0][:40]!r}.'
        )
    nomes = []
    for literal in re.findall(_RE_STRING, conteudo):
        try:
            nomes.append(json.loads(literal))
        except json.JSONDecodeError:
            raise ArquivoNomesInvalido(f'Nome com escape inválido: {literal[:60]}.')
    return nomes


@dataclass
class ResultadoCarga:
    lidos: int = 0
    criados: list = field(default_factory=list)
    existentes: list = field(default_factory=list)
    duplicados: list = field(default_factory=list)
    vazios: int = 0


def carregar_colaboradores(nomes, dry_run=False):
    """Cria os colaboradores que ainda não existem (por ``nome_normalizado``),
    ativos e sem departamento. Nunca altera nem apaga os existentes.

    Espaços são colapsados, vazios descartados e repetidos no próprio arquivo
    (mesmo nome normalizado) contados em ``duplicados`` (fica o primeiro).
    Tudo numa transação; com ``dry_run`` nada é gravado, mas o resultado é o
    mesmo que seria.
    """
    resultado = ResultadoCarga(lidos=len(nomes))
    unicos = {}
    for bruto in nomes:
        nome = colapsar_espacos(bruto)
        if not nome:
            resultado.vazios += 1
            continue
        chave = normalizar_nome(nome)
        if chave in unicos:
            resultado.duplicados.append(nome)
            continue
        unicos[chave] = nome

    with transaction.atomic():
        ja_existem = set(
            Colaborador.objects.select_for_update()
            .filter(nome_normalizado__in=unicos).values_list('nome_normalizado', flat=True)
        )
        for chave, nome in unicos.items():
            if chave in ja_existem:
                resultado.existentes.append(nome)
                continue
            if not dry_run:
                Colaborador.objects.create(nome=nome, ativo=True, departamento=None)
            resultado.criados.append(nome)
    if not dry_run:
        logger.info('Carga de colaboradores: %d criados.', len(resultado.criados))
    return resultado
