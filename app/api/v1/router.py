"""API v1 router — all modules are wired here."""

from fastapi import APIRouter

from app.modules.agents.api import agents_router
from app.modules.auth.api import auth_router
from app.modules.chat.api import chat_router
from app.modules.evaluation.api import evaluation_router
from app.modules.integrations.api import integrations_router
from app.modules.knowledge.api import knowledge_router
from app.modules.tools.api import tools_router

api_v1_router = APIRouter(prefix="/api/v1")

api_v1_router.include_router(auth_router)
api_v1_router.include_router(agents_router)
api_v1_router.include_router(tools_router)
api_v1_router.include_router(chat_router)
api_v1_router.include_router(knowledge_router)
api_v1_router.include_router(evaluation_router)
api_v1_router.include_router(integrations_router)
