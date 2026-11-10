"""Roteador agregado da versão 1 da API."""

from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.health import router as health_router
from app.api.v1.members import router as members_router
from app.api.v1.reports import router as reports_router
from app.api.v1.reviews import router as reviews_router
from app.api.v1.sync import router as sync_router
from app.api.v1.system import router as system_router
from app.api.v1.tenants import router as tenants_router
from app.api.v1.webhooks import router as webhooks_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(tenants_router)
api_router.include_router(reports_router)
api_router.include_router(sync_router)
api_router.include_router(members_router)
api_router.include_router(reviews_router)
api_router.include_router(system_router)
api_router.include_router(webhooks_router)
