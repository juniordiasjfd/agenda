import logging
import re
from datetime import timedelta
from smtplib import SMTPException
from unittest import mock

import pytest
from django.contrib.auth.tokens import PasswordResetTokenGenerator, default_token_generator
from django.core import mail
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

pytestmark = pytest.mark.django_db

URL_PEDIR = reverse('usuarios:password_reset')
URL_ENVIADO = reverse('usuarios:password_reset_done')
URL_CONCLUIDO = reverse('usuarios:password_reset_complete')
NOVA_SENHA = 'Outra-Senha-Forte-77'


def _pedir(client, email):
    return client.post(URL_PEDIR, {'email': email})


def _link_do_email(mensagem):
    achado = re.search(r'https?://[^/\s]+(/senha/redefinir/[^/\s]+/[^/\s]+/)', mensagem.body)
    assert achado, mensagem.body
    return achado.group(1)


def _url_confirmar(usuario, token):
    uid = urlsafe_base64_encode(force_bytes(usuario.pk))
    return reverse('usuarios:password_reset_confirm', kwargs={'uidb64': uid, 'token': token})


def test_telas_publicas_abrem(client):
    assert client.get(URL_PEDIR).status_code == 200
    assert client.get(URL_ENVIADO).status_code == 200
    assert client.get(URL_CONCLUIDO).status_code == 200


def test_usuario_ativo_recebe_um_email_com_link_valido(client, usuario_ativo):
    response = _pedir(client, usuario_ativo.email)

    assert response.status_code == 302
    assert response.url == URL_ENVIADO
    assert len(mail.outbox) == 1
    mensagem = mail.outbox[0]
    assert mensagem.to == [usuario_ativo.email]
    assert mensagem.subject == 'Agenda — redefinição de senha'
    assert mensagem.from_email == 'Agenda <nao-responder@agenda.local>'
    assert '24 horas' in mensagem.body

    # O link leva à tela de nova senha (o Django troca o token por
    # "set-password" na sessão e redireciona).
    response = client.get(_link_do_email(mensagem), follow=True)
    assert response.status_code == 200
    assert response.context['validlink'] is True


def test_email_com_caixa_diferente_tambem_recebe(client, usuario_ativo):
    _pedir(client, 'ATIVO@Scriba.com.br')

    assert len(mail.outbox) == 1


def test_email_inexistente_mesma_resposta_e_nenhum_email(client, usuario_ativo):
    resposta_existente = _pedir(client, usuario_ativo.email)
    mail.outbox.clear()

    resposta_inexistente = _pedir(client, 'ninguem@scriba.com.br')

    assert resposta_inexistente.status_code == resposta_existente.status_code == 302
    assert resposta_inexistente.url == resposta_existente.url == URL_ENVIADO
    assert len(mail.outbox) == 0


@pytest.mark.parametrize('fixture', ['usuario_pendente', 'usuario_desativado'])
def test_usuario_inativo_nao_recebe_email(client, request, fixture):
    usuario = request.getfixturevalue(fixture)

    response = _pedir(client, usuario.email)

    assert response.status_code == 302
    assert response.url == URL_ENVIADO
    assert len(mail.outbox) == 0


def test_token_invalido_recusado(client, usuario_ativo):
    response = client.get(_url_confirmar(usuario_ativo, 'token-invalido'))

    assert response.status_code == 200
    assert response.context['validlink'] is False
    assert 'Link inválido ou expirado' in response.content.decode()


def test_token_expirado_recusado(client, usuario_ativo):
    token = default_token_generator.make_token(usuario_ativo)
    agora = PasswordResetTokenGenerator()._now()

    with mock.patch.object(PasswordResetTokenGenerator, '_now', return_value=agora + timedelta(hours=25)):
        response = client.get(_url_confirmar(usuario_ativo, token))

    assert response.status_code == 200
    assert response.context['validlink'] is False


def test_token_dentro_de_24h_aceito(client, usuario_ativo):
    token = default_token_generator.make_token(usuario_ativo)
    agora = PasswordResetTokenGenerator()._now()

    with mock.patch.object(PasswordResetTokenGenerator, '_now', return_value=agora + timedelta(hours=23)):
        response = client.get(_url_confirmar(usuario_ativo, token), follow=True)

    assert response.context['validlink'] is True


def test_nova_senha_funciona_no_login(client, usuario_ativo, senha):
    _pedir(client, usuario_ativo.email)
    response = client.get(_link_do_email(mail.outbox[0]), follow=True)
    url_definir = response.redirect_chain[-1][0]

    response = client.post(url_definir, {'new_password1': NOVA_SENHA, 'new_password2': NOVA_SENHA})

    assert response.status_code == 302
    assert response.url == URL_CONCLUIDO
    usuario_ativo.refresh_from_db()
    assert usuario_ativo.check_password(NOVA_SENHA)

    login = reverse('usuarios:login')
    assert client.post(login, {'username': usuario_ativo.email, 'password': senha}).status_code == 200
    assert client.post(login, {'username': usuario_ativo.email, 'password': NOVA_SENHA}).status_code == 302


def test_link_nao_pode_ser_reusado(client, usuario_ativo):
    _pedir(client, usuario_ativo.email)
    link = _link_do_email(mail.outbox[0])
    response = client.get(link, follow=True)
    client.post(response.redirect_chain[-1][0], {'new_password1': NOVA_SENHA, 'new_password2': NOVA_SENHA})

    response = client.get(link, follow=True)

    assert response.context['validlink'] is False


def test_senha_fraca_recusada(client, usuario_ativo, senha):
    _pedir(client, usuario_ativo.email)
    response = client.get(_link_do_email(mail.outbox[0]), follow=True)
    url_definir = response.redirect_chain[-1][0]

    response = client.post(url_definir, {'new_password1': '12345678', 'new_password2': '12345678'})

    assert response.status_code == 200
    assert response.context['form'].errors['new_password2']
    usuario_ativo.refresh_from_db()
    assert usuario_ativo.check_password(senha)


def test_falha_no_envio_nao_derruba_e_registra_log(client, usuario_ativo, caplog):
    with mock.patch('django.core.mail.EmailMultiAlternatives.send', side_effect=SMTPException('SMTP fora')):
        with caplog.at_level(logging.ERROR, logger='django.contrib.auth'):
            response = _pedir(client, usuario_ativo.email)

    assert response.status_code == 302
    assert response.url == URL_ENVIADO
    assert any('password reset email' in r.getMessage() for r in caplog.records)
