"""Knowledge HTTP layer."""

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.api.v1.dependencies import CurrentUserDep, SessionDep, SettingsDep

from .graph_extraction import GraphExtractionService
from .repository import KnowledgeRepository
from .schemas import (
    GraphExtractCreate,
    GraphExtractResponse,
    KnowledgeIngestCreate,
    KnowledgeIngestResponse,
    KnowledgeJobRead,
    KnowledgeQueryCreate,
    KnowledgeQueryResponse,
)
from .service import KnowledgeService

knowledge_router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _service(request: Request, session, settings) -> KnowledgeService:
    return KnowledgeService(
        repository=KnowledgeRepository(session),
        vector_store=request.app.state.vector_store,
        settings=settings,
    )


@knowledge_router.post("/ingest", response_model=KnowledgeIngestResponse)
async def ingest_urls(
    payload: KnowledgeIngestCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    _user: CurrentUserDep,
) -> KnowledgeIngestResponse:
    service = _service(request, session, settings)
    response = await service.create_ingestion_job(payload)
    background_tasks.add_task(
        service.run_ingestion_pipeline, response.job_id, request.app.state.db.session_factory
    )
    return response


@knowledge_router.get("/jobs", response_model=list[KnowledgeJobRead])
async def list_jobs(session: SessionDep, _user: CurrentUserDep) -> list[KnowledgeJobRead]:
    jobs = await KnowledgeRepository(session).list_jobs()
    return [KnowledgeJobRead.model_validate(j) for j in jobs]


@knowledge_router.get("/jobs/{job_id}", response_model=KnowledgeJobRead)
async def get_job(job_id: str, session: SessionDep, _user: CurrentUserDep) -> KnowledgeJobRead:
    job = await KnowledgeRepository(session).get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return KnowledgeJobRead.model_validate(job)


@knowledge_router.post("/query", response_model=KnowledgeQueryResponse)
async def query_knowledge(
    payload: KnowledgeQueryCreate,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    _user: CurrentUserDep,
) -> KnowledgeQueryResponse:
    return await _service(request, session, settings).query(payload)


# ---------------------------------------------------------------------------
# Knowledge graph (Neo4j)
# ---------------------------------------------------------------------------


@knowledge_router.post("/graph/extract", response_model=GraphExtractResponse)
async def extract_graph_facts(
    payload: GraphExtractCreate,
    request: Request,
    settings: SettingsDep,
    _user: CurrentUserDep,
) -> GraphExtractResponse:
    """Run LLM fact extraction over the ingested chunks of a namespace into Neo4j.

    Synchronous admin operation — one LLM call per source URL.
    """
    graph_store = getattr(request.app.state, "graph_store", None)
    if graph_store is None or not settings.graph_enabled:
        raise HTTPException(status_code=503, detail="Knowledge graph is not enabled")

    extraction = GraphExtractionService(
        settings=settings,
        vector_store=request.app.state.vector_store,
        graph_store=graph_store,
    )
    summary = await extraction.extract_namespace(payload.namespace)
    return GraphExtractResponse(
        namespace=summary.namespace,
        urls_processed=summary.urls_processed,
        urls_failed=summary.urls_failed,
        products_upserted=summary.products_upserted,
        fees_upserted=summary.fees_upserted,
        features_upserted=summary.features_upserted,
        errors=summary.errors,
    )


@knowledge_router.get("/graph/products")
async def list_graph_products(
    request: Request, settings: SettingsDep, _user: CurrentUserDep
) -> list[dict]:
    """List products currently in the knowledge graph, with their facts."""
    graph_store = getattr(request.app.state, "graph_store", None)
    if graph_store is None or not settings.graph_enabled:
        raise HTTPException(status_code=503, detail="Knowledge graph is not enabled")
    products = await graph_store.list_products()
    detailed = []
    for product in products:
        facts = await graph_store.get_product_facts(product["slug"])
        detailed.extend(facts)
    return detailed
