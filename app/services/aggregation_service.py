"""AggregationService — Module 2.

Postings and companies are GLOBAL shared data; this service does NOT extend
BaseService and does NOT scope queries to a user_id.
"""
from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import APIError
from app.llm.embeddings import embed
from app.models.company import Company
from app.models.posting import Posting
from app.schemas.posting import PostingSchema, coerce_posting_schema
from app.sources.adzuna import AdzunaSource
from app.sources.ashby import AshbySource
from app.sources.base import RawPosting, Source
from app.sources.firecrawl_india import IndiaFirecrawlSource
from app.sources.greenhouse import GreenhouseSource
from app.sources.normalize import normalize, normalize_company_name
from app.sources.remoteok import RemoteOKSource
from app.sources.remotive import RemotiveSource
from app.sources.usajobs import USAJobsSource

logger = logging.getLogger(__name__)


class AggregationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Public — refresh all sources
    # ------------------------------------------------------------------

    async def refresh(self) -> dict[str, int]:
        # India source requires both Firecrawl key (for scraping) AND an LLM (for extraction).
        # It is wired up lazily so the LLM router's cooldown logic is shared with the pipeline.
        _india_llm_fn = None
        if settings.FIRECRAWL_API_KEY:
            from app.llm.router import complete as _complete
            _india_llm_fn = _complete

        sources: list[Source] = [
            GreenhouseSource(),
            AshbySource(),
            RemoteOKSource(),
            RemotiveSource(),
            USAJobsSource(),   # all-field government internships (requires USAJOBS_API_KEY)
            AdzunaSource(),    # cross-industry aggregator (requires ADZUNA_APP_ID/KEY)
            IndiaFirecrawlSource(  # Indian sites: Internshala, LetsIntern (requires FIRECRAWL_API_KEY)
                api_key=settings.FIRECRAWL_API_KEY,
                llm_fn=_india_llm_fn,
            ),
        ]

        # Fetch all sources concurrently; a single failing source must not abort the run
        raw_results = await asyncio.gather(
            *[s.fetch() for s in sources],
            return_exceptions=True,
        )

        all_raws: list[RawPosting] = []
        for i, result in enumerate(raw_results):
            if isinstance(result, BaseException):
                logger.warning("source_failed source=%s error=%s", sources[i].name, result)
            elif isinstance(result, list):
                all_raws.extend(result)

        # Apply internship filter when configured
        if settings.INTERNSHIP_FILTER:
            # \bintern(ship)? matches "Intern" and "Internship" as whole words
            # but NOT "Internal" or "International"
            all_raws = [
                r for r in all_raws
                if re.search(r"\bintern(ship)?\b", r["title"], re.IGNORECASE)
            ]

        # Process sequentially — avoids race conditions on company inserts
        ingested = 0
        deduped = 0
        for raw in all_raws:
            try:
                was_deduped = await self._upsert_one(raw)
                if was_deduped:
                    deduped += 1
                else:
                    ingested += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("upsert_failed title=%s error=%s", raw.get("title"), exc)
                # Roll back the aborted transaction so the session is usable for the next row
                await self.db.rollback()

        from app.services.ghost_service import GhostService
        await GhostService(self.db).rescore_all()

        return {"ingested": ingested, "deduped": deduped}

    # ------------------------------------------------------------------
    # Public — list postings (paginated, filtered)
    # ------------------------------------------------------------------

    async def list_postings(
        self,
        *,
        work_mode: str | None = None,
        company: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[PostingSchema], int]:
        stmt = (
            select(Posting, Company)
            .join(Company, Posting.company_id == Company.id)
            .where(Posting.status == "active")
        )
        if work_mode:
            stmt = stmt.where(Posting.work_mode == work_mode)
        if company:
            stmt = stmt.where(
                Company.normalized_name.contains(normalize_company_name(company))
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total: int = (await self.db.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(Posting.created_at.desc()).offset((page - 1) * limit).limit(limit)
        rows = (await self.db.execute(stmt)).all()

        schemas = [coerce_posting_schema(p, c) for p, c in rows]
        return schemas, total

    # ------------------------------------------------------------------
    # Public — get single posting
    # ------------------------------------------------------------------

    async def get_posting(self, posting_id: uuid.UUID) -> PostingSchema | None:
        stmt = (
            select(Posting, Company)
            .join(Company, Posting.company_id == Company.id)
            .where(Posting.id == posting_id)
        )
        row = (await self.db.execute(stmt)).first()
        if row is None:
            return None
        posting, company = row
        return coerce_posting_schema(posting, company)

    # ------------------------------------------------------------------
    # Public — import a single posting by ATS URL
    # ------------------------------------------------------------------

    async def import_from_url(self, url: str) -> PostingSchema:
        from app.sources.ashby import fetch_ashby_single
        from app.sources.greenhouse import fetch_greenhouse_single
        from app.sources.lever import fetch_lever_single

        parsed = urllib.parse.urlparse(url)
        host = parsed.netloc.lower()

        raw: RawPosting | None = None
        if "greenhouse.io" in host:
            raw = await fetch_greenhouse_single(url)
        elif "lever.co" in host:
            raw = await fetch_lever_single(url)
        elif "ashbyhq.com" in host:
            raw = await fetch_ashby_single(url)
        else:
            raise APIError(422, "UNSUPPORTED_ATS", f"Unsupported ATS URL: {host}")

        if raw is None:
            raise APIError(404, "POSTING_NOT_FOUND", "Could not fetch the posting from the provided URL")

        await self._upsert_one(raw)

        # Return the now-stored posting
        result = await self.db.execute(
            select(Posting, Company)
            .join(Company, Posting.company_id == Company.id)
            .where(Posting.source_url == raw["source_url"])
        )
        row = result.first()
        if row is None:
            raise APIError(500, "INTERNAL_ERROR", "Posting was not stored")
        posting, company = row
        return coerce_posting_schema(posting, company)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _upsert_one(self, raw: RawPosting) -> bool:
        """Upsert one raw posting. Returns True if it was a duplicate."""
        normalized = normalize(raw)

        source_url = str(normalized["source_url"])
        dedup_key = str(normalized["dedup_key"])

        # 1. Check by source_url (exact same posting seen before)
        existing = (
            await self.db.execute(
                select(Posting).where(Posting.source_url == source_url)
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.last_seen_at = datetime.now(UTC)
            self.db.add(existing)
            await self.db.commit()
            return True  # already exists

        # 2. Check by dedup_key (cross-source duplicate — different URL, same role)
        cross = (
            await self.db.execute(
                select(Posting).where(Posting.dedup_key == dedup_key).limit(1)
            )
        ).scalar_one_or_none()
        if cross is not None:
            # Count the extra sighting so the REPOST FREQUENCY signal can fire
            cross.source_sightings = (cross.source_sightings or 1) + 1
            cross.last_seen_at = datetime.now(UTC)
            self.db.add(cross)
            await self.db.commit()
            return True  # cross-source duplicate

        # 3. Resolve company
        company = await self._resolve_company(raw["company_name"])

        # 4. Create posting
        posting = Posting(
            company_id=company.id,
            title=normalized["title"],
            description=normalized["description"],
            requirements=normalized["requirements"],
            location=normalized.get("location"),
            work_mode=normalized["work_mode"],
            stipend=normalized.get("stipend"),
            source=normalized["source"],
            source_url=source_url,
            posted_at=normalized.get("posted_at"),
            last_seen_at=normalized["last_seen_at"],
            status=normalized["status"],
            ghost_score=normalized["ghost_score"],
            is_ghost=normalized["is_ghost"],
            dedup_key=dedup_key,
        )

        # 5. Compute and store embedding — use rich description text, not sparse requirements
        embed_text = (
            f"{posting.title} at {raw['company_name']}. "
            f"{posting.description[:800]}"
        )
        try:
            vectors = await embed([embed_text])
            if vectors:
                posting.embedding = vectors[0]
        except Exception as exc:  # noqa: BLE001
            logger.warning("embed_failed title=%s error=%s", posting.title, exc)

        self.db.add(posting)
        await self.db.commit()
        return False

    async def _resolve_company(self, name: str) -> Company:
        normalized = normalize_company_name(name)
        result = await self.db.execute(
            select(Company).where(Company.normalized_name == normalized)
        )
        company = result.scalar_one_or_none()
        if company is not None:
            return company
        try:
            company = Company(name=name, normalized_name=normalized)
            self.db.add(company)
            await self.db.commit()
            await self.db.refresh(company)
            return company
        except IntegrityError:
            await self.db.rollback()
            result = await self.db.execute(
                select(Company).where(Company.normalized_name == normalized)
            )
            return result.scalar_one()
