import os
import secrets
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Optional

import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field


DATABASE_URL = os.environ.get("DATABASE_URL", "")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")

app = FastAPI(
    title="DroidControl API",
    version="1.0.0",
    description="Consent-based Android device administration API"
)

bearer = HTTPBearer(auto_error=False)


def get_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")

    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        connect_timeout=10,
        sslmode="require"
    )


def hash_value(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def check_admin(x_admin_key: Optional[str] = Header(default=None)):
    if not ADMIN_KEY or not x_admin_key:
        raise HTTPException(status_code=401, detail="Admin authentication required")

    if not hmac.compare_digest(x_admin_key, ADMIN_KEY):
        raise HTTPException(status_code=401, detail="Invalid admin key")


def current_device(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer)
):
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Device token required")

    token_hash = hash_value(credentials.credentials)

    with get_connection() as conn:
        device = conn.execute(
            """
            SELECT id, name, active
            FROM devices
            WHERE token_hash = %s AND active = TRUE
            """,
            (token_hash,)
        ).fetchone()

    if not device:
        raise HTTPException(status_code=401, detail="Invalid or revoked device token")

    return device


@app.on_event("startup")
def initialize_database():
    if not DATABASE_URL or not ADMIN_KEY:
        raise RuntimeError("Set DATABASE_URL and ADMIN_KEY environment variables")

    if len(ADMIN_KEY) < 32:
        raise RuntimeError("ADMIN_KEY must contain at least 32 characters")

    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS devices (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name TEXT NOT NULL,
                manufacturer TEXT,
                model TEXT,
                android_version TEXT,
                app_version TEXT,
                token_hash TEXT UNIQUE NOT NULL,
                active BOOLEAN NOT NULL DEFAULT TRUE,
                battery_percent INTEGER,
                charging BOOLEAN,
                last_seen TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pairing_codes (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                code_hash TEXT UNIQUE NOT NULL,
                expires_at TIMESTAMPTZ NOT NULL,
                used_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )


class PairingRequest(BaseModel):
    code: str = Field(min_length=6, max_length=20)
    name: str = Field(min_length=1, max_length=80)
    manufacturer: Optional[str] = Field(default=None, max_length=80)
    model: Optional[str] = Field(default=None, max_length=80)
    android_version: Optional[str] = Field(default=None, max_length=40)
    app_version: Optional[str] = Field(default=None, max_length=40)


class HeartbeatRequest(BaseModel):
    battery_percent: Optional[int] = Field(default=None, ge=0, le=100)
    charging: Optional[bool] = None


@app.get("/")
def root():
    return {"service": "DroidControl API", "status": "online"}


@app.get("/api/health")
def health():
    try:
        with get_connection() as conn:
            conn.execute("SELECT 1")
        return {"status": "online", "database": "connected"}
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable")


@app.post("/api/admin/pairing-codes", dependencies=[Depends(check_admin)])
def create_pairing_code():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    code = "".join(secrets.choice(alphabet) for _ in range(8))
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO pairing_codes (code_hash, expires_at)
            VALUES (%s, %s)
            """,
            (hash_value(code), expires)
        )

    return {
        "pairing_code": code,
        "expires_in_seconds": 600,
        "message": "Share this code only with the device owner during consent-based pairing."
    }


@app.post("/api/pair")
def pair_device(request: PairingRequest):
    token = secrets.token_urlsafe(32)
    code_hash = hash_value(request.code.strip().upper())
    now = datetime.now(timezone.utc)

    with get_connection() as conn:
        pairing = conn.execute(
            """
            SELECT id, expires_at, used_at
            FROM pairing_codes
            WHERE code_hash = %s
            FOR UPDATE
            """,
            (code_hash,)
        ).fetchone()

        if (
            not pairing
            or pairing["used_at"] is not None
            or pairing["expires_at"] <= now
        ):
            raise HTTPException(status_code=400, detail="Invalid, expired, or already used pairing code")

        conn.execute(
            """
            UPDATE pairing_codes
            SET used_at = NOW()
            WHERE id = %s
            """,
            (pairing["id"],)
        )

        device = conn.execute(
            """
            INSERT INTO devices (
                name, manufacturer, model, android_version,
                app_version, token_hash, last_seen
            )
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            RETURNING id
            """,
            (
                request.name,
                request.manufacturer,
                request.model,
                request.android_version,
                request.app_version,
                hash_value(token)
            )
        ).fetchone()

    return {
        "message": "Device paired successfully",
        "device_id": str(device["id"]),
        "device_token": token
    }


@app.post("/api/device/heartbeat")
def device_heartbeat(
    request: HeartbeatRequest,
    device=Depends(current_device)
):
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE devices
            SET battery_percent = %s,
                charging = %s,
                last_seen = NOW()
            WHERE id = %s AND active = TRUE
            """,
            (request.battery_percent, request.charging, device["id"])
        )

    return {"message": "Heartbeat received", "status": "online"}


@app.get("/api/admin/devices", dependencies=[Depends(check_admin)])
def list_devices():
    with get_connection() as conn:
        devices = conn.execute(
            """
            SELECT id, name, manufacturer, model, android_version,
                   app_version, active, battery_percent, charging,
                   last_seen, created_at
            FROM devices
            ORDER BY created_at DESC
            """
        ).fetchall()

    for device in devices:
        device["id"] = str(device["id"])

    return {"devices": devices}


@app.delete(
    "/api/admin/devices/{device_id}",
    dependencies=[Depends(check_admin)]
)
def revoke_device(device_id: str):
    with get_connection() as conn:
        result = conn.execute(
            """
            UPDATE devices
            SET active = FALSE
            WHERE id = %s AND active = TRUE
            RETURNING id
            """,
            (device_id,)
        ).fetchone()

    if not result:
        raise HTTPException(status_code=404, detail="Active device not found")

    return {"message": "Device access revoked"}
