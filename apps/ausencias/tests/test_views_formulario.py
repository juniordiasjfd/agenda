"""Tela de registro/edição: formset, mapeamento dos erros do serviço e
opções de colaborador/tipo/situação."""

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.ausencias import ausencias_service
from apps.ausencias.forms import BasePeriodoFormSet
from apps.ausencias.models import Ausencia, PeriodoAusencia
from apps.ausencias.tests.conftest import d, dados_formulario, linha
from apps.colaboradores.models import Colaborador

pytestmark = pytest.mark.django_db

URL_REGISTRAR = reverse('ausencias:registrar')


def url_editar(ausencia):
    return reverse('ausencias:editar', args=[ausencia.pk])


def erros_das_linhas(response):
    """Mensagens (não de campo) de cada linha do formset, na ordem do formset."""
    return [list(form.non_field_errors()) for form in response.context['periodos'].forms]


def datas(ausencia):
    return [(f'{p.data_inicio:%d/%m/%Y}', f'{p.data_fim:%d/%m/%Y}') for p in ausencia.periodos.all()]


@pytest.fixture
def ausencia(colaborador, ferias, gestor):
    """Férias de Ana: 02 a 06/03 e 16 a 20/03/2026."""
    return ausencias_service.criar_ausencia(
        colaborador, ferias,
        [ausencias_service.PeriodoInformado(d('02/03/2026'), d('06/03/2026')),
         ausencias_service.PeriodoInformado(d('16/03/2026'), d('20/03/2026'))],
        'Viagem', gestor,
    )


def dados_edicao(ausencia, *linhas, **kwargs):
    kwargs.setdefault('iniciais', ausencia.periodos.count())
    kwargs.setdefault('versao', ausencia.atualizado_em.isoformat())
    return dados_formulario(
        kwargs.pop('colaborador', ausencia.colaborador), kwargs.pop('tipo', ausencia.tipo), *linhas, **kwargs,
    )


# ---------------------------------------------------------------------------
# Registrar
# ---------------------------------------------------------------------------
def test_registrar_com_dois_periodos(gestor_client, gestor, colaborador, ferias, aprovado):
    response = gestor_client.post(URL_REGISTRAR, dados_formulario(
        colaborador, ferias,
        linha('02/03/2026', '06/03/2026'),
        linha('16/03/2026', '20/03/2026', situacao=aprovado),
        observacoes='  Viagem ',
    ))

    assert response.status_code == 302
    ausencia = Ausencia.objects.get()
    assert (ausencia.colaborador, ausencia.tipo, ausencia.observacoes) == (colaborador, ferias, 'Viagem')
    assert ausencia.criado_por == gestor
    assert datas(ausencia) == [('02/03/2026', '06/03/2026'), ('16/03/2026', '20/03/2026')]
    assert [p.situacao.nome for p in ausencia.periodos.all()] == ['Planejado', 'Aprovado']


def test_registrar_get_tem_uma_linha_com_a_situacao_padrao(gestor_client, planejado):
    response = gestor_client.get(URL_REGISTRAR)

    periodos = response.context['periodos']
    assert len(periodos.forms) == 1
    assert periodos.forms[0]['situacao'].value() == planejado.pk


def test_registrar_sobreposicao_com_o_banco_na_linha(gestor_client, ausencia, colaborador, banco_horas):
    response = gestor_client.post(URL_REGISTRAR, dados_formulario(
        colaborador, banco_horas,
        linha('10/03/2026', '11/03/2026'),
        linha('05/03/2026', '05/03/2026'),
    ))

    assert response.status_code == 200
    assert erros_das_linhas(response) == [
        [],
        ['Sobrepõe Férias já registrado de 02/03/2026 a 06/03/2026.'],
    ]
    assert Ausencia.objects.count() == 1


def test_remocao_de_linha_no_meio_mapeia_o_erro_para_a_linha_certa(gestor_client, ausencia, colaborador, banco_horas):
    """Linhas 0, 1 (removida) e 2: para o serviço, a linha 2 é o período de
    índice 1, e o erro tem de voltar para a linha 2 do formset."""
    response = gestor_client.post(URL_REGISTRAR, dados_formulario(
        colaborador, banco_horas,
        linha('10/03/2026', '12/03/2026'),
        linha('01/03/2026', '31/03/2026', remover=True),
        linha('11/03/2026', '11/03/2026'),
    ))

    assert response.status_code == 200
    assert erros_das_linhas(response) == [
        [],
        [],
        ['Sobrepõe o período 1 deste registro (10/03/2026 a 12/03/2026).'],
    ]
    # Numeração exibida = a do serviço (a removida não conta).
    assert [numero for _, numero in response.context['periodos'].linhas()] == [1, None, 2]


def test_remocao_de_linha_no_meio_com_conflito_no_banco(gestor_client, ausencia, colaborador, banco_horas):
    response = gestor_client.post(URL_REGISTRAR, dados_formulario(
        colaborador, banco_horas,
        linha('01/03/2026', '01/03/2026', remover=True),
        linha('10/03/2026', '12/03/2026'),
        linha('18/03/2026', '18/03/2026'),
    ))

    assert erros_das_linhas(response) == [
        [],
        [],
        ['Sobrepõe Férias já registrado de 16/03/2026 a 20/03/2026.'],
    ]


def test_linha_removida_nao_e_gravada(gestor_client, colaborador, ferias):
    gestor_client.post(URL_REGISTRAR, dados_formulario(
        colaborador, ferias,
        linha('02/03/2026', '06/03/2026'),
        linha('', '', remover=True),
    ))

    assert datas(Ausencia.objects.get()) == [('02/03/2026', '06/03/2026')]


def test_linha_em_branco_nao_removida_e_erro(gestor_client, colaborador, ferias):
    response = gestor_client.post(URL_REGISTRAR, dados_formulario(
        colaborador, ferias, linha('02/03/2026', '06/03/2026'), linha('', ''),
    ))

    assert erros_das_linhas(response)[1] == ['Informe a data de início.', 'Informe a data de fim.']
    assert not Ausencia.objects.exists()


def test_limite_de_doze_periodos(gestor_client, colaborador, ferias):
    linhas = [linha(f'{dia:02d}/03/2026', f'{dia:02d}/03/2026') for dia in range(1, 14)]

    response = gestor_client.post(URL_REGISTRAR, dados_formulario(colaborador, ferias, *linhas))

    assert response.status_code == 200
    assert list(response.context['periodos'].non_form_errors()) == ['No máximo 12 períodos por registro.']
    assert not Ausencia.objects.exists()


def test_doze_periodos_aceitos_mesmo_com_removidas_alem(gestor_client, colaborador, ferias):
    linhas = [linha(f'{dia:02d}/03/2026', f'{dia:02d}/03/2026') for dia in range(1, 13)]
    linhas.append(linha('20/03/2026', '20/03/2026', remover=True))

    response = gestor_client.post(URL_REGISTRAR, dados_formulario(colaborador, ferias, *linhas))

    assert response.status_code == 302
    assert Ausencia.objects.get().periodos.count() == 12


@pytest.mark.parametrize('inicio, fim', [('31/12/1999', '02/01/2000'), ('30/12/2100', '01/01/2101')])
def test_ano_fora_do_intervalo(gestor_client, colaborador, ferias, inicio, fim):
    response = gestor_client.post(URL_REGISTRAR, dados_formulario(colaborador, ferias, linha(inicio, fim)))

    assert erros_das_linhas(response) == [['O ano deve estar entre 2000 e 2100.']]
    assert not Ausencia.objects.exists()


def test_campos_de_data_com_min_e_max(gestor_client):
    html = gestor_client.get(URL_REGISTRAR).content.decode()

    assert 'min="2000-01-01"' in html
    assert 'max="2100-12-31"' in html


def test_data_ilegivel_mostra_so_o_erro_do_campo(gestor_client, colaborador, ferias):
    dados = dados_formulario(colaborador, ferias, linha('02/03/2026', '06/03/2026'))
    dados['periodos-0-data_inicio'] = '2026-13-45'

    response = gestor_client.post(URL_REGISTRAR, dados)

    form = response.context['periodos'].forms[0]
    assert form.has_error('data_inicio')
    assert list(form.non_field_errors()) == []


def test_cabecalho_obrigatorio_sem_mensagem_repetida(gestor_client):
    response = gestor_client.post(URL_REGISTRAR, dados_formulario(None, None, linha('02/03/2026', '06/03/2026')))

    cabecalho = response.context['cabecalho']
    assert cabecalho.errors['colaborador'] == ['Este campo é obrigatório.']
    assert cabecalho.errors['tipo'] == ['Este campo é obrigatório.']


def test_nenhum_periodo(gestor_client, colaborador, ferias):
    response = gestor_client.post(URL_REGISTRAR, dados_formulario(colaborador, ferias))

    assert list(response.context['periodos'].non_form_errors()) == ['Informe pelo menos um período.']


def test_conflito_concorrente_capturado_na_gravacao(gestor_client, monkeypatch, colaborador, ferias, banco_horas, gravar_ausencia):
    """Outro envio do mesmo colaborador grava entre a validação do formulário
    e a trava do serviço: o serviço recusa e a tela mostra o erro na linha."""
    clean_original = BasePeriodoFormSet.clean

    def clean_e_outro_grava(self):
        clean_original(self)
        gravar_ausencia(colaborador, banco_horas, ('05/03/2026', '05/03/2026'))

    monkeypatch.setattr(BasePeriodoFormSet, 'clean', clean_e_outro_grava)

    response = gestor_client.post(URL_REGISTRAR, dados_formulario(
        colaborador, ferias, linha('01/03/2026', '01/03/2026'), linha('02/03/2026', '06/03/2026'),
    ))

    assert response.status_code == 200
    assert erros_das_linhas(response) == [[], ['Sobrepõe Banco de horas já registrado de 05/03/2026 a 05/03/2026.']]
    assert not Ausencia.objects.filter(tipo=ferias).exists()


# ---------------------------------------------------------------------------
# Opções e pré-seleção
# ---------------------------------------------------------------------------
def test_pre_seleciona_o_colaborador_vinculado(gestor_client, gestor, colaborador):
    colaborador.usuario = gestor
    colaborador.save()

    response = gestor_client.get(URL_REGISTRAR)

    assert response.context['cabecalho']['colaborador'].value() == colaborador.pk


def test_nao_pre_seleciona_colaborador_vinculado_inativo(gestor_client, gestor, colaborador):
    colaborador.usuario, colaborador.ativo = gestor, False
    colaborador.save()

    response = gestor_client.get(URL_REGISTRAR)

    assert response.context['cabecalho']['colaborador'].value() is None


def test_edicao_nao_troca_pelo_colaborador_vinculado(gestor_client, gestor, ausencia, outro_colaborador):
    outro_colaborador.usuario = gestor
    outro_colaborador.save()

    response = gestor_client.get(url_editar(ausencia))

    assert response.context['cabecalho']['colaborador'].value() == ausencia.colaborador_id


def test_inativos_fora_das_opcoes_no_registro(gestor_client, colaborador, outro_colaborador, ferias, banco_horas, aprovado):
    outro_colaborador.ativo = False
    outro_colaborador.save()
    banco_horas.ativo = False
    banco_horas.save()
    aprovado.ativo = False
    aprovado.save()

    response = gestor_client.get(URL_REGISTRAR)

    cabecalho = response.context['cabecalho']
    assert list(cabecalho.fields['colaborador'].queryset) == [colaborador]
    assert banco_horas not in cabecalho.fields['tipo'].queryset
    assert aprovado not in response.context['periodos'].forms[0].fields['situacao'].queryset


def test_inativos_em_uso_aparecem_na_edicao(gestor_client, ausencia, colaborador, ferias, aprovado, outro_colaborador):
    periodo = ausencia.periodos.first()
    periodo.situacao = aprovado
    periodo.save()
    for objeto in (colaborador, ferias, aprovado, outro_colaborador):
        objeto.ativo = False
        objeto.save()

    response = gestor_client.get(url_editar(ausencia))

    cabecalho = response.context['cabecalho']
    assert list(cabecalho.fields['colaborador'].queryset) == [colaborador]
    assert ferias in cabecalho.fields['tipo'].queryset
    assert aprovado in response.context['periodos'].forms[0].fields['situacao'].queryset
    html = response.content.decode()
    assert 'Ana Souza (inativo)' in html
    assert 'Férias (inativo)' in html
    assert 'Aprovado (inativo)' in html


def test_colaborador_inativo_fora_da_lista_e_recusado(gestor_client, colaborador, ferias):
    colaborador.ativo = False
    colaborador.save()

    response = gestor_client.post(URL_REGISTRAR, dados_formulario(colaborador, ferias, linha('02/03/2026', '06/03/2026')))

    assert response.context['cabecalho'].has_error('colaborador')
    assert not Ausencia.objects.exists()


def test_colaborador_inexistente_no_post(gestor_client, ferias):
    fantasma = Colaborador(pk=999999)

    response = gestor_client.post(URL_REGISTRAR, dados_formulario(fantasma, ferias, linha('02/03/2026', '06/03/2026')))

    assert response.context['cabecalho'].has_error('colaborador')


# ---------------------------------------------------------------------------
# Editar
# ---------------------------------------------------------------------------
def test_editar_get_preenche_com_a_ausencia(gestor_client, ausencia):
    response = gestor_client.get(url_editar(ausencia))

    periodos = response.context['periodos']
    assert [f['data_inicio'].value() for f in periodos.forms] == [d('02/03/2026'), d('16/03/2026')]
    assert [f['id'].value() for f in periodos.forms] == [p.pk for p in ausencia.periodos.all()]
    assert response.context['cabecalho']['observacoes'].value() == 'Viagem'


def test_editar_sem_conflitar_com_os_proprios_periodos(gestor_client, ausencia):
    primeiro, segundo = ausencia.periodos.all()

    response = gestor_client.post(url_editar(ausencia), dados_edicao(
        ausencia,
        linha('02/03/2026', '06/03/2026', id=primeiro.pk),
        linha('16/03/2026', '20/03/2026', id=segundo.pk),
        observacoes='Outra',
    ))

    assert response.status_code == 302
    ausencia.refresh_from_db()
    assert ausencia.observacoes == 'Outra'


def test_editar_adiciona_altera_e_remove(gestor_client, ausencia):
    primeiro, segundo = ausencia.periodos.all()

    response = gestor_client.post(url_editar(ausencia), dados_edicao(
        ausencia,
        linha('03/03/2026', '06/03/2026', id=primeiro.pk),               # altera
        linha('16/03/2026', '20/03/2026', id=segundo.pk, remover=True),  # remove
        linha('01/04/2026', '02/04/2026'),                               # adiciona
    ))

    assert response.status_code == 302
    assert datas(ausencia) == [('03/03/2026', '06/03/2026'), ('01/04/2026', '02/04/2026')]
    assert ausencia.periodos.filter(pk=primeiro.pk).exists()
    assert not PeriodoAusencia.objects.filter(pk=segundo.pk).exists()


def test_editar_periodo_de_outra_ausencia_recusado(gestor_client, ausencia, outro_colaborador, ferias, gravar_ausencia):
    alheia = gravar_ausencia(outro_colaborador, ferias, ('01/05/2026', '02/05/2026'))

    response = gestor_client.post(url_editar(ausencia), dados_edicao(
        ausencia, linha('01/05/2026', '02/05/2026', id=alheia.periodos.get().pk),
    ))

    assert erros_das_linhas(response) == [['Este período não pertence a este registro.']]
    assert alheia.periodos.get().data_inicio == d('01/05/2026')


def test_editar_conflito_com_outra_ausencia(gestor_client, ausencia, colaborador, banco_horas, gravar_ausencia):
    gravar_ausencia(colaborador, banco_horas, ('01/04/2026', '03/04/2026'))
    primeiro, segundo = ausencia.periodos.all()

    response = gestor_client.post(url_editar(ausencia), dados_edicao(
        ausencia,
        linha('02/03/2026', '06/03/2026', id=primeiro.pk),
        linha('02/04/2026', '02/04/2026', id=segundo.pk),
    ))

    assert erros_das_linhas(response) == [[], ['Sobrepõe Banco de horas já registrado de 01/04/2026 a 03/04/2026.']]
    assert datas(ausencia)[1] == ('16/03/2026', '20/03/2026')


def test_editar_ausencia_na_lixeira_redireciona(gestor_client, ausencia, gestor):
    ausencias_service.excluir_ausencia(ausencia, gestor)

    response = gestor_client.get(url_editar(ausencia), follow=True)

    assert 'Restaure antes de editar' in response.content.decode()


def test_editar_inexistente_404(gestor_client):
    assert gestor_client.get(reverse('ausencias:editar', args=[999999])).status_code == 404


# ---------------------------------------------------------------------------
# Trava otimista
# ---------------------------------------------------------------------------
def test_editar_com_versao_desatualizada_recusa_e_mantem_o_digitado(gestor_client, ausencia, admin):
    versao_aberta = ausencia.atualizado_em.isoformat()
    primeiro, segundo = ausencia.periodos.all()
    # Outra pessoa salva no meio tempo.
    ausencias_service.atualizar_ausencia(
        ausencia, ausencia.colaborador, ausencia.tipo,
        [ausencias_service.PeriodoInformado(p.data_inicio, p.data_fim, p.situacao, p.pk) for p in (primeiro, segundo)],
        'Do outro', admin,
    )

    response = gestor_client.post(url_editar(ausencia), dados_edicao(
        ausencia,
        linha('03/03/2026', '06/03/2026', id=primeiro.pk),
        linha('16/03/2026', '20/03/2026', id=segundo.pk),
        observacoes='Minha',
        versao=versao_aberta,
    ))

    assert response.status_code == 200
    assert list(response.context['cabecalho'].non_field_errors()) == [
        'Esta ausência foi alterada por outra pessoa. Recarregue e refaça a edição.'
    ]
    html = response.content.decode()
    assert 'Minha' in html and 'value="2026-03-03"' in html
    ausencia.refresh_from_db()
    assert ausencia.observacoes == 'Do outro'


def test_editar_sem_versao_recusado(gestor_client, ausencia):
    primeiro, segundo = ausencia.periodos.all()

    response = gestor_client.post(url_editar(ausencia), dados_edicao(
        ausencia, linha('02/03/2026', '06/03/2026', id=primeiro.pk), versao='lixo',
    ))

    assert response.context['cabecalho'].non_field_errors()
    assert ausencia.periodos.count() == 2


def test_alteracao_entre_validacao_e_gravacao_recusada(gestor_client, monkeypatch, ausencia, admin):
    """A tela validou com a versão atual, mas outra gravação entrou antes da
    trava: o serviço recusa e a mensagem é a mesma."""
    clean_original = BasePeriodoFormSet.clean

    def clean_e_outro_salva(self):
        clean_original(self)
        type(ausencia).todos.filter(pk=ausencia.pk).update(observacoes='Do outro', atualizado_em=timezone.now())

    monkeypatch.setattr(BasePeriodoFormSet, 'clean', clean_e_outro_salva)
    primeiro, segundo = ausencia.periodos.all()

    response = gestor_client.post(url_editar(ausencia), dados_edicao(
        ausencia, linha('02/03/2026', '06/03/2026', id=primeiro.pk), observacoes='Minha',
    ))

    assert response.status_code == 200
    assert list(response.context['cabecalho'].non_field_errors()) == [
        'Esta ausência foi alterada por outra pessoa. Recarregue e refaça a edição.'
    ]
    assert ausencia.periodos.count() == 2


def test_formulario_de_edicao_leva_a_versao(gestor_client, ausencia):
    html = gestor_client.get(url_editar(ausencia)).content.decode()

    assert f'value="{ausencia.atualizado_em.isoformat()}"' in html


# ---------------------------------------------------------------------------
# Linhas dinâmicas (estrutura que o Alpine usa)
# ---------------------------------------------------------------------------
def test_tela_tem_linha_modelo_e_data_de_hoje(gestor_client):
    html = gestor_client.get(URL_REGISTRAR).content.decode()

    assert 'x-ref="modelo"' in html
    assert 'periodos-__prefix__-data_inicio' in html
    assert f'data-hoje="{timezone.localdate():%Y-%m-%d}"' in html
    assert 'periodosForm(12)' in html


def test_linha_removida_continua_oculta_e_marcada_apos_erro(gestor_client, colaborador, ferias):
    response = gestor_client.post(URL_REGISTRAR, dados_formulario(
        colaborador, ferias,
        linha('', ''),
        linha('02/03/2026', '06/03/2026', remover=True),
    ))

    html = response.content.decode()
    assert 'name="periodos-1-DELETE" class="form-check-input" checked' in html
    linhas = response.context['periodos'].linhas()
    assert [numero for _, numero in linhas] == [1, None]
