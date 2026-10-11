"""Utilitários sem dependência de models."""

import unicodedata


def colapsar_espacos(texto):
    """Sem espaços nas pontas e com espaços múltiplos (inclui tab/quebra de
    linha) reduzidos a um: '  Ana   Lúcia ' -> 'Ana Lúcia'. Mantém caixa e
    acentos."""
    return ' '.join((texto or '').split())


def normalizar_nome(texto):
    """Chave de comparação de nomes: espaços colapsados, minúsculas e sem
    acentos (decomposição NFD, descartando as marcas combinantes).

    'José  da SILVA' -> 'jose da silva'. Equivale ao ``norm()`` do
    ``legado/referencias/index.html``. Usada na unicidade de Colaborador, na
    busca e na importação de CSV.
    """
    texto = colapsar_espacos(texto).lower()
    decomposto = unicodedata.normalize('NFD', texto)
    return ''.join(c for c in decomposto if not unicodedata.combining(c))
