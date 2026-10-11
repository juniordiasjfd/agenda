"""Vínculo usuário↔colaborador pelo convite (etapa 3)."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.colaboradores.models import Colaborador
from apps.usuarios import usuarios_service
from apps.usuarios.models import Convite, User

pytestmark = pytest.mark.django_db

URL_CONVITES = reverse('usuarios:convites')
SENHA_NOVA = 'Convite-Forte-2026!'
TEXTO_NEUTRO = 'Este link de convite não é válido.'


def _criar(client, colaborador, email='convidada@exemplo.com'):
    return client.post(URL_CONVITES, {
        'email': email, 'validade_dias': 7, 'colaborador': colaborador.pk if colaborador else '',
    })


def _aceitar(client, convite):
    return client.post(reverse('usuarios:convite_aceitar', args=[convite.token]), {
        'nome': 'Convidada Nova', 'password1': SENHA_NOVA, 'password2': SENHA_NOVA,
    })


def _convite_para(colaborador, email='convidada@exemplo.com', dias=7):
    return Convite.objects.create(
        email=email, colaborador=colaborador, expira_em=timezone.now() + timedelta(days=dias),
    )


@pytest.fixture
def admin_client(client, admin):
    client.force_login(admin)
    return client


@pytest.fixture
def colaborador(db):
    return Colaborador.objects.create(nome='Convidada Nova')


# ---------------------------------------------------------------------------
# Criação do convite
# ---------------------------------------------------------------------------
def test_criar_convite_com_colaborador(admin_client, colaborador):
    response = _criar(admin_client, colaborador)

    assert response.status_code == 302
    convite = Convite.objects.get()
    assert convite.colaborador == colaborador


def test_criar_convite_sem_colaborador_continua_funcionando(admin_client):
    _criar(admin_client, None)

    assert Convite.objects.get().colaborador is None


def test_select_so_tem_colaboradores_ativos_sem_usuario(admin_client, colaborador, gestor):
    Colaborador.objects.create(nome='Inativa', ativo=False)
    Colaborador.objects.create(nome='Já Vinculada', usuario=gestor)

    opcoes = list(admin_client.get(URL_CONVITES).context['form'].fields['colaborador'].queryset)

    assert opcoes == [colaborador]


def test_recusa_colaborador_inativo(admin_client):
    inativo = Colaborador.objects.create(nome='Inativa', ativo=False)

    response = _criar(admin_client, inativo)

    assert response.status_code == 200
    assert 'colaborador' in response.context['form'].errors
    assert not Convite.objects.exists()


def test_recusa_colaborador_ja_vinculado(admin_client, gestor):
    vinculado = Colaborador.objects.create(nome='Já Vinculada', usuario=gestor)

    response = _criar(admin_client, vinculado)

    assert response.status_code == 200
    assert 'colaborador' in response.context['form'].errors
    assert not Convite.objects.exists()


@pytest.mark.parametrize('ajuste, mensagem', [
    ({'ativo': False}, 'O colaborador escolhido está inativo.'),
    ('usuario', 'O colaborador escolhido já está vinculado a um usuário.'),
])
def test_servico_recusa_colaborador_que_mudou_depois_do_formulario(admin, colaborador, gestor, ajuste, mensagem):
    # O formulário validou com o colaborador disponível; o serviço confere de novo.
    campos = {'usuario': gestor} if ajuste == 'usuario' else ajuste
    Colaborador.objects.filter(pk=colaborador.pk).update(**campos)

    with pytest.raises(usuarios_service.ConviteRecusado, match=mensagem) as erro:
        usuarios_service.criar_convite('x@exemplo.com', 7, criado_por=admin, colaborador=colaborador)
    assert erro.value.campo == 'colaborador'
    assert not Convite.objects.exists()


def test_recusa_segundo_convite_pendente_para_o_mesmo_colaborador(admin_client, colaborador):
    _criar(admin_client, colaborador, email='primeiro@exemplo.com')

    response = _criar(admin_client, colaborador, email='segundo@exemplo.com')

    assert response.status_code == 200
    assert response.context['form'].errors['colaborador'] == [
        'Já existe um convite pendente para este colaborador. Reenvie ou revogue o convite existente.'
    ]
    assert Convite.objects.count() == 1


@pytest.mark.parametrize('anterior', ['expirado', 'usado_sem_vinculo'])
def test_permite_novo_convite_se_o_anterior_nao_esta_pendente(admin_client, colaborador, anterior):
    convite = _convite_para(colaborador, email='antigo@exemplo.com', dias=-1 if anterior == 'expirado' else 7)
    if anterior == 'usado_sem_vinculo':
        Convite.objects.filter(pk=convite.pk).update(usado_em=timezone.now())

    response = _criar(admin_client, colaborador)

    assert response.status_code == 302
    assert Convite.objects.filter(colaborador=colaborador).count() == 2


def test_detalhe_e_lista_mostram_o_colaborador(admin_client, colaborador):
    convite = _convite_para(colaborador)

    assert 'Convidada Nova' in admin_client.get(URL_CONVITES).content.decode()
    detalhe = admin_client.get(reverse('usuarios:convite_detalhe', args=[convite.pk])).content.decode()
    assert 'Convidada Nova' in detalhe


# ---------------------------------------------------------------------------
# Aceite
# ---------------------------------------------------------------------------
def test_aceite_vincula_o_colaborador(client, colaborador):
    convite = _convite_para(colaborador)

    response = _aceitar(client, convite)

    assert response.status_code == 302
    usuario = User.objects.get(email='convidada@exemplo.com')
    colaborador.refresh_from_db()
    assert colaborador.usuario == usuario
    convite.refresh_from_db()
    assert convite.usado_em is not None


def test_aceite_sem_colaborador_nao_vincula(client):
    convite = _convite_para(None)

    _aceitar(client, convite)

    usuario = User.objects.get(email='convidada@exemplo.com')
    assert not Colaborador.objects.filter(usuario=usuario).exists()


def test_aceite_com_colaborador_vinculado_no_meio_tempo_nao_consome(client, colaborador, gestor, caplog):
    convite = _convite_para(colaborador)
    Colaborador.objects.filter(pk=colaborador.pk).update(usuario=gestor)

    response = _aceitar(client, convite)

    assert response.status_code == 200
    assert TEXTO_NEUTRO in response.content.decode()
    assert not User.objects.filter(email='convidada@exemplo.com').exists()
    convite.refresh_from_db()
    assert convite.usado_em is None
    colaborador.refresh_from_db()
    assert colaborador.usuario == gestor


def test_servico_de_aceite_recusa_colaborador_vinculado_e_registra_log(colaborador, gestor, caplog):
    convite = _convite_para(colaborador)
    Colaborador.objects.filter(pk=colaborador.pk).update(usuario=gestor)

    with pytest.raises(usuarios_service.ConviteInvalido):
        usuarios_service.aceitar_convite(convite.token, nome='Convidada', senha=SENHA_NOVA)

    convite.refresh_from_db()
    assert convite.usado_em is None
    assert not User.objects.filter(email='convidada@exemplo.com').exists()
    assert 'já está vinculado a outro usuário' in caplog.text


def test_pagina_do_convite_neutra_se_colaborador_ja_vinculado(client, colaborador, gestor):
    convite = _convite_para(colaborador)
    Colaborador.objects.filter(pk=colaborador.pk).update(usuario=gestor)

    response = client.get(reverse('usuarios:convite_aceitar', args=[convite.token]))

    assert TEXTO_NEUTRO in response.content.decode()


def test_aceite_com_email_ja_cadastrado_nao_vincula(client, colaborador, usuario_ativo):
    convite = _convite_para(colaborador, email=usuario_ativo.email)

    response = _aceitar(client, convite)

    assert response.status_code == 200
    colaborador.refresh_from_db()
    assert colaborador.usuario is None
    convite.refresh_from_db()
    assert convite.usado_em is None


def test_colaborador_inativado_depois_do_convite_ainda_e_vinculado(client, colaborador):
    convite = _convite_para(colaborador)
    Colaborador.objects.filter(pk=colaborador.pk).update(ativo=False)

    _aceitar(client, convite)

    colaborador.refresh_from_db()
    assert colaborador.usuario.email == 'convidada@exemplo.com'
