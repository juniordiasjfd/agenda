import pytest
from django.contrib.auth.models import Group
from django.core import mail
from django.urls import reverse

from apps.usuarios import usuarios_service
from apps.usuarios.models import User

pytestmark = pytest.mark.django_db

URL_PENDENTES = reverse('usuarios:pendentes')
URL_LOGIN = reverse('usuarios:login')
SENHA_NOVA = 'Cadastro-Forte-2026!'


def _aprovar(usuario):
    return reverse('usuarios:aprovar_usuario', args=[usuario.pk])


def _rejeitar(usuario):
    return reverse('usuarios:rejeitar_usuario', args=[usuario.pk])


def _mensagens(response):
    return [str(m) for m in response.wsgi_request._messages]


@pytest.fixture
def admin_client(client, admin):
    client.force_login(admin)
    return client


# ---------------------------------------------------------------------------
# Notificação aos administradores (no autocadastro)
# ---------------------------------------------------------------------------
def _cadastrar(client):
    return client.post(reverse('usuarios:cadastro'), {
        'nome': 'Nova Pessoa', 'email': 'nova@scriba.com.br',
        'password1': SENHA_NOVA, 'password2': SENHA_NOVA,
    })


def test_autocadastro_avisa_admins_ativos_com_email(client, admin, senha):
    User.objects.create_superuser('admin2@scriba.com.br', senha, nome='Admin 2')
    inativo = User.objects.create_superuser('admin3@scriba.com.br', senha, nome='Admin 3')
    User.objects.filter(pk=inativo.pk).update(is_active=False)

    _cadastrar(client)

    assert len(mail.outbox) == 1
    mensagem = mail.outbox[0]
    assert sorted(mensagem.to) == ['admin2@scriba.com.br', 'admin@scriba.com.br']
    assert 'aguardando aprovação' in mensagem.subject
    assert 'nova@scriba.com.br' in mensagem.body
    assert f'http://testserver{URL_PENDENTES}' in mensagem.body


def test_autocadastro_sem_admin_nao_envia(client):
    response = _cadastrar(client)

    assert response.status_code == 302
    assert mail.outbox == []


def test_falha_de_smtp_nao_impede_cadastro(client, admin, monkeypatch):
    def explode(*args, **kwargs):
        raise ConnectionRefusedError('SMTP fora do ar')

    monkeypatch.setattr('apps.core.email_service.send_mail', explode)

    response = _cadastrar(client)

    assert response.status_code == 302
    assert response.url == reverse('usuarios:cadastro_recebido')
    assert User.objects.filter(email='nova@scriba.com.br', is_active=False).exists()


def test_email_duplicado_nao_avisa_admins(client, admin, usuario_ativo):
    client.post(reverse('usuarios:cadastro'), {
        'nome': 'X', 'email': 'ativo@scriba.com.br', 'password1': SENHA_NOVA, 'password2': SENHA_NOVA,
    })

    assert mail.outbox == []


# ---------------------------------------------------------------------------
# Acesso
# ---------------------------------------------------------------------------
def test_anonimo_vai_para_login(client, usuario_pendente):
    for url, metodo in [(URL_PENDENTES, client.get), (_aprovar(usuario_pendente), client.post),
                        (_rejeitar(usuario_pendente), client.post)]:
        response = metodo(url)
        assert response.status_code == 302
        assert response.url.startswith(URL_LOGIN)
    usuario_pendente.refresh_from_db()
    assert usuario_pendente.aguardando_aprovacao


def test_gestor_recebe_403(client, gestor, usuario_pendente):
    client.force_login(gestor)

    assert client.get(URL_PENDENTES).status_code == 403
    assert client.post(_aprovar(usuario_pendente)).status_code == 403
    assert client.post(_rejeitar(usuario_pendente)).status_code == 403
    usuario_pendente.refresh_from_db()
    assert usuario_pendente.aguardando_aprovacao


def test_admin_ve_a_lista(admin_client, usuario_pendente, usuario_ativo, usuario_desativado):
    response = admin_client.get(URL_PENDENTES)

    assert response.status_code == 200
    assert list(response.context['pendentes']) == [usuario_pendente]
    conteudo = response.content.decode()
    assert usuario_pendente.email in conteudo
    assert usuario_desativado.email not in conteudo


def test_superuser_inativo_sem_aprovado_em_nao_e_pendente(admin_client, senha):
    estranho = User.objects.create_superuser('root@scriba.com.br', senha, nome='Root')
    User.objects.filter(pk=estranho.pk).update(is_active=False, aprovado_em=None)

    response = admin_client.get(URL_PENDENTES)

    assert list(response.context['pendentes']) == []


@pytest.mark.parametrize('acao', ['aprovar_usuario', 'rejeitar_usuario'])
def test_acoes_so_por_post(admin_client, usuario_pendente, acao):
    response = admin_client.get(reverse(f'usuarios:{acao}', args=[usuario_pendente.pk]))

    assert response.status_code == 405
    usuario_pendente.refresh_from_db()
    assert usuario_pendente.aguardando_aprovacao


@pytest.mark.parametrize('acao', ['aprovar_usuario', 'rejeitar_usuario'])
def test_usuario_inexistente_404(admin_client, acao):
    assert admin_client.post(reverse(f'usuarios:{acao}', args=[999999])).status_code == 404


# ---------------------------------------------------------------------------
# Aprovar
# ---------------------------------------------------------------------------
def test_aprovar(admin_client, usuario_pendente):
    response = admin_client.post(_aprovar(usuario_pendente))

    assert response.status_code == 302
    assert response.url == URL_PENDENTES
    usuario_pendente.refresh_from_db()
    assert usuario_pendente.is_active
    assert usuario_pendente.aprovado_em is not None
    assert list(usuario_pendente.groups.values_list('name', flat=True)) == ['Gestor']
    assert len(mail.outbox) == 1
    mensagem = mail.outbox[0]
    assert mensagem.to == [usuario_pendente.email]
    assert f'http://testserver{URL_LOGIN}' in mensagem.body


def test_aprovado_consegue_entrar(admin_client, client, usuario_pendente, senha):
    admin_client.post(_aprovar(usuario_pendente))
    admin_client.logout()

    response = client.post(URL_LOGIN, {'username': usuario_pendente.email, 'password': senha})

    assert response.status_code == 302


def test_aprovar_duas_vezes_e_inofensivo(admin_client, usuario_pendente):
    admin_client.post(_aprovar(usuario_pendente))
    usuario_pendente.refresh_from_db()
    aprovado_em = usuario_pendente.aprovado_em

    response = admin_client.post(_aprovar(usuario_pendente))

    assert response.status_code == 302
    assert 'já estava aprovado' in _mensagens(response)[-1]
    usuario_pendente.refresh_from_db()
    assert usuario_pendente.aprovado_em == aprovado_em
    assert usuario_pendente.groups.count() == 1
    assert len(mail.outbox) == 1


def test_aprovar_nao_reativa_desativado(admin_client, usuario_desativado):
    response = admin_client.post(_aprovar(usuario_desativado))

    assert 'não está aguardando aprovação' in _mensagens(response)[0]
    usuario_desativado.refresh_from_db()
    assert not usuario_desativado.is_active
    assert mail.outbox == []


def test_falha_de_smtp_nao_impede_aprovacao(admin_client, usuario_pendente, monkeypatch):
    def explode(*args, **kwargs):
        raise ConnectionRefusedError('SMTP fora do ar')

    monkeypatch.setattr('apps.core.email_service.send_mail', explode)

    response = admin_client.post(_aprovar(usuario_pendente))

    assert response.status_code == 302
    usuario_pendente.refresh_from_db()
    assert usuario_pendente.is_active


# ---------------------------------------------------------------------------
# Rejeitar
# ---------------------------------------------------------------------------
def test_rejeitar_exclui_pendente(admin_client, usuario_pendente):
    response = admin_client.post(_rejeitar(usuario_pendente))

    assert response.status_code == 302
    assert not User.objects.filter(pk=usuario_pendente.pk).exists()


@pytest.mark.parametrize('fixture', ['usuario_ativo', 'usuario_desativado', 'admin'])
def test_rejeitar_nao_exclui_quem_nao_e_pendente(admin_client, request, fixture):
    usuario = request.getfixturevalue(fixture)

    response = admin_client.post(_rejeitar(usuario))

    assert response.status_code == 302
    assert 'não foi excluído' in _mensagens(response)[0]
    assert User.objects.filter(pk=usuario.pk).exists()


def test_rejeitar_superuser_inativo_sem_aprovado_em_nao_exclui(senha):
    estranho = User.objects.create_superuser('root@scriba.com.br', senha, nome='Root')
    User.objects.filter(pk=estranho.pk).update(is_active=False, aprovado_em=None)

    with pytest.raises(usuarios_service.UsuarioNaoPendente):
        usuarios_service.rejeitar_usuario(estranho.pk)

    assert User.objects.filter(pk=estranho.pk).exists()


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------
def test_menu_do_admin_mostra_contador(admin_client, usuario_pendente):
    response = admin_client.get(reverse('core:home'))

    conteudo = response.content.decode()
    assert URL_PENDENTES in conteudo
    assert str(response.context['cadastros_pendentes']) == '1'


def test_menu_do_gestor_nao_tem_pendentes(client, gestor, usuario_pendente):
    client.force_login(gestor)

    response = client.get(reverse('core:home'))

    assert URL_PENDENTES not in response.content.decode()
    assert 'cadastros_pendentes' not in response.context


def test_contador_e_uma_consulta_so(admin_client, usuario_pendente, django_assert_num_queries):
    # Sessão + usuário + o count() do menu (que aparece duas vezes no HTML).
    with django_assert_num_queries(3):
        admin_client.get(reverse('core:home'))


def test_grupo_gestor_e_o_do_service():
    assert Group.objects.filter(name=usuarios_service.NOME_GRUPO_GESTOR).exists()
