import logging

from django.core import mail

from apps.core.email_service import enviar_email

# Qualquer par assunto/corpo existente serve; usa o da redefinição de senha.
ASSUNTO = 'usuarios/emails/redefinir_senha_assunto.txt'
CORPO = 'usuarios/emails/redefinir_senha.txt'
CONTEXTO = {
    'email': 'fulana@scriba.com.br', 'protocol': 'http', 'domain': 'testserver',
    'uid': 'MQ', 'token': 'abc-123',
}


def test_envia_com_remetente_padrao_e_assunto_em_uma_linha(settings):
    settings.DEFAULT_FROM_EMAIL = 'Agenda <nao-responder@agenda.local>'

    assert enviar_email(ASSUNTO, CORPO, CONTEXTO, ['fulana@scriba.com.br']) is True

    assert len(mail.outbox) == 1
    mensagem = mail.outbox[0]
    assert mensagem.to == ['fulana@scriba.com.br']
    assert mensagem.from_email == 'Agenda <nao-responder@agenda.local>'
    assert mensagem.subject == 'Agenda — redefinição de senha'
    assert 'http://testserver/' in mensagem.body


def test_sem_destinatario_nao_envia():
    assert enviar_email(ASSUNTO, CORPO, CONTEXTO, ['', None]) is False
    assert mail.outbox == []


def test_falha_no_envio_nao_propaga(monkeypatch, caplog):
    def explode(*args, **kwargs):
        raise ConnectionRefusedError('SMTP fora do ar')

    monkeypatch.setattr('apps.core.email_service.send_mail', explode)

    with caplog.at_level(logging.ERROR, logger='apps.core.email_service'):
        assert enviar_email(ASSUNTO, CORPO, CONTEXTO, ['fulana@scriba.com.br']) is False

    assert 'Falha ao enviar e-mail' in caplog.text
