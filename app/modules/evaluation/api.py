"""Evaluation HTTP layer."""

from fastapi import APIRouter, HTTPException, Request

from app.api.v1.dependencies import CurrentUserDep, SessionDep, SettingsDep
from app.modules.chat.repository import ChatRepository

from .repository import EvaluationRepository
from .schemas import (
    EvalResultRead,
    EvalRunCreate,
    EvalRunRead,
    GoldenItemCreate,
    GoldenItemRead,
    GoldenItemUpdate,
    PromoteFromMessageCreate,
)
from .service import EvaluationError, EvaluationService

evaluation_router = APIRouter(prefix="/evaluation", tags=["evaluation"])


def _service(request: Request, session, settings) -> EvaluationService:
    return EvaluationService(
        repository=EvaluationRepository(session),
        settings=settings,
        vector_store=getattr(request.app.state, "vector_store", None),
    )


# --- Golden dataset --------------------------------------------------------


@evaluation_router.get("/golden-items", response_model=list[GoldenItemRead])
async def list_items(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    _user: CurrentUserDep,
    include_archived: bool = False,
):
    return await _service(request, session, settings).list_items(include_archived)


@evaluation_router.post("/golden-items", response_model=GoldenItemRead, status_code=201)
async def create_item(
    payload: GoldenItemCreate,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    _user: CurrentUserDep,
):
    return await _service(request, session, settings).create_item(payload)


@evaluation_router.patch("/golden-items/{item_id}", response_model=GoldenItemRead)
async def update_item(
    item_id: str,
    payload: GoldenItemUpdate,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    _user: CurrentUserDep,
):
    try:
        return await _service(request, session, settings).update_item(item_id, payload)
    except EvaluationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@evaluation_router.post("/golden-items/promote", response_model=GoldenItemRead, status_code=201)
async def promote_from_message(
    payload: PromoteFromMessageCreate,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    _user: CurrentUserDep,
):
    try:
        return await _service(request, session, settings).promote_from_message(
            payload, ChatRepository(session)
        )
    except EvaluationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


# --- Langfuse dataset ------------------------------------------------------


@evaluation_router.post("/langfuse/sync-dataset")
async def sync_langfuse_dataset(
    request: Request, session: SessionDep, settings: SettingsDep, _user: CurrentUserDep
):
    """Push the golden dataset to Langfuse as 'getnet-qa-v1' (idempotent upsert)."""
    try:
        return await _service(request, session, settings).sync_langfuse_dataset()
    except EvaluationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


# --- Eval runs -------------------------------------------------------------


@evaluation_router.get("/runs", response_model=list[EvalRunRead])
async def list_runs(
    request: Request, session: SessionDep, settings: SettingsDep, _user: CurrentUserDep
):
    return await _service(request, session, settings).list_runs()


@evaluation_router.post("/runs", response_model=EvalRunRead, status_code=201)
async def start_run(
    payload: EvalRunCreate,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    _user: CurrentUserDep,
):
    try:
        return await _service(request, session, settings).start_run(payload)
    except EvaluationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@evaluation_router.get("/runs/{run_id}", response_model=EvalRunRead)
async def get_run(
    run_id: str,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    _user: CurrentUserDep,
):
    try:
        return await _service(request, session, settings).get_run(run_id)
    except EvaluationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@evaluation_router.get("/runs/{run_id}/results", response_model=list[EvalResultRead])
async def list_results(
    run_id: str, session: SessionDep, _user: CurrentUserDep
):
    results = await EvaluationRepository(session).list_results(run_id)
    return [EvalResultRead.model_validate(r) for r in results]
