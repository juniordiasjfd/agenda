from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.colaboradores import colaboradores_service


class Command(BaseCommand):
    help = (
        'Carga inicial de colaboradores a partir de um arquivo .js no formato do legado '
        '(window.FUNCIONARIOS = [ "Nome", ... ];). Idempotente: quem já existe é ignorado.'
    )

    def add_arguments(self, parser):
        parser.add_argument('caminho', help='Arquivo .js com a lista de nomes (UTF-8).')
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Só mostra o resumo, sem gravar nada.',
        )

    def handle(self, *args, caminho, dry_run, **options):
        arquivo = Path(caminho)
        if not arquivo.is_file():
            raise CommandError(f'Arquivo não encontrado: {caminho}')
        try:
            texto = arquivo.read_text(encoding='utf-8-sig')
        except UnicodeDecodeError:
            raise CommandError(f'O arquivo não está em UTF-8: {caminho}')

        try:
            nomes = colaboradores_service.ler_nomes_js(texto)
        except colaboradores_service.ArquivoNomesInvalido as erro:
            raise CommandError(f'{caminho}: {erro}')

        resultado = colaboradores_service.carregar_colaboradores(nomes, dry_run=dry_run)

        if dry_run:
            self.stdout.write(self.style.WARNING('Simulação (--dry-run): nada foi gravado.'))
        self.stdout.write(f'Lidos: {resultado.lidos}')
        rotulo_criados = 'Seriam criados' if dry_run else 'Criados'
        self.stdout.write(self.style.SUCCESS(f'{rotulo_criados}: {len(resultado.criados)}'))
        self.stdout.write(f'Já existentes (ignorados): {len(resultado.existentes)}')
        self.stdout.write(f'Duplicados no arquivo (ignorados): {len(resultado.duplicados)}')
        for nome in resultado.duplicados:
            self.stdout.write(f'  - {nome}')
        if resultado.vazios:
            self.stdout.write(f'Vazios descartados: {resultado.vazios}')
