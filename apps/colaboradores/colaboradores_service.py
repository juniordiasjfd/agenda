"""Regras de negócio de departamentos e colaboradores.

As views só traduzem requisição/resposta; toda decisão fica aqui.
"""

import csv
import io
import json
import logging
import re
from dataclasses import dataclass, field

from django.conf import settings
from django.db import transaction
from django.db.models import Count

from apps.colaboradores.models import Colaborador, Departamento
from apps.core.csv_utils import decodificar, desfazer_neutralizacao, detectar_separador
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


def colaboradores_vinculaveis():
    """Colaboradores que podem receber um usuário (convite ou aprovação):
    ativos e ainda sem usuário."""
    return Colaborador.objects.filter(ativo=True, usuario__isnull=True)


def colaborador_por_nome(nome):
    """O único colaborador vinculável (ativo e sem usuário) cujo nome
    normalizado é igual ao de ``nome``, ou ``None``. Usado para pré-selecionar
    o vínculo na aprovação: só sugere, nunca vincula.

    Como ``nome_normalizado`` é único, há no máximo um homônimo; se ele estiver
    inativo ou já vinculado, não há sugestão.
    """
    chave = normalizar_nome(nome)
    if not chave:
        return None
    candidatos = list(colaboradores_vinculaveis().filter(nome_normalizado=chave)[:2])
    return candidatos[0] if len(candidatos) == 1 else None


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


# ---------------------------------------------------------------------------
# Importação por CSV (tela do administrador)
# ---------------------------------------------------------------------------
EXTENSOES_CSV = ('.csv', '.txt')
TAMANHO_NOME_COLABORADOR = Colaborador._meta.get_field('nome').max_length
TAMANHO_NOME_DEPARTAMENTO = Departamento._meta.get_field('nome').max_length

# Cabeçalho normalizado (sem acento, caixa e símbolos) -> coluna.
_ALIASES_CSV = {'colaborador': 'Colaborador', 'nome': 'Colaborador', 'departamento': 'Departamento'}


class ArquivoColaboradoresInvalido(Exception):
    """Arquivo recusado inteiro (extensão, tamanho, codificação, colunas)."""


@dataclass
class LinhaColaborador:
    """Uma linha de dados do CSV. ``linha``: posição no arquivo (cabeçalho
    = 1). ``departamento`` vazio = sem departamento."""
    linha: int
    nome: str
    departamento: str = ''


def ler_csv_colaboradores(enviado):
    """Lê o CSV ``Colaborador;Departamento`` de um arquivo enviado (objeto
    com ``name``, ``size`` e ``read()``).

    Mesmas regras de leitura da importação de ausências: ``;`` ou ``,``,
    UTF-8 ou Windows-1252, limites ``CSV_IMPORTACAO_MAX_BYTES`` e
    ``CSV_IMPORTACAO_MAX_REGISTROS``, apóstrofo anti-fórmula desfeito. A
    coluna Departamento é opcional; linhas totalmente vazias são descartadas.
    Problema no arquivo inteiro = ``ArquivoColaboradoresInvalido``.
    """
    if not enviado.name.lower().endswith(EXTENSOES_CSV):
        raise ArquivoColaboradoresInvalido('Extensão não aceita: envie um arquivo .csv ou .txt.')
    max_bytes = settings.CSV_IMPORTACAO_MAX_BYTES
    if enviado.size > max_bytes:
        raise ArquivoColaboradoresInvalido(f'Arquivo maior que {max_bytes / (1024 * 1024):g} MB.')
    texto, _codificacao = decodificar(enviado.read())
    if texto is None:
        raise ArquivoColaboradoresInvalido('Codificação não reconhecida: salve o arquivo em UTF-8 ou Windows-1252.')
    if not texto.strip():
        raise ArquivoColaboradoresInvalido('O arquivo está vazio.')
    try:
        tabela = list(csv.reader(io.StringIO(texto, newline=''), delimiter=detectar_separador(texto), quotechar='"'))
    except csv.Error as erro:
        raise ArquivoColaboradoresInvalido(f'O arquivo não é um CSV válido ({erro}).')

    indices = {}
    for indice, titulo in enumerate(tabela[0]):
        coluna = _ALIASES_CSV.get(re.sub(r'[^a-z0-9]', '', normalizar_nome(titulo)))
        if coluna and coluna not in indices:
            indices[coluna] = indice
    if 'Colaborador' not in indices:
        raise ArquivoColaboradoresInvalido('Falta a coluna obrigatória: Colaborador.')

    max_registros = settings.CSV_IMPORTACAO_MAX_REGISTROS
    linhas = []
    for posicao, valores in enumerate(tabela[1:], start=2):
        if not any(valor.strip() for valor in valores):
            continue
        if len(linhas) == max_registros:
            raise ArquivoColaboradoresInvalido(
                f'O arquivo tem mais de {max_registros} registros: divida-o em arquivos menores.'
            )
        lidos = {
            coluna: desfazer_neutralizacao(valores[indice]) if indice < len(valores) else ''
            for coluna, indice in indices.items()
        }
        linhas.append(LinhaColaborador(
            linha=posicao,
            nome=colapsar_espacos(lidos['Colaborador']),
            departamento=colapsar_espacos(lidos.get('Departamento')),
        ))
    if not linhas:
        raise ArquivoColaboradoresInvalido('O arquivo não tem linhas de dados.')
    return linhas


@dataclass
class ItemImportacao:
    """Uma linha no resumo. ``departamento``/``anterior``: nome ou vazio
    (= sem departamento)."""
    linha: int
    nome: str
    departamento: str = ''
    anterior: str = ''
    motivo: str = ''


@dataclass
class ResultadoImportacao:
    simulado: bool
    lidos: int = 0
    criados: list = field(default_factory=list)
    atualizados: list = field(default_factory=list)
    sem_alteracao: list = field(default_factory=list)
    duplicados: list = field(default_factory=list)
    invalidos: list = field(default_factory=list)
    departamentos_criados: list = field(default_factory=list)


def _motivo_invalida(linha):
    if not linha.nome:
        return 'Colaborador não informado.'
    if len(linha.nome) > TAMANHO_NOME_COLABORADOR:
        return f'Nome do colaborador com mais de {TAMANHO_NOME_COLABORADOR} caracteres.'
    if len(linha.departamento) > TAMANHO_NOME_DEPARTAMENTO:
        return f'Nome do departamento com mais de {TAMANHO_NOME_DEPARTAMENTO} caracteres.'
    return ''


def importar_colaboradores(linhas, usuario, simular=True):
    """Aplica as linhas lidas do CSV (``LinhaColaborador``).

    - Colaborador novo (por ``nome_normalizado``): criado ativo, com o
      departamento da linha; departamento vazio = sem departamento.
    - Colaborador existente (ativo ou não): se a linha traz departamento
      diferente do atual, o departamento é trocado; departamento vazio NÃO
      apaga o atual. Nome e ``ativo`` nunca são alterados.
    - Departamento inexistente (comparação sem diferença de maiúsculas, como
      a constraint): criado, só se alguma linha aplicada o usa.
    - Nome repetido no arquivo: vale a primeira linha; as demais vão para
      ``duplicados``. Linha sem nome ou com nome longo demais: ``invalidos``.

    Tudo numa transação, com os colaboradores existentes travados. Com
    ``simular`` nada é gravado, mas o resultado é o mesmo que seria.
    """
    resultado = ResultadoImportacao(simulado=simular, lidos=len(linhas))
    unicas = {}
    for linha in linhas:
        motivo = _motivo_invalida(linha)
        if motivo:
            resultado.invalidos.append(ItemImportacao(linha.linha, linha.nome, linha.departamento, motivo=motivo))
            continue
        chave = normalizar_nome(linha.nome)
        if chave in unicas:
            resultado.duplicados.append(ItemImportacao(
                linha.linha, linha.nome, linha.departamento,
                motivo=f'Repete o nome da linha {unicas[chave].linha}.',
            ))
            continue
        unicas[chave] = linha

    with transaction.atomic():
        existentes = {
            colaborador.nome_normalizado: colaborador
            for colaborador in Colaborador.objects.select_for_update().filter(nome_normalizado__in=unicas)
        }
        departamentos = {departamento.nome.lower(): departamento for departamento in Departamento.objects.all()}
        nome_do_departamento = {departamento.pk: departamento.nome for departamento in departamentos.values()}

        def departamento_de(nome):
            """O departamento de ``nome`` (criado se preciso) ou ``None``."""
            if not nome:
                return None
            chave = nome.lower()
            if chave not in departamentos:
                novo = Departamento(nome=nome)
                if not simular:
                    _gravar_com_auditoria(novo, usuario)
                departamentos[chave] = novo
                resultado.departamentos_criados.append(nome)
            return departamentos[chave]

        for chave, linha in unicas.items():
            colaborador = existentes.get(chave)
            if colaborador is None:
                departamento = departamento_de(linha.departamento)
                if not simular:
                    _gravar_com_auditoria(Colaborador(nome=linha.nome, departamento=departamento), usuario)
                resultado.criados.append(ItemImportacao(
                    linha.linha, linha.nome, departamento.nome if departamento else '',
                ))
                continue

            atual = nome_do_departamento.get(colaborador.departamento_id, '')
            if not linha.departamento or linha.departamento.lower() == atual.lower():
                motivo = 'Departamento vazio no arquivo: mantido o atual.' if atual and not linha.departamento else ''
                resultado.sem_alteracao.append(ItemImportacao(linha.linha, colaborador.nome, atual, motivo=motivo))
                continue
            novo = departamento_de(linha.departamento)
            if not simular:
                colaborador.departamento = novo
                colaborador.atualizado_por = usuario
                colaborador.save(update_fields=['departamento', 'atualizado_por', 'atualizado_em'])
            resultado.atualizados.append(ItemImportacao(linha.linha, colaborador.nome, novo.nome, anterior=atual))

    if not simular:
        logger.info(
            'Importação de colaboradores: %d criados, %d atualizados, %d departamentos criados.',
            len(resultado.criados), len(resultado.atualizados), len(resultado.departamentos_criados),
        )
    return resultado
