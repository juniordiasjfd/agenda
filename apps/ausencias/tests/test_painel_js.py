"""Guardas do static/js/painel.js (lido como texto: não há navegador na suíte).

O JS do painel só desenha: texto do servidor nunca entra como HTML, a cor do
tipo é validada e o localStorage guarda só a preferência de escala.
"""

import re
from pathlib import Path

from django.conf import settings

PAINEL_JS = Path(settings.BASE_DIR) / 'static' / 'js' / 'painel.js'


def _codigo():
    """O arquivo sem comentários (os comentários citam as palavras proibidas)."""
    texto = PAINEL_JS.read_text(encoding='utf-8')
    texto = re.sub(r'/\*.*?\*/', '', texto, flags=re.S)
    return re.sub(r'//[^\n]*', '', texto)


def test_nenhuma_insercao_de_html():
    codigo = _codigo()

    for proibido in ('innerHTML', 'outerHTML', 'insertAdjacentHTML', 'document.write', 'eval(', 'new Function'):
        assert proibido not in codigo, proibido


def test_cor_do_tipo_validada_no_cliente():
    assert "/^#[0-9a-fA-F]{6}$/" in _codigo()


def test_localstorage_so_para_a_escala():
    usos = re.findall(r'localStorage\.(\w+)\(([^,)]*)', _codigo())

    assert usos
    assert {argumento.strip() for _, argumento in usos} == {'CHAVE_ESCALA'}


def test_hoje_vem_do_servidor_e_nao_do_relogio():
    codigo = _codigo()

    assert 'new Date()' not in codigo
    assert 'Date.now(' not in codigo
    assert 'isoParaMs(dados.hoje)' in codigo


def test_url_do_detalhe_precisa_ser_relativa():
    assert 'urlSegura(item.periodo.url)' in _codigo()
