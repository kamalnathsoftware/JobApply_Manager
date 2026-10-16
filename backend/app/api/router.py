from fastapi import APIRouter

from app.api import (
    accounts,
    answer_bank,
    applications,
    auth,
    llm_settings,
    personal,
    resumes,
    schedules,
    search_profiles,
    system,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(resumes.router)
api_router.include_router(accounts.router)
api_router.include_router(answer_bank.router)
api_router.include_router(search_profiles.router)
api_router.include_router(schedules.router)
api_router.include_router(applications.router)
api_router.include_router(system.router)
api_router.include_router(llm_settings.router)
api_router.include_router(personal.router)
