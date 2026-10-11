from django.utils.functional import SimpleLazyObject

from apps.usuarios import usuarios_service


def pendencias_admin(request):
    """Contador de cadastros pendentes para o menu do administrador.

    Só existe para superuser e é preguiçoso: o ``count()`` roda uma única vez,
    quando o template o usa (páginas públicas e de gestor não consultam).
    """
    user = getattr(request, 'user', None)
    if user is None or not user.is_superuser:
        return {}
    return {'cadastros_pendentes': SimpleLazyObject(usuarios_service.contar_pendentes)}
