from fastapi import APIRouter

from app.api import accounts, answer_bank, auth, resumes

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(resumes.router)
api_router.include_router(accounts.router)
api_router.include_router(answer_bank.router)
