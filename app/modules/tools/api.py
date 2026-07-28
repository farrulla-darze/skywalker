"""Tools HTTP layer — expose the tool catalog to the frontend."""

from fastapi import APIRouter, Request

from app.api.v1.dependencies import CurrentUserDep

from .schemas import ToolInfoRead

tools_router = APIRouter(prefix="/tools", tags=["tools"])


@tools_router.get("", response_model=list[ToolInfoRead])
async def list_tools(request: Request, _user: CurrentUserDep) -> list[ToolInfoRead]:
    registry = request.app.state.tool_registry
    return [spec.to_info() for spec in registry.list_specs()]
