from django.conf import settings
from django.db import models
from django.utils import timezone


class AuditoriaBase(models.Model):
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    # Usamos settings.AUTH_USER_MODEL para referenciar o modelo de usuário customizado
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(class)s_criados",
        verbose_name="Criado por"
    )
    atualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(class)s_atualizados",
        verbose_name="Atualizado por"
    )

    class Meta:
        abstract = True


class NaoExcluidosManager(models.Manager):
    """Manager padrão dos models com exclusão lógica: oculta os excluídos."""

    def get_queryset(self):
        return super().get_queryset().filter(excluido_em__isnull=True)


class SoftDeleteMixin(models.Model):
    """Exclusão lógica: ``excluido_em``/``excluido_por`` em vez de apagar a linha.

    ``objects`` (manager padrão) oculta os excluídos; ``todos`` inclui. Usar
    junto com ``AuditoriaBase``: ``class Ausencia(SoftDeleteMixin, AuditoriaBase)``.
    Quem decide se pode excluir/restaurar é a camada de serviço; aqui ficam só
    as operações sobre o registro.
    """
    excluido_em = models.DateTimeField(null=True, blank=True, verbose_name="Excluído em")
    excluido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(class)s_excluidos",
        verbose_name="Excluído por"
    )

    # O primeiro manager declarado é o padrão (_default_manager).
    objects = NaoExcluidosManager()
    todos = models.Manager()

    class Meta:
        abstract = True

    @property
    def esta_excluido(self):
        return self.excluido_em is not None

    def excluir(self, usuario):
        self.excluido_em = timezone.now()
        self.excluido_por = usuario
        self.save(update_fields=['excluido_em', 'excluido_por'])

    def restaurar(self):
        self.excluido_em = None
        self.excluido_por = None
        self.save(update_fields=['excluido_em', 'excluido_por'])
