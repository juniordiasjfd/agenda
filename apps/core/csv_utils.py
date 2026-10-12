"""Utilitários de CSV usados por mais de um app (ausências e colaboradores).

Puros: não consultam o banco.
"""

BOM = '﻿'

# Injeção de fórmula (planilhas executam célula que começa com = + - @...)
_INICIO_DE_FORMULA = ('=', '+', '-', '@', '\t', '\r')


def neutralizar_formula(valor):
    """Prefixa com apóstrofo o texto que uma planilha leria como fórmula."""
    return f"'{valor}" if valor.startswith(_INICIO_DE_FORMULA) else valor


def desfazer_neutralizacao(valor):
    """Inverso exato de ``neutralizar_formula``: tira o apóstrofo só quando
    ele vem seguido de um dos caracteres neutralizados."""
    if len(valor) >= 2 and valor[0] == "'" and valor[1] in _INICIO_DE_FORMULA:
        return valor[1:]
    return valor


def decodificar(conteudo):
    """``(texto, codificação)``: UTF-8 (com ou sem BOM) e, se não for,
    Windows-1252. ``(None, '')`` se nenhuma das duas servir."""
    try:
        texto = conteudo.decode('utf-8')
    except UnicodeDecodeError:
        pass
    else:
        if texto.startswith(BOM):
            return texto[1:], 'UTF-8 com BOM'
        return texto, 'UTF-8'
    try:
        return conteudo.decode('cp1252'), 'Windows-1252'
    except UnicodeDecodeError:
        return None, ''


def detectar_separador(texto):
    """``;`` ou ``,``: o mais frequente na primeira linha (empate = ``;``)."""
    primeira_linha = texto.splitlines()[0] if texto else ''
    return ';' if primeira_linha.count(';') >= primeira_linha.count(',') else ','
