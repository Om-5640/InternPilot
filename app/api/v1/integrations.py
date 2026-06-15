"""Module 8 — Integration endpoints (Gmail inbox sync)."""
from __future__ import annotations

import logging
import uuid

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.application import Application
from app.models.company import Company
from app.models.outcome import Outcome
from app.models.posting import Posting
from app.models.user import User
from app.schemas.application import GmailSyncResponse
from app.services.cohort_service import CohortService

router = APIRouter(tags=["integrations"])

logger = logging.getLogger(__name__)

_GMAIL_MESSAGES_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
_GMAIL_MESSAGE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/{id}"

# Days back to search for email replies
_LOOKBACK_DAYS: int = 30


async def _fetch_gmail_message_headers(
    client: httpx.AsyncClient,
    message_id: str,
    token: str,
) -> dict[str, str]:
    """Return {header_name_lower: value} for From and Subject."""
    try:
        resp = await client.get(
            _GMAIL_MESSAGE_URL.format(id=message_id),
            headers={"Authorization": f"Bearer {token}"},
            params={"format": "metadata", "metadataHeaders": ["From", "Subject"]},
            timeout=5.0,
        )
        if resp.status_code != 200:
            return {}
        data = resp.json()
        headers: dict[str, str] = {}
        for h in data.get("payload", {}).get("headers", []):
            headers[h["name"].lower()] = h.get("value", "")
        return headers
    except Exception:
        return {}


@router.post("/integrations/gmail/sync", response_model=GmailSyncResponse)
async def gmail_sync(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GmailSyncResponse:
    """Scan Gmail inbox for replies to applied internship positions.

    Graceful no-op (detected=0) when:
    - user.consent["gmail"] is False
    - user.gmail_token is None or missing access_token
    - Gmail API returns non-200

    Privacy: only reads threads for companies the user themselves applied to.
    """
    consent: dict[str, bool] = current_user.consent or {}
    if not consent.get("gmail", False):
        return GmailSyncResponse(detected=0)

    token_data: dict[str, str] | None = current_user.gmail_token
    if not token_data or not token_data.get("access_token"):
        return GmailSyncResponse(detected=0)

    access_token = token_data["access_token"]

    # Load user's applied applications + their company domains/names
    rows = (
        await db.execute(
            select(Application, Posting, Company)
            .join(Posting, Application.posting_id == Posting.id)
            .join(Company, Posting.company_id == Company.id)
            .where(Application.user_id == current_user.id)
            .where(Application.status != "saved")
        )
    ).all()

    if not rows:
        return GmailSyncResponse(detected=0)

    # Build lookup: company identifier → list of application_ids
    # Use domain if set, else normalized_name
    company_to_apps: dict[str, list[tuple[uuid.UUID, uuid.UUID]]] = {}
    for app, posting, company in rows:
        key = (company.domain or company.normalized_name or "").lower().strip()
        if key:
            company_to_apps.setdefault(key, []).append((app.id, posting.company_id))

    if not company_to_apps:
        return GmailSyncResponse(detected=0)

    # Build Gmail search query: from: any known domain
    from_parts = " OR ".join(f"from:{k}" for k in list(company_to_apps.keys())[:20])
    query = f"({from_parts}) newer_than:{_LOOKBACK_DAYS}d"

    detected = 0
    affected_company_ids: set[uuid.UUID] = set()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            search_resp = await client.get(
                _GMAIL_MESSAGES_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                params={"q": query, "maxResults": 50},
            )
            if search_resp.status_code != 200:
                logger.warning(
                    "Gmail search returned %s for user %s",
                    search_resp.status_code,
                    current_user.id,
                )
                return GmailSyncResponse(detected=0)

            messages = search_resp.json().get("messages", [])

            for msg in messages:
                headers = await _fetch_gmail_message_headers(
                    client, msg["id"], access_token
                )
                from_header = headers.get("from", "").lower()

                matched_apps: list[tuple[uuid.UUID, uuid.UUID]] = []
                for key, app_pairs in company_to_apps.items():
                    if key and key in from_header:
                        matched_apps.extend(app_pairs)

                for application_id, company_id in matched_apps:
                    existing = (
                        await db.execute(
                            select(Outcome).where(
                                Outcome.application_id == application_id,
                                Outcome.source == "gmail",
                            )
                        )
                    ).scalar_one_or_none()

                    if existing is None:
                        outcome = Outcome(
                            application_id=application_id,
                            outcome_type="responded",
                            responded=True,
                            time_to_response_hours=None,
                            source="gmail",
                        )
                        db.add(outcome)
                        affected_company_ids.add(company_id)
                        detected += 1

        if detected > 0:
            await db.flush()
            cohort_svc = CohortService(db)
            for company_id in affected_company_ids:
                await cohort_svc.recompute_company_response(company_id)
        # recompute_company_response commits; if no outcomes were detected, commit anyway
        if not affected_company_ids:
            await db.commit()

    except httpx.HTTPError as exc:
        logger.warning("Gmail sync HTTP error for user %s: %s", current_user.id, exc)
        return GmailSyncResponse(detected=0)

    return GmailSyncResponse(detected=detected)
