from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.account_notices import CAMPAIGN_ID, NOTICE_LIFETIME, notice_payloads, refresh_account_notice
from app.db import Base
from app.models import AccountNoticeCampaign, Source, SyncRun, User


@pytest.fixture
def notice_db(monkeypatch):
    import app.account_notices as notices

    at = datetime(2026, 10, 31, 5)
    monkeypatch.setattr(notices, "now", lambda: at)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        for name in ["healthy", "reconnect", "setup"]:
            db.add(User(id=name, email=f"{name}@example.com", name="Student", tokens="unused"))
            db.add(Source(
                id=name, user_id=name, spreadsheet_id="sheet", sheet_gid="0", active=name != "setup",
                calendar_id=None if name == "setup" else f"calendar-{name}",
                last_synced_at=at - timedelta(days=1), last_error="Reconnect Google" if name == "reconnect" else None,
            ))
        db.add(SyncRun(id="expired-grant", source_id="reconnect", status="reconnect_required",
                       started_at=at - timedelta(hours=1), message="Reconnect Google"))
        db.commit()
        yield db, at
    engine.dispose()


def activate(db, user_id, at):
    source = db.get(Source, user_id)
    source.active, source.calendar_id = True, f"calendar-{user_id}"
    source.last_error, source.last_synced_at = None, at
    db.commit()


def test_only_affected_accounts_receive_their_own_note_and_admin_gets_counts(notice_db):
    db, at = notice_db
    campaign = refresh_account_notice(db, start=True)
    assert campaign.created_at == at and campaign.expires_at == at + timedelta(hours=120)
    assert campaign.targets == {"reconnect": "reconnect", "setup": "setup"}
    assert notice_payloads(db, "healthy") == (None, None)
    notice, summary = notice_payloads(db, "reconnect")
    assert summary is None and notice["action"] == "reconnect"
    assert "main account syncs" in notice["message"]
    setup, summary = notice_payloads(db, "setup")
    assert setup["action"] == "setup" and summary is None
    _, summary = notice_payloads(db, "healthy", admin=True)
    assert summary["remaining"] == 2 and summary["total"] == 2
    assert "targets" not in summary and "resolved_user_ids" not in summary


def test_retries_and_newly_affected_accounts_never_extend_the_original_deadline(notice_db):
    db, at = notice_db
    original = refresh_account_notice(db, start=True).expires_at
    db.add(User(id="new", name="New", email="new@example.com", tokens="unused"))
    db.commit()
    for hours in [1, 24, 70, 119]:
        campaign = refresh_account_notice(db, start=True, at=at + timedelta(hours=hours))
        assert campaign.expires_at == original
        assert campaign.targets["new"] == "setup"
    assert len(list(db.scalars(select(AccountNoticeCampaign)))) == 1


def test_individual_recovery_clears_own_note_then_everyone_active_closes_the_issue(notice_db):
    db, at = notice_db
    refresh_account_notice(db, start=True)
    activate(db, "reconnect", at + timedelta(minutes=1))
    assert notice_payloads(db, "reconnect") == (None, None)
    assert notice_payloads(db, "setup")[0] is not None
    assert notice_payloads(db, "healthy", admin=True)[1]["remaining"] == 1
    activate(db, "setup", at + timedelta(minutes=2))
    assert refresh_account_notice(db, start=True, at=at + timedelta(minutes=3)) is None
    campaign = db.get(AccountNoticeCampaign, CAMPAIGN_ID)
    assert campaign.closure_reason == "resolved" and campaign.closed_at is not None
    assert campaign.targets == {} and campaign.resolved_user_ids == []
    assert notice_payloads(db, "healthy", admin=True) == (None, None)


def test_selecting_a_class_without_a_successful_sync_does_not_falsely_clear_the_note(notice_db):
    db, at = notice_db
    refresh_account_notice(db, start=True)
    source = db.get(Source, "setup")
    source.active, source.calendar_id = True, "calendar-setup"
    source.last_error = None
    db.commit()
    assert notice_payloads(db, "setup")[0] is not None
    source.last_synced_at = at + timedelta(seconds=1)
    db.commit()
    assert notice_payloads(db, "setup")[0] is None


def test_note_self_destructs_at_exactly_120_hours_even_with_unresolved_accounts(notice_db, monkeypatch):
    import app.account_notices as notices

    db, at = notice_db
    refresh_account_notice(db, start=True)
    monkeypatch.setattr(notices, "now", lambda: at + NOTICE_LIFETIME - timedelta(microseconds=1))
    assert notice_payloads(db, "reconnect")[0] is not None
    monkeypatch.setattr(notices, "now", lambda: at + NOTICE_LIFETIME)
    assert notice_payloads(db, "reconnect", admin=True) == (None, None)
    campaign = db.get(AccountNoticeCampaign, CAMPAIGN_ID)
    assert campaign.closure_reason == "expired"
    assert campaign.targets == {} and campaign.resolved_user_ids == []
    # Expiring the notice never changes a user's authorization or calendar data.
    assert db.get(Source, "reconnect").last_error == "Reconnect Google"
    assert not db.get(Source, "setup").active
    assert db.get(User, "reconnect").tokens == "unused"


@pytest.mark.parametrize("closure", ["resolved", "expired"])
def test_closed_notice_cannot_be_recreated_by_later_scheduled_syncs(notice_db, closure):
    db, at = notice_db
    refresh_account_notice(db, start=True)
    if closure == "resolved":
        activate(db, "reconnect", at + timedelta(minutes=1))
        activate(db, "setup", at + timedelta(minutes=1))
        assert refresh_account_notice(db, at=at + timedelta(minutes=2)) is None
    else:
        assert refresh_account_notice(db, at=at + NOTICE_LIFETIME) is None
    db.add(User(id="later", name="Later", email="later@example.com", tokens="unused"))
    db.commit()
    assert refresh_account_notice(db, start=True, at=at + timedelta(days=10)) is None
    assert len(list(db.scalars(select(AccountNoticeCampaign)))) == 1
    assert db.get(AccountNoticeCampaign, CAMPAIGN_ID).closure_reason == closure


def test_successful_reconnection_updates_live_batch_counts(notice_db):
    from app.batch_sync import batch_summary
    from app.models import SyncBatch

    db, at = notice_db
    batch = SyncBatch(id="batch", requested_at=at, source_ids=["reconnect"], status="completed",
                      outcomes={"reconnect": "reconnect_required"}, message="Done")
    db.add(batch)
    db.commit()
    assert batch_summary(batch, db)["reconnect_required"] == 1
    activate(db, "reconnect", at + timedelta(minutes=1))
    summary = batch_summary(batch, db)
    assert summary["reconnect_required"] == 0 and summary["up_to_date"] == 1
