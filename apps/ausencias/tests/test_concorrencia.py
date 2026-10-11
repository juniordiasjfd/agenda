"""Dois registros simultâneos (threads, conexões e transações reais no
PostgreSQL). A trava do colaborador (select_for_update) precisa serializar
os envios do MESMO colaborador sem bloquear colaboradores diferentes."""

import threading
import time
from datetime import date

import pytest
from django.db import connection

from apps.ausencias import ausencias_service
from apps.ausencias.ausencias_service import ErroValidacaoAusencia, PeriodoInformado
from apps.ausencias.models import Ausencia, TipoAusencia
from apps.colaboradores.models import Colaborador

REPETICOES = 5


@pytest.fixture
def janela_de_corrida(monkeypatch):
    """Alarga a janela entre "consultei os conflitos" e "gravei": sem a trava,
    os dois envios veriam o banco vazio e gravariam."""
    original = ausencias_service.periodos_conflitantes

    def lento(*args, **kwargs):
        resultado = original(*args, **kwargs)
        time.sleep(0.3)
        return resultado

    monkeypatch.setattr(ausencias_service, 'periodos_conflitantes', lento)


def _registrar_em_paralelo(envios):
    """``envios``: lista de (colaborador, PeriodoInformado). Devolve os
    resultados ('ok' ou 'conflito'), em qualquer ordem."""
    tipo = TipoAusencia.objects.get(nome='Férias')
    barreira = threading.Barrier(len(envios))
    resultados = []

    def registrar(colaborador, periodo):
        try:
            barreira.wait(timeout=5)
            ausencias_service.criar_ausencia(colaborador, tipo, [periodo], '', None)
            resultados.append('ok')
        except ErroValidacaoAusencia:
            resultados.append('conflito')
        finally:
            connection.close()

    threads = [threading.Thread(target=registrar, args=envio) for envio in envios]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    return resultados


@pytest.mark.parametrize('repeticao', range(REPETICOES))
@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_mesmo_colaborador_so_um_e_aceito(janela_de_corrida, repeticao):
    colaborador = Colaborador.objects.create(nome='Ana Souza')

    resultados = _registrar_em_paralelo([
        (colaborador, PeriodoInformado(date(2026, 3, 10), date(2026, 3, 20))),
        (colaborador, PeriodoInformado(date(2026, 3, 15), date(2026, 3, 25))),
    ])

    assert sorted(resultados) == ['conflito', 'ok']
    assert Ausencia.objects.filter(colaborador=colaborador).count() == 1


@pytest.mark.parametrize('repeticao', range(REPETICOES))
@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_colaboradores_diferentes_ambos_passam(janela_de_corrida, repeticao):
    ana = Colaborador.objects.create(nome='Ana Souza')
    bruno = Colaborador.objects.create(nome='Bruno Lima')

    resultados = _registrar_em_paralelo([
        (ana, PeriodoInformado(date(2026, 3, 10), date(2026, 3, 20))),
        (bruno, PeriodoInformado(date(2026, 3, 10), date(2026, 3, 20))),
    ])

    assert resultados == ['ok', 'ok']
    assert Ausencia.objects.count() == 2
