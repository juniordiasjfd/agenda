import smtplib
from io import StringIO

import pytest
from django.core import mail
from django.core.management import CommandError, call_command


def _rodar(*args):
    saida = StringIO()
    call_command('testar_email', *args, stdout=saida)
    return saida.getvalue()


def test_envia_para_o_endereco_informado(settings):
    settings.DEFAULT_FROM_EMAIL = 'Agenda <nao-responder@agenda.local>'

    saida = _rodar('fulana@scriba.com.br')

    assert len(mail.outbox) == 1
    mensagem = mail.outbox[0]
    assert mensagem.to == ['fulana@scriba.com.br']
    assert mensagem.from_email == 'Agenda <nao-responder@agenda.local>'
    assert mensagem.subject == 'Agenda — e-mail de teste'
    assert 'Enviado para fulana@scriba.com.br.' in saida


def test_mostra_a_configuracao_sem_a_senha(settings):
    settings.EMAIL_HOST = 'smtp.exemplo.com'
    settings.EMAIL_PORT = 587
    settings.EMAIL_HOST_USER = 'conta-smtp'
    settings.EMAIL_HOST_PASSWORD = 'segredo-nao-mostrar'
    settings.EMAIL_USE_TLS = True

    saida = _rodar('fulana@scriba.com.br')

    assert 'Servidor: smtp.exemplo.com:587' in saida
    assert 'Usuário: conta-smtp' in saida
    assert 'Senha definida: sim' in saida
    assert 'TLS: True' in saida
    assert 'segredo-nao-mostrar' not in saida


def test_mostra_o_erro_real_do_smtp(monkeypatch):
    def recusa(*args, **kwargs):
        raise smtplib.SMTPAuthenticationError(535, b'5.7.8 Username and Password not accepted')

    monkeypatch.setattr('apps.core.management.commands.testar_email.send_mail', recusa)

    with pytest.raises(CommandError) as erro:
        _rodar('fulana@scriba.com.br')

    mensagem = str(erro.value)
    assert 'SMTPAuthenticationError' in mensagem
    assert '535' in mensagem
    assert 'Username and Password not accepted' in mensagem
    assert isinstance(erro.value.__cause__, smtplib.SMTPAuthenticationError)


def test_endereco_invalido_nao_envia():
    with pytest.raises(CommandError, match='E-mail inválido'):
        _rodar('nao-e-email')

    assert mail.outbox == []
