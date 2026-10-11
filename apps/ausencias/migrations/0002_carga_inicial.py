from django.db import migrations

# Cores do legado (Painel de ausências.html, --c0..--c3 do tema claro).
TIPOS = [
    ('Férias', '#2f5fd0', 1),
    ('Banco de horas', '#d9822b', 2),
    ('Licença', '#8a4fbf', 3),
    ('Outro', '#6b7a89', 4),
]

# (nome, ordem, padrao, conta_como_ausencia)
SITUACOES = [
    ('Planejado', 1, True, True),
    ('Aprovado', 2, False, True),
    ('Realizado', 3, False, True),
    ('Cancelado', 4, False, False),
]


def criar_carga_inicial(apps, schema_editor):
    TipoAusencia = apps.get_model('ausencias', 'TipoAusencia')
    SituacaoAusencia = apps.get_model('ausencias', 'SituacaoAusencia')
    for nome, cor, ordem in TIPOS:
        TipoAusencia.objects.get_or_create(nome=nome, defaults={'cor': cor, 'ordem': ordem})
    for nome, ordem, padrao, conta in SITUACOES:
        SituacaoAusencia.objects.get_or_create(
            nome=nome,
            defaults={'ordem': ordem, 'padrao': padrao, 'conta_como_ausencia': conta},
        )


def remover_carga_inicial(apps, schema_editor):
    TipoAusencia = apps.get_model('ausencias', 'TipoAusencia')
    SituacaoAusencia = apps.get_model('ausencias', 'SituacaoAusencia')
    TipoAusencia.objects.filter(nome__in=[nome for nome, _, _ in TIPOS]).delete()
    SituacaoAusencia.objects.filter(nome__in=[nome for nome, *_ in SITUACOES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('ausencias', '0001_tipos_situacoes'),
    ]

    operations = [
        migrations.RunPython(criar_carga_inicial, remover_carga_inicial),
    ]
