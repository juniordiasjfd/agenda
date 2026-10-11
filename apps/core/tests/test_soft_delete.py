from apps.core.models import AuditoriaBase, NaoExcluidosManager, SoftDeleteMixin


def test_models_base_sao_abstratos():
    assert AuditoriaBase._meta.abstract
    assert SoftDeleteMixin._meta.abstract


def test_manager_padrao_oculta_excluidos():
    """O comportamento com dados é testado na etapa 5, com a Ausencia; aqui
    só a configuração dos managers."""
    managers = {m.name: m for m in SoftDeleteMixin._meta.managers}

    assert isinstance(managers['objects'], NaoExcluidosManager)
    assert type(managers['todos']) is not NaoExcluidosManager
    assert SoftDeleteMixin._meta.managers[0].name == 'objects'
