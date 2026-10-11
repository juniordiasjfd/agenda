import re

import pytest

from apps.ausencias import ausencias_service

pytestmark = pytest.mark.django_db


def test_formato_e_alfabeto():
    codigos = [ausencias_service.gerar_codigo() for _ in range(300)]

    for codigo in codigos:
        assert re.fullmatch(r'[A-Z2-9]{8}', codigo)
        assert not set(codigo) & set('0O1IL')
    assert len(set(codigos)) == len(codigos)


def test_alfabeto_sem_ambiguos():
    assert len(ausencias_service.ALFABETO_CODIGO) == 31
    assert not set(ausencias_service.ALFABETO_CODIGO) & set('0O1IL')


def test_retenta_quando_o_codigo_ja_existe(monkeypatch, gravar_ausencia, colaborador, ferias, admin):
    existente = gravar_ausencia(colaborador, ferias, ('01/03/2026', '02/03/2026'))
    existente.excluir(admin)  # excluída também conta
    sorteios = iter(existente.codigo + 'ABCDEFGH')
    monkeypatch.setattr(ausencias_service.secrets, 'choice', lambda alfabeto: next(sorteios))

    assert ausencias_service.gerar_codigo() == 'ABCDEFGH'


def test_desiste_apos_tentativas_limitadas(monkeypatch, gravar_ausencia, colaborador, ferias):
    existente = gravar_ausencia(colaborador, ferias, ('01/03/2026', '02/03/2026'))
    letras = list(existente.codigo)
    chamadas = []

    def sempre_o_mesmo(alfabeto):
        chamadas.append(1)
        return letras[(len(chamadas) - 1) % 8]

    monkeypatch.setattr(ausencias_service.secrets, 'choice', sempre_o_mesmo)

    with pytest.raises(RuntimeError):
        ausencias_service.gerar_codigo()
    assert len(chamadas) == 8 * ausencias_service.TENTATIVAS_CODIGO
