import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.colaboradores import colaboradores_service
from apps.colaboradores.colaboradores_service import ArquivoColaboradoresInvalido, ler_csv_colaboradores
from apps.colaboradores.models import Colaborador, Departamento

pytestmark = pytest.mark.django_db

URL = reverse('colaboradores:colaboradores_importar')


def _arquivo(texto, nome='colaboradores.csv', codificacao='utf-8'):
    return SimpleUploadedFile(nome, texto.encode(codificacao), content_type='text/csv')


def _importar(texto, usuario, simular=False):
    linhas = ler_csv_colaboradores(_arquivo(texto))
    return colaboradores_service.importar_colaboradores(linhas, usuario, simular=simular)


def _departamento_de(nome):
    colaborador = Colaborador.objects.select_related('departamento').get(nome=nome)
    return colaborador.departamento.nome if colaborador.departamento else None


# ---------------------------------------------------------------------------
# Acesso
# ---------------------------------------------------------------------------
def test_anonimo_vai_para_o_login(client):
    for metodo in ('get', 'post'):
        response = getattr(client, metodo)(URL)
        assert response.status_code == 302
        assert response.url.startswith(reverse('usuarios:login'))


def test_sem_grupo_e_gestor_recebem_403(client, usuario_ativo, gestor):
    for usuario in (usuario_ativo, gestor):
        client.force_login(usuario)
        assert client.get(URL).status_code == 403
        response = client.post(URL, {'arquivo': _arquivo('Colaborador\nAna Lima\n')})
        assert response.status_code == 403
    assert not Colaborador.objects.exists()


def test_admin_ve_o_formulario_com_simulacao_marcada(admin_client):
    response = admin_client.get(URL)
    assert response.status_code == 200
    assert response.context['form']['simular'].value() is True


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------
def test_le_ponto_e_virgula_e_departamento_vazio():
    linhas = ler_csv_colaboradores(_arquivo('Colaborador;Departamento\nAna  Lima ;Financeiro\nBruno Reis;\n'))
    assert [(l.linha, l.nome, l.departamento) for l in linhas] == [
        (2, 'Ana Lima', 'Financeiro'), (3, 'Bruno Reis', ''),
    ]


def test_le_virgula_windows_1252_bom_e_coluna_departamento_ausente():
    linhas = ler_csv_colaboradores(_arquivo('colaborador,departamento\nJosé Souza,Operações\n', codificacao='cp1252'))
    assert (linhas[0].nome, linhas[0].departamento) == ('José Souza', 'Operações')

    linhas = ler_csv_colaboradores(_arquivo('﻿Colaborador\nAna Lima\n\n;\n'))
    assert [(l.nome, l.departamento) for l in linhas] == [('Ana Lima', '')]


def test_desfaz_apostrofo_anti_formula():
    linhas = ler_csv_colaboradores(_arquivo("Colaborador;Departamento\n'=Ana;'-TI\n"))
    assert (linhas[0].nome, linhas[0].departamento) == ('=Ana', '-TI')


@pytest.mark.parametrize('texto, nome, mensagem', [
    ('Pessoa;Setor\nAna;TI\n', 'a.csv', 'Falta a coluna obrigatória: Colaborador.'),
    ('Colaborador\n', 'a.csv', 'não tem linhas de dados'),
    ('', 'a.csv', 'vazio'),
    ('Colaborador\nAna\n', 'a.xlsx', 'Extensão não aceita'),
])
def test_arquivo_recusado(texto, nome, mensagem):
    with pytest.raises(ArquivoColaboradoresInvalido, match=mensagem):
        ler_csv_colaboradores(_arquivo(texto, nome=nome))


def test_limites_de_tamanho_e_registros(settings):
    settings.CSV_IMPORTACAO_MAX_REGISTROS = 2
    with pytest.raises(ArquivoColaboradoresInvalido, match='mais de 2 registros'):
        ler_csv_colaboradores(_arquivo('Colaborador\nA\nB\nC\n'))
    settings.CSV_IMPORTACAO_MAX_BYTES = 10
    with pytest.raises(ArquivoColaboradoresInvalido, match='maior que'):
        ler_csv_colaboradores(_arquivo('Colaborador\nAna Lima\n'))


# ---------------------------------------------------------------------------
# Regras
# ---------------------------------------------------------------------------
def test_cria_colaboradores_e_departamento_vazio_fica_sem_departamento(admin):
    resultado = _importar('Colaborador;Departamento\nAna Lima;Financeiro\nBruno Reis;\n', admin)
    assert [i.nome for i in resultado.criados] == ['Ana Lima', 'Bruno Reis']
    assert _departamento_de('Ana Lima') == 'Financeiro'
    assert _departamento_de('Bruno Reis') is None
    ana = Colaborador.objects.get(nome='Ana Lima')
    assert ana.ativo is True
    assert ana.criado_por == admin


def test_departamento_inexistente_e_criado_uma_vez_e_existente_reaproveitado(admin):
    Departamento.objects.create(nome='Financeiro')
    resultado = _importar('Colaborador;Departamento\nAna;financeiro\nBruno;Jurídico\nCarla;JURÍDICO\n', admin)
    assert resultado.departamentos_criados == ['Jurídico']
    assert Departamento.objects.count() == 2
    assert _departamento_de('Ana') == 'Financeiro'
    assert _departamento_de('Carla') == 'Jurídico'
    assert Departamento.objects.get(nome='Jurídico').criado_por == admin


def test_existente_tem_departamento_atualizado(admin, colaborador):
    # colaborador = "José da Silva", departamento Financeiro.
    resultado = _importar('Colaborador;Departamento\njose  DA silva;Comercial\n', admin)
    assert [(i.nome, i.anterior, i.departamento) for i in resultado.atualizados] == [
        ('José da Silva', 'Financeiro', 'Comercial'),
    ]
    colaborador.refresh_from_db()
    assert colaborador.departamento.nome == 'Comercial'
    assert colaborador.nome == 'José da Silva'
    assert colaborador.atualizado_por == admin
    assert not resultado.criados


def test_existente_com_departamento_vazio_ou_igual_nao_muda(admin, colaborador):
    resultado = _importar('Colaborador;Departamento\nJosé da Silva;\n', admin)
    assert len(resultado.sem_alteracao) == 1
    assert 'mantido o atual' in resultado.sem_alteracao[0].motivo
    resultado = _importar('Colaborador;Departamento\nJosé da Silva;FINANCEIRO\n', admin)
    assert len(resultado.sem_alteracao) == 1
    colaborador.refresh_from_db()
    assert colaborador.departamento.nome == 'Financeiro'


def test_existente_inativo_continua_inativo(admin, colaborador):
    colaborador.ativo = False
    colaborador.save()
    _importar('Colaborador;Departamento\nJosé da Silva;TI\n', admin)
    colaborador.refresh_from_db()
    assert colaborador.ativo is False
    assert colaborador.departamento.nome == 'TI'


def test_repetidos_no_arquivo_vale_a_primeira_linha(admin):
    resultado = _importar('Colaborador;Departamento\nAna Lima;TI\nÁNA  lima;RH\n', admin)
    assert [(i.linha, i.motivo) for i in resultado.duplicados] == [(3, 'Repete o nome da linha 2.')]
    assert _departamento_de('Ana Lima') == 'TI'
    assert not Departamento.objects.filter(nome='RH').exists()


def test_linhas_invalidas_nao_sao_importadas(admin):
    texto = 'Colaborador;Departamento\n;TI\n' + 'X' * 151 + ';\nAna;' + 'D' * 101 + '\nBruno;\n'
    resultado = _importar(texto, admin)
    assert [i.linha for i in resultado.invalidos] == [2, 3, 4]
    assert list(Colaborador.objects.values_list('nome', flat=True)) == ['Bruno']
    assert not Departamento.objects.exists()


def test_simulacao_nao_grava_e_resultado_e_o_mesmo(admin, colaborador):
    texto = 'Colaborador;Departamento\nAna Lima;Jurídico\nJosé da Silva;Comercial\n'
    simulado = _importar(texto, admin, simular=True)
    assert Colaborador.objects.count() == 1
    assert Departamento.objects.count() == 1
    colaborador.refresh_from_db()
    assert colaborador.departamento.nome == 'Financeiro'

    gravado = _importar(texto, admin, simular=False)
    for campo in ('criados', 'atualizados', 'sem_alteracao', 'departamentos_criados'):
        assert getattr(simulado, campo) == getattr(gravado, campo), campo


# ---------------------------------------------------------------------------
# Tela
# ---------------------------------------------------------------------------
def test_post_simulando_nao_grava_e_desmarca_a_simulacao(admin_client):
    response = admin_client.post(URL, {'arquivo': _arquivo('Colaborador;Departamento\nAna Lima;TI\n'), 'simular': 'on'})
    assert response.status_code == 200
    assert response.context['resultado'].simulado is True
    assert response.context['form']['simular'].value() is False
    assert not Colaborador.objects.exists()
    assert 'Simulação: nada foi gravado' in response.content.decode()


def test_post_gravando(admin_client):
    response = admin_client.post(URL, {'arquivo': _arquivo('Colaborador;Departamento\nAna Lima;TI\nBruno;\n')})
    assert response.status_code == 200
    assert response.context['resultado'].simulado is False
    assert response.context['form']['simular'].value() is True
    assert _departamento_de('Ana Lima') == 'TI'
    assert _departamento_de('Bruno') is None
    assert 'Importação concluída: 2 colaborador(es) criado(s)' in response.content.decode()


def test_post_arquivo_invalido_mostra_erro_no_campo(admin_client):
    response = admin_client.post(URL, {'arquivo': _arquivo('Pessoa;Setor\nAna;TI\n')})
    assert response.status_code == 200
    assert response.context['form'].errors['arquivo'] == ['Falta a coluna obrigatória: Colaborador.']
    assert response.context['resultado'] is None


def test_post_sem_arquivo(admin_client):
    response = admin_client.post(URL, {})
    assert response.context['form'].errors['arquivo'] == ['Selecione um arquivo.']
