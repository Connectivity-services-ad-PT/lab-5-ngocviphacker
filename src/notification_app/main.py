import os
import uuid
import requests
import psycopg2
from datetime import datetime, timezone
from typing import Dict, List, Optional
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

SERVICE_NAME = os.getenv("SERVICE_NAME", "notification-service")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "0.5.0")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "local-dev-token")

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "db")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_USER = os.getenv("POSTGRES_USER", "lab05")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "lab05pass")
POSTGRES_DB = os.getenv("POSTGRES_DB", "notificationdb")

app = FastAPI(
    title="FIT4110 Lab 05 - Notification Service",
    version=SERVICE_VERSION,
    description="Notification Service API with PostgreSQL and AI integration.",
)

# In-memory storage fallback if DB is not available
IN_MEMORY_NOTIFICATIONS = {}

def get_db_connection():
    return psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        database=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        connect_timeout=3
    )

def execute_db_query(query, params=None, fetch=False):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(query, params or ())
        if fetch:
            results = cur.fetchall()
            cur.close()
            conn.close()
            return results
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[DB Warning] SQL Execution failed, falling back to memory: {e}")
        return None

@app.on_event("startup")
def startup_event():
    # Setup database schema if possible
    create_table_query = """
    CREATE TABLE IF NOT EXISTS notifications (
        delivery_id VARCHAR(50) PRIMARY KEY,
        alert_id VARCHAR(100) NOT NULL,
        event_id VARCHAR(50) NOT NULL,
        channel VARCHAR(50) NOT NULL,
        status VARCHAR(50) NOT NULL,
        sent_at VARCHAR(50) NOT NULL,
        delivered_at VARCHAR(50),
        error_message TEXT
    );
    """
    res = execute_db_query(create_table_query)
    if res:
        print("[DB Info] Table 'notifications' successfully initialized in PostgreSQL.")
    else:
        print("[DB Info] Table initialization failed, running with memory fallback.")

# Pydantic schemas
class AlertData(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    message: str = Field(..., min_length=1, max_length=1000)
    source: str = Field(..., min_length=1, max_length=100)
    alertLevel: Optional[str] = Field(default=None, max_length=50)

class AlertEventPayload(BaseModel):
    eventId: str
    eventType: str
    alertId: str = Field(..., min_length=1, max_length=100)
    correlationId: str = Field(..., min_length=1, max_length=100)
    source: Optional[str] = None
    severity: str
    alertVersion: Optional[int] = Field(default=1, ge=1)
    occurredAt: Optional[str] = None
    payload: Optional[AlertData] = None  # Mapping legacy postman field
    data: Optional[AlertData] = None     # Mapping standard schema field
    channels: Optional[List[str]] = Field(default=None, max_length=4)
    metadata: Optional[dict] = None

class NotificationDelivery(BaseModel):
    deliveryId: str
    alertId: str
    eventId: str
    channel: str
    status: str
    sentAt: str
    deliveredAt: Optional[str] = None
    errorMessage: Optional[str] = None

# RFC 7807 problem builder
def build_problem(
    status_code: int,
    title: str,
    detail: str,
    instance: Optional[str] = None,
    problem_type: str = "about:blank",
):
    problem = {
        "type": problem_type,
        "title": title,
        "status": status_code,
        "detail": detail,
    }
    if instance:
        problem["instance"] = instance
    return problem

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict):
        problem = exc.detail
    else:
        problem = build_problem(
            status_code=exc.status_code,
            title="HTTP Error",
            detail=str(exc.detail),
            instance=str(request.url.path),
        )
    return JSONResponse(
        status_code=exc.status_code,
        content=problem,
        media_type="application/problem+json",
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    first_error = exc.errors()[0] if exc.errors() else {}
    location = ".".join(str(item) for item in first_error.get("loc", []))
    message = first_error.get("msg", "Validation error")
    detail = f"{location}: {message}" if location else message

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=build_problem(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Unprocessable Entity",
            detail=detail,
            instance=str(request.url.path),
            problem_type="https://notification.campus.local/problems/unprocessable-entity",
        ),
        media_type="application/problem+json",
    )

def verify_bearer_token(authorization: Optional[str] = Header(default=None)) -> None:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=build_problem(
                status_code=status.HTTP_401_UNAUTHORIZED,
                title="Unauthorized",
                detail="Missing Authorization header",
                problem_type="https://notification.campus.local/problems/unauthorized",
            ),
        )
    expected = f"Bearer {AUTH_TOKEN}"
    if authorization != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=build_problem(
                status_code=status.HTTP_401_UNAUTHORIZED,
                title="Unauthorized",
                detail="Invalid bearer token",
                problem_type="https://notification.campus.local/problems/unauthorized",
            ),
        )

# Helper to log notifications
def log_notification_delivery(delivery_id: str, alert_id: str, event_id: str, channel: str, status_str: str, sent_at: str):
    insert_query = """
    INSERT INTO notifications (delivery_id, alert_id, event_id, channel, status, sent_at, delivered_at, error_message)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
    """
    res = execute_db_query(insert_query, (delivery_id, alert_id, event_id, channel, status_str, sent_at, sent_at, "No error"))
    if not res:
        # Memory fallback
        IN_MEMORY_NOTIFICATIONS[delivery_id] = {
            "deliveryId": delivery_id,
            "alertId": alert_id,
            "eventId": event_id,
            "channel": channel,
            "status": status_str,
            "sentAt": sent_at,
            "deliveredAt": sent_at,
            "errorMessage": "No error"
        }

@app.get("/")
def root():
    return {"message": "Notification Service API is running"}

@app.get("/health")
def health() -> dict:
    db_ok = False
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        db_ok = True
    except Exception as e:
        print(f"[Health] DB check failed: {e}")

    ai_ok = False
    try:
        r = requests.get("http://ai-service:9000/health", timeout=2.0)
        if r.status_code == 200:
            ai_ok = True
    except Exception as e:
        print(f"[Health] AI check failed: {e}")

    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dependencies": {
            "database": "ok" if db_ok else "failed (memory fallback active)",
            "ai_service": "ok" if ai_ok else "failed"
        }
    }

@app.post(
    "/events/alert.created",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_bearer_token)],
)
def handle_alert_created(payload: AlertEventPayload):
    # UUID validation on eventId
    try:
        uuid.UUID(payload.eventId)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=build_problem(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                title="Unprocessable Entity",
                detail="eventId must be a valid UUID",
                problem_type="https://notification.campus.local/problems/unprocessable-entity",
            ),
        )

    # Perform integration check by calling AI-service
    ai_prediction = None
    try:
        r = requests.post("http://ai-service:9000/predict", json={}, timeout=2.0)
        if r.status_code == 200:
            ai_prediction = r.json()
            print(f"[AI Info] Classification prediction: {ai_prediction}")
    except Exception as e:
        print(f"[AI Warning] Could not connect to AI service: {e}")

    # Generate delivery statuses for each target channel
    sent_at = datetime.now(timezone.utc).isoformat()
    channels = payload.channels or ["telegram", "email", "app"]
    
    # Check max channels boundary
    if len(channels) > 4:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=build_problem(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                title="Unprocessable Entity",
                detail="Max 4 channels allowed",
                problem_type="https://notification.campus.local/problems/unprocessable-entity",
            ),
        )

    for channel in channels:
        delivery_id = str(uuid.uuid4())
        log_notification_delivery(
            delivery_id=delivery_id,
            alert_id=payload.alertId,
            event_id=payload.eventId,
            channel=channel,
            status_str="delivered",
            sent_at=sent_at
        )

    return {
        "eventId": payload.eventId,
        "status": "queued",
        "processedAt": sent_at
    }

@app.post(
    "/events/alert.escalated",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_bearer_token)],
)
def handle_alert_escalated(payload: AlertEventPayload):
    # UUID validation on eventId
    try:
        uuid.UUID(payload.eventId)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=build_problem(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                title="Unprocessable Entity",
                detail="eventId must be a valid UUID",
            ),
        )

    sent_at = datetime.now(timezone.utc).isoformat()
    channels = payload.channels or ["telegram", "email", "app", "sms"]
    for channel in channels:
        delivery_id = str(uuid.uuid4())
        log_notification_delivery(
            delivery_id=delivery_id,
            alert_id=payload.alertId,
            event_id=payload.eventId,
            channel=channel,
            status_str="delivered",
            sent_at=sent_at
        )

    return {
        "eventId": payload.eventId,
        "status": "queued",
        "processedAt": sent_at
    }

@app.post(
    "/events/alert.resolved",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_bearer_token)],
)
def handle_alert_resolved(payload: AlertEventPayload):
    # UUID validation on eventId
    try:
        uuid.UUID(payload.eventId)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=build_problem(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                title="Unprocessable Entity",
                detail="eventId must be a valid UUID",
            ),
        )

    sent_at = datetime.now(timezone.utc).isoformat()
    channels = payload.channels or ["telegram", "email", "app"]
    for channel in channels:
        delivery_id = str(uuid.uuid4())
        log_notification_delivery(
            delivery_id=delivery_id,
            alert_id=payload.alertId,
            event_id=payload.eventId,
            channel=channel,
            status_str="delivered",
            sent_at=sent_at
        )

    return {
        "eventId": payload.eventId,
        "status": "queued",
        "processedAt": sent_at
    }

@app.get(
    "/notifications/{notificationId}",
    response_model=NotificationDelivery,
    dependencies=[Depends(verify_bearer_token)],
)
def get_notification_status(notificationId: str):
    # Query database
    select_query = """
    SELECT delivery_id, alert_id, event_id, channel, status, sent_at, delivered_at, error_message
    FROM notifications
    WHERE delivery_id = %s;
    """
    rows = execute_db_query(select_query, (notificationId,), fetch=True)
    if rows:
        row = rows[0]
        return NotificationDelivery(
            deliveryId=row[0],
            alertId=row[1],
            eventId=row[2],
            channel=row[3],
            status=row[4],
            sentAt=row[5],
            deliveredAt=row[6],
            errorMessage=row[7]
        )

    # Fallback to memory
    if notificationId in IN_MEMORY_NOTIFICATIONS:
        item = IN_MEMORY_NOTIFICATIONS[notificationId]
        return NotificationDelivery(
            deliveryId=item["deliveryId"],
            alertId=item["alertId"],
            eventId=item["eventId"],
            channel=item["channel"],
            status=item["status"],
            sentAt=item["sentAt"],
            deliveredAt=item["deliveredAt"],
            errorMessage=item["errorMessage"]
        )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=build_problem(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Not Found",
            detail=f"Notification with ID {notificationId} not found",
            instance=f"/notifications/{notificationId}",
            problem_type="https://notification.campus.local/problems/not-found",
        ),
    )
