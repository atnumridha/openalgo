import pytest
from services.neo_desk.research_jobs import get_job


def test_job_identity_is_owner_bound():
    with pytest.raises(ValueError):
        get_job("foreign", "missing")
