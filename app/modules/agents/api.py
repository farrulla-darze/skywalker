"""Agents HTTP layer."""

from fastapi import APIRouter, HTTPException, Request

from app.api.v1.dependencies import CurrentUserDep, SessionDep

from .repository import AgentRepository
from .schemas import AgentCreate, AgentRead, AgentUpdate
from .service import AgentService, AgentServiceError

agents_router = APIRouter(prefix="/agents", tags=["agents"])


def _service(request: Request, session) -> AgentService:
    return AgentService(AgentRepository(session), request.app.state.tool_registry)


@agents_router.get("", response_model=list[AgentRead])
async def list_agents(request: Request, session: SessionDep, _user: CurrentUserDep):
    return await _service(request, session).list_all()


@agents_router.post("", response_model=AgentRead, status_code=201)
async def create_agent(
    payload: AgentCreate, request: Request, session: SessionDep, user: CurrentUserDep
):
    try:
        return await _service(request, session).create(payload, owner_id=user.id)
    except AgentServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@agents_router.get("/{agent_id}", response_model=AgentRead)
async def get_agent(agent_id: str, request: Request, session: SessionDep, _user: CurrentUserDep):
    try:
        return await _service(request, session).get(agent_id)
    except AgentServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@agents_router.patch("/{agent_id}", response_model=AgentRead)
async def update_agent(
    agent_id: str,
    payload: AgentUpdate,
    request: Request,
    session: SessionDep,
    _user: CurrentUserDep,
):
    try:
        return await _service(request, session).update(agent_id, payload)
    except AgentServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@agents_router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: str, request: Request, session: SessionDep, _user: CurrentUserDep
):
    try:
        await _service(request, session).delete(agent_id)
    except AgentServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
