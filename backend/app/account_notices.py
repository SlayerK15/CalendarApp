"""One 120-hour notice for accounts affected by the shared-sync rollout."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import AccountNoticeCampaign, Source, SyncRun, User

CAMPAIGN_ID = "main-account-sync-activation"
NOTICE_LIFETIME = timedelta(hours=120)
logger = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def calendar_ready(source, since):
    return bool(
        source and source.active and source.calendar_id and source.last_error is None
        and source.last_synced_at and source.last_synced_at >= since
    )


def refresh_account_notice(db, *, start=False, at=None):
    at = at or now()
    # Concurrent calendar workers must not overwrite one another's resolutions.
    campaign = db.scalar(
        select(AccountNoticeCampaign).where(AccountNoticeCampaign.id == CAMPAIGN_ID)
        .with_for_update().execution_options(populate_existing=True)
    )
    if campaign and campaign.closed_at:
        db.commit()
        return None
    if campaign and at >= campaign.expires_at:
        campaign.closed_at, campaign.closure_reason = at, "expired"
        campaign.targets, campaign.resolved_user_ids = {}, []
        db.commit()
        return None
    if campaign is None and not start:
        return None
    sources = {s.user_id: s for s in db.scalars(select(Source).execution_options(populate_existing=True))}
    targets = dict(campaign.targets) if campaign else {}
    if start:
        last_runs = {}
        for run in db.scalars(
            select(SyncRun).where(SyncRun.status != "running").order_by(SyncRun.started_at.desc(), SyncRun.id.desc())
        ):
            last_runs.setdefault(run.source_id, run.status)
        for user_id in db.scalars(select(User.id)):
            source = sources.get(user_id)
            if source is None or not source.active:
                targets[user_id] = "setup"
            elif last_runs.get(source.id) == "reconnect_required" and source.last_error:
                targets[user_id] = "reconnect"
    if campaign is None:
        if not targets:
            return None
        # Only the serialized shared-batch worker creates this fixed incident.
        campaign = AccountNoticeCampaign(
            id=CAMPAIGN_ID, created_at=at, expires_at=at + NOTICE_LIFETIME,
            targets=targets, resolved_user_ids=[],
        )
        db.add(campaign)
    existing_users = set(db.scalars(select(User.id)))
    resolved = {
        user_id for user_id in targets
        if user_id not in existing_users or calendar_ready(sources.get(user_id), campaign.created_at)
    }
    campaign.targets, campaign.resolved_user_ids = targets, sorted(resolved)
    if resolved == set(targets):
        campaign.closed_at, campaign.closure_reason = at, "resolved"
        campaign.targets, campaign.resolved_user_ids = {}, []
        db.commit()
        return None
    db.commit()
    return campaign


def refresh_notice_safely(db, *, start=False):
    # A notice failure must never turn a successful Calendar write into a failed sync.
    try:
        return refresh_account_notice(db, start=start)
    except Exception as exc:
        db.rollback()
        logger.warning("account notice update failed type=%s", type(exc).__name__)
        return None


def notice_payloads(db, user_id, *, admin=False):
    campaign = refresh_account_notice(db)
    if campaign is None:
        return None, None
    unresolved = set(campaign.targets) - set(campaign.resolved_user_ids)
    expires_at = campaign.expires_at.isoformat() + "Z"
    notice = None
    if user_id in unresolved:
        action = campaign.targets[user_id]
        notice = {
            "id": campaign.id,
            "action": action,
            "title": "Reconnect your timetable" if action == "reconnect" else "Finish connecting your timetable",
            "message": (
                "Your calendar cannot receive timetable updates until you reconnect Google. "
                "Reconnect to receive updates automatically when the main account syncs."
                if action == "reconnect" else
                "Choose your programme and section to receive automatic updates from the main timetable account."
            ),
            "expires_at": expires_at,
        }
    summary = {
        "id": campaign.id, "remaining": len(unresolved), "total": len(campaign.targets), "expires_at": expires_at,
    } if admin else None
    return notice, summary
