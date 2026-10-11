from apps.core.models import AuditoriaBase, NaoExcluidosManager, SoftDeleteMixin


def test_models_base_sao_abstratos():
    assert AuditoriaBase._meta.abstract
    assert SoftDeleteMixin._meta.abstract


def test_manager_padrao_oculta_excluidos():
    """Só a configuração dos managers; o comportamento com dados está em
    apps/ausencias/tests/test_soft_delete.py."""
    managers = {m.name: m for m in SoftDeleteMixin._meta.managers}

    assert isinstance(managers['objects'], NaoExcluidosManager)
    assert type(managers['todos']) is not NaoExcluidosManager
    assert SoftDeleteMixin._meta.managers[0].name == 'objects'
