import pytest

from services.neo_desk.research_jobs import get_job


def test_job_identity_is_owner_bound():
    with pytest.raises(ValueError):
        get_job("foreign", "missing")


def test_missing_observation_error_is_actionable_and_owner_bound(monkeypatch):
    from test_replay import request

    import services.neo_desk.research_jobs as jobs
    from database import neo_history_db as db

    db.init_db()
    identity = "research-error-fixture"
    db.db_session.query(db.NeoResearchJob).filter_by(id=identity).delete()
    db.db_session.add(
        db.NeoResearchJob(id=identity, owner="job-fixture", status="queued", request={})
    )
    db.db_session.commit()

    def fail(_):
        raise ValueError("Index 15-minute and option 1-minute observations are required.")

    monkeypatch.setattr(jobs, "load_dataset", fail)
    assert jobs.slots.acquire(blocking=False)
    jobs._execute("job-fixture", identity, request())
    result = jobs.get_job("job-fixture", identity)
    assert result["status"] == "failed" and "verified 15-minute NIFTY" in result["error"]
    with pytest.raises(ValueError):
        jobs.get_job("foreign", identity)
    db.db_session.query(db.NeoResearchJob).filter_by(id=identity).delete()
    db.db_session.commit()
