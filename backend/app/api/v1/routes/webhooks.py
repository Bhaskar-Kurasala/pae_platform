import hashlib
import hmac
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, status

from app.core.config import settings

log = structlog.get_logger()

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _verify_github_signature(body: bytes, signature: str) -> None:
    """Verify GitHub webhook HMAC-SHA256 signature."""
    secret = settings.github_token.encode()
    expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid GitHub signature",
        )


def _verify_stripe_signature(body: bytes, signature: str) -> None:
    """Verify Stripe webhook signature."""
    if not settings.stripe_webhook_secret:
        return
    parts = {p.split("=")[0]: p.split("=")[1] for p in signature.split(",") if "=" in p}
    timestamp = parts.get("t", "")
    payload = f"{timestamp}.{body.decode()}"
    expected = hmac.new(
        settings.stripe_webhook_secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    v1 = parts.get("v1", "")
    if not hmac.compare_digest(expected, v1):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Stripe signature",
        )


async def _handle_github_push(payload: dict[str, Any]) -> None:
    """On push event: trigger ContentIngestionAgent to process the commit."""
    repo_name = payload.get("repository", {}).get("name", "unknown")
    commit_sha = payload.get("after", "")
    pusher = payload.get("pusher", {}).get("name", "unknown")
    log.info("webhook.github.push", repo=repo_name, commit=commit_sha, pusher=pusher)

    try:
        from app.agents.base_agent import AgentState
        from app.agents.content_ingestion import ContentIngestionAgent

        agent = ContentIngestionAgent()
        state = AgentState(
            student_id="system",
            task=f"Process GitHub push to {repo_name}",
            context={
                "github_commit": commit_sha,
                "repo": repo_name,
                "pusher": pusher,
                "commits": payload.get("commits", []),
            },
        )
        result = await agent.run(state)
        log.info("webhook.github.push.processed", repo=repo_name, response_len=len(result.response or ""))
    except Exception as exc:
        log.error("webhook.github.push.failed", repo=repo_name, error=str(exc))


async def _handle_stripe_checkout_completed(payload: dict[str, Any]) -> None:
    """On checkout.session.completed: create enrollment for the purchased course."""
    session = payload.get("data", {}).get("object", {})
    customer_email = session.get("customer_email") or session.get("customer_details", {}).get("email")
    metadata = session.get("metadata", {})
    course_id = metadata.get("course_id")
    amount_total = session.get("amount_total", 0)
    payment_intent_id = session.get("payment_intent", "")

    log.info(
        "webhook.stripe.checkout_completed",
        customer_email=customer_email,
        course_id=course_id,
        amount=amount_total,
    )

    if not course_id or not customer_email:
        log.warning("webhook.stripe.missing_metadata", session_id=session.get("id"))
        return

    try:
        from app.core.database import AsyncSessionLocal
        from app.models.enrollment import Enrollment
        from app.models.payment import Payment
        from app.repositories.course_repository import CourseRepository
        from app.repositories.user_repository import UserRepository

        async with AsyncSessionLocal() as db:
            user_repo = UserRepository(db)
            course_repo = CourseRepository(db)

            user = await user_repo.get_by_email(customer_email)
            if not user:
                log.warning("webhook.stripe.user_not_found", email=customer_email)
                return

            import uuid
            try:
                course_uuid = uuid.UUID(course_id)
            except ValueError:
                log.warning("webhook.stripe.invalid_course_id", course_id=course_id)
                return

            course = await course_repo.get_active(course_uuid)
            if not course:
                log.warning("webhook.stripe.course_not_found", course_id=course_id)
                return

            # Create payment record
            payment = Payment(
                user_id=user.id,
                course_id=course.id,
                stripe_payment_intent_id=payment_intent_id,
                amount_cents=amount_total,
                currency="usd",
                status="succeeded",
                payment_method="card",
            )
            db.add(payment)
            await db.flush()

            # Create enrollment
            enrollment = Enrollment(
                student_id=user.id,
                course_id=course.id,
                status="active",
                enrolled_at=datetime.now(UTC),
                payment_id=payment.id,
            )
            db.add(enrollment)
            await db.commit()
            log.info(
                "webhook.stripe.enrollment_created",
                user_id=str(user.id),
                course_id=str(course.id),
            )
    except Exception as exc:
        log.error("webhook.stripe.enrollment_failed", error=str(exc))


@router.post("/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str = Header(default=""),
    x_github_event: str = Header(default=""),
) -> dict[str, str]:
    body = await request.body()
    if x_hub_signature_256:
        _verify_github_signature(body, x_hub_signature_256)
    payload: dict[str, Any] = await request.json()
    log.info("webhook.github", gh_event=x_github_event, repo=payload.get("repository", {}).get("name"))

    if x_github_event == "push":
        background_tasks.add_task(_handle_github_push, payload)

    return {"status": "received", "event": x_github_event}


@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    stripe_signature: str = Header(default=""),
) -> dict[str, str]:
    body = await request.body()
    if stripe_signature and settings.stripe_webhook_secret:
        _verify_stripe_signature(body, stripe_signature)
    payload: dict[str, Any] = await request.json()
    event_type: str = payload.get("type", "unknown")
    log.info("webhook.stripe", stripe_event=event_type)

    if event_type == "checkout.session.completed":
        background_tasks.add_task(_handle_stripe_checkout_completed, payload)

    return {"status": "received", "event": event_type}


@router.post("/youtube")
async def youtube_webhook(request: Request) -> dict[str, str]:
    # TODO: connect YouTube Data API push notifications
    # When a new video is published to the channel, trigger ContentIngestionAgent
    payload: dict[str, Any] = await request.json()
    log.info("webhook.youtube.received", payload_keys=list(payload.keys()))
    return {"status": "received", "note": "YouTube webhook handler not yet implemented"}
