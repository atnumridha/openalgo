import pytest
from services.neo_desk.datasets import list_datasets,load_dataset
def test_unknown_dataset_and_traversal_are_refused():
    with pytest.raises(ValueError):load_dataset('../../.env')
def test_real_registry_never_advertises_synthetic_profit_fixtures():
    assert all(not x['source'].get('synthetic',False) for x in list_datasets())
