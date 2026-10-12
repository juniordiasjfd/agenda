from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.utils import timezone


class Command(BaseCommand):
    help = (
        'Envia um e-mail de teste para o endereço informado usando a configuração '
        'atual (variáveis EMAIL_*). Ao contrário do envio normal da aplicação, '
        'não engole a exceção: mostra o erro real do SMTP.'
    )

    def add_arguments(self, parser):
        parser.add_argument('destinatario', help='E-mail que deve receber o teste.')

    def handle(self, *args, destinatario, **options):
        try:
            validate_email(destinatario)
        except ValidationError:
            raise CommandError(f'E-mail inválido: {destinatario}')

        # Configuração em uso — nunca a senha, só se ela está definida.
        self.stdout.write(f'Backend: {settings.EMAIL_BACKEND}')
        self.stdout.write(f'Servidor: {settings.EMAIL_HOST}:{settings.EMAIL_PORT}')
        self.stdout.write(f'Usuário: {settings.EMAIL_HOST_USER or "(vazio)"}')
        self.stdout.write(f'Senha definida: {"sim" if settings.EMAIL_HOST_PASSWORD else "não"}')
        self.stdout.write(f'TLS: {settings.EMAIL_USE_TLS}  SSL: {settings.EMAIL_USE_SSL}')
        self.stdout.write(f'Timeout: {settings.EMAIL_TIMEOUT} s')
        self.stdout.write(f'Remetente: {settings.DEFAULT_FROM_EMAIL}')

        agora = timezone.localtime().strftime('%d/%m/%Y %H:%M:%S')
        try:
            send_mail(
                'Agenda — e-mail de teste',
                f'E-mail de teste enviado pelo comando testar_email em {agora}.\n'
                'Se você recebeu esta mensagem, o envio de e-mails da Agenda está funcionando.\n',
                settings.DEFAULT_FROM_EMAIL,
                [destinatario],
                fail_silently=False,
            )
        except Exception as erro:
            # Use --traceback para ver a pilha completa.
            raise CommandError(f'Falha no envio: {type(erro).__name__}: {erro}') from erro

        self.stdout.write(self.style.SUCCESS(f'Enviado para {destinatario}.'))
