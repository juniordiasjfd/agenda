from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from apps.colaboradores.colaboradores_service import ArquivoNomesInvalido, ler_nomes_js
from apps.colaboradores.models import Colaborador

ARQUIVO_LEGADO = Path(__file__).parent / 'fixtures' / 'funcionarios_sintetico.js'
# Arquivo sintético no formato do legado (nomes fictícios, todos distintos).
TOTAL_LEGADO = 10


def _rodar(caminho, *args):
    saida = StringIO()
    call_command('carregar_colaboradores', str(caminho), *args, stdout=saida)
    return saida.getvalue()


@pytest.fixture
def arquivo_js(tmp_path):
    def criar(conteudo, encoding='utf-8'):
        caminho = tmp_path / 'funcionarios.js'
        caminho.write_bytes(conteudo.encode(encoding))
        return caminho
    return criar


# ---------------------------------------------------------------------------
# Parse (sem banco)
# ---------------------------------------------------------------------------
def test_ler_nomes_js_formato_legado():
    texto = (
        '\ufeff// Lista de colaboradores do formulário "Registro de ausências".\n'
        '// Um nome por linha, entre aspas.\n'
        'window.FUNCIONARIOS = [\n'
        '  "Ana Souza",\n'
        '  // "Comentado Fora",\n'
        '  "Helena  Teixeira Exemplo",\n'
        '  "Jos\\u00e9 \\"Zé\\" Lima",\n'
        '  "Colchete ] no nome",\n'
        '];\n'
    )
    assert ler_nomes_js(texto) == ['Ana Souza', 'Helena  Teixeira Exemplo', 'José "Zé" Lima', 'Colchete ] no nome']


def test_ler_nomes_js_sem_virgula_final_e_em_uma_linha():
    assert ler_nomes_js('window.FUNCIONARIOS = ["A", "B"];') == ['A', 'B']


def test_ler_nomes_js_array_vazio():
    assert ler_nomes_js('window.FUNCIONARIOS = [];') == []


@pytest.mark.parametrize('texto', [
    'window.FUNCIONARIOS = "Ana";',
    '// window.FUNCIONARIOS = ["Ana"];',
    '',
    'window.FUNCIONARIOS = ["Ana", "Bia"',
])
def test_ler_nomes_js_sem_array(texto):
    with pytest.raises(ArquivoNomesInvalido, match='Nenhum array'):
        ler_nomes_js(texto)


@pytest.mark.parametrize('texto', [
    "window.FUNCIONARIOS = ['Ana', 'Bia'];",
    'window.FUNCIONARIOS = ["Ana", nome];',
])
def test_ler_nomes_js_conteudo_estranho(texto):
    with pytest.raises(ArquivoNomesInvalido, match='não é nome entre aspas duplas'):
        ler_nomes_js(texto)


def test_ler_nomes_js_nao_executa_nada():
    # Expressões JS não são avaliadas: o arquivo é recusado.
    with pytest.raises(ArquivoNomesInvalido):
        ler_nomes_js('window.FUNCIONARIOS = ["Ana" + alert(1)];')


# ---------------------------------------------------------------------------
# Comando com o arquivo no formato do legado
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_carrega_arquivo_legado():
    saida = _rodar(ARQUIVO_LEGADO)

    assert Colaborador.objects.count() == TOTAL_LEGADO
    assert not Colaborador.objects.filter(ativo=False).exists()
    assert not Colaborador.objects.filter(departamento__isnull=False).exists()
    assert Colaborador.objects.filter(nome='Helena Teixeira Exemplo').exists()
    assert Colaborador.objects.filter(nome='Beatriz de Fátima Modelo').exists()
    assert f'Lidos: {TOTAL_LEGADO}' in saida
    assert f'Criados: {TOTAL_LEGADO}' in saida
    assert 'Já existentes (ignorados): 0' in saida
    assert 'Duplicados no arquivo (ignorados): 0' in saida


@pytest.mark.django_db
def test_segunda_execucao_nao_cria_nada():
    _rodar(ARQUIVO_LEGADO)
    saida = _rodar(ARQUIVO_LEGADO)

    assert Colaborador.objects.count() == TOTAL_LEGADO
    assert 'Criados: 0' in saida
    assert f'Já existentes (ignorados): {TOTAL_LEGADO}' in saida


@pytest.mark.django_db
def test_dry_run_nao_grava():
    saida = _rodar(ARQUIVO_LEGADO, '--dry-run')

    assert not Colaborador.objects.exists()
    assert 'nada foi gravado' in saida
    assert f'Seriam criados: {TOTAL_LEGADO}' in saida


# ---------------------------------------------------------------------------
# Comando com arquivos de teste
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_normaliza_espacos_e_reporta_duplicados_no_arquivo(arquivo_js):
    caminho = arquivo_js(
        'window.FUNCIONARIOS = [\n'
        '  "Helena  Teixeira Exemplo",\n'
        '  "helena teixeira exemplo",\n'
        '  "José Lima",\n'
        '  "JOSE  LIMA",\n'
        '  "   ",\n'
        '];\n'
    )

    saida = _rodar(caminho)

    assert sorted(Colaborador.objects.values_list('nome', flat=True)) == ['Helena Teixeira Exemplo', 'José Lima']
    assert 'Lidos: 5' in saida
    assert 'Criados: 2' in saida
    assert 'Duplicados no arquivo (ignorados): 2' in saida
    assert '  - helena teixeira exemplo' in saida
    assert '  - JOSE LIMA' in saida
    assert 'Vazios descartados: 1' in saida


@pytest.mark.django_db
def test_existentes_ficam_intactos(arquivo_js, departamento, admin):
    existente = Colaborador.objects.create(
        nome='José Lima', departamento=departamento, ativo=False, criado_por=admin,
    )
    caminho = arquivo_js('window.FUNCIONARIOS = ["JOSE  LIMA", "Nova Pessoa"];')

    saida = _rodar(caminho)

    existente.refresh_from_db()
    assert existente.nome == 'José Lima'
    assert existente.departamento == departamento
    assert existente.ativo is False
    assert existente.criado_por == admin
    assert Colaborador.objects.count() == 2
    assert 'Criados: 1' in saida
    assert 'Já existentes (ignorados): 1' in saida


@pytest.mark.django_db
def test_arquivo_com_bom(arquivo_js):
    caminho = arquivo_js('\ufeffwindow.FUNCIONARIOS = ["Ângela"];')

    _rodar(caminho)

    assert Colaborador.objects.get().nome == 'Ângela'


@pytest.mark.django_db
def test_arquivo_inexistente(tmp_path):
    with pytest.raises(CommandError, match='Arquivo não encontrado'):
        _rodar(tmp_path / 'nao-existe.js')


@pytest.mark.django_db
def test_arquivo_sem_array(arquivo_js):
    caminho = arquivo_js('console.log("oi");\n')

    with pytest.raises(CommandError, match='Nenhum array'):
        _rodar(caminho)
    assert not Colaborador.objects.exists()


@pytest.mark.django_db
def test_arquivo_fora_de_utf8(arquivo_js):
    caminho = arquivo_js('window.FUNCIONARIOS = ["Ângela"];', encoding='cp1252')

    with pytest.raises(CommandError, match='não está em UTF-8'):
        _rodar(caminho)
    assert not Colaborador.objects.exists()
