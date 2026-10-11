import pytest

from apps.core.utils import colapsar_espacos, normalizar_nome


@pytest.mark.parametrize('entrada, esperado', [
    ('Helena  Teixeira Exemplo', 'helena teixeira exemplo'),
    ('  Ana   Lúcia  ', 'ana lucia'),
    ('Ana\tLúcia\nSouza', 'ana lucia souza'),
    ('JOÃO GUILHERME', 'joao guilherme'),
    ('Verônica Merlin', 'veronica merlin'),
    ('Ângela Françoise Müller', 'angela francoise muller'),
    ('Ç Ñ ü', 'c n u'),
])
def test_normalizar_nome(entrada, esperado):
    assert normalizar_nome(entrada) == esperado


def test_normalizar_nome_iguala_variacoes():
    assert normalizar_nome('José da Silva') == normalizar_nome('jose  DA silva') == normalizar_nome(' JOSÉ DA SILVA ')


def test_normalizar_nome_aceita_forma_decomposta():
    # "é" já decomposto (e + acento combinante) vira o mesmo que o composto.
    assert normalizar_nome('José') == normalizar_nome('José') == 'jose'


@pytest.mark.parametrize('vazio', ['', '   ', None])
def test_normalizar_nome_vazio(vazio):
    assert normalizar_nome(vazio) == ''


def test_colapsar_espacos_mantem_caixa_e_acentos():
    assert colapsar_espacos('  Ana   LÚCIA ') == 'Ana LÚCIA'
    assert colapsar_espacos(None) == ''
