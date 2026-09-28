from fastapi import APIRouter

from app.api.v1.endpoints import (
    admin,
    analytics,
    auth,
    cards,
    catalog,
    evaluations,
    groups,
    incidents,
    lessons,
    materials,
    reports,
    scenarios,
    services,
    telephony,
    training,
    users,
    workplaces,
    ws,
)

api_router = APIRouter()

# Порядок включения влияет только на порядок разделов в Swagger.
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(groups.router)
api_router.include_router(catalog.router)
api_router.include_router(services.router)
api_router.include_router(incidents.router)
api_router.include_router(scenarios.router)
api_router.include_router(materials.router)
api_router.include_router(cards.router)
api_router.include_router(lessons.router)
api_router.include_router(workplaces.router)
api_router.include_router(training.router)
api_router.include_router(evaluations.router)
api_router.include_router(analytics.router)
api_router.include_router(reports.router)
api_router.include_router(telephony.router)
api_router.include_router(admin.router)
api_router.include_router(ws.router)
