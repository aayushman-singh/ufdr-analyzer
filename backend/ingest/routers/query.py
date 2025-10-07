"""
Query Router - Natural Language Query Interface

Provides API endpoints for executing natural language queries against UFDR data.
Integrates LLM-based query understanding with database/search execution.
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlmodel import Session, select
from meilisearch import Client as MeiliClient
from typing import Optional, Dict, Any, List
import traceback
import time
import uuid

from database import get_session
from db_setup import Query, Run, User
from ai.llm_client import LLMClient
from ai.query_executor import QueryExecutor
from ingest.utils.logger import get_logger
import os

logger = get_logger(__name__)

router = APIRouter(prefix="/query", tags=["Query"])


# Pydantic models for request/response
class ExecuteQueryRequest(BaseModel):
    """Request model for executing a natural language query"""
    query: str
    run_id: str
    user_id: Optional[str] = None  # Default to system user if not provided
    provider: Optional[str] = "openai"  # "openai" or "anthropic"
    generate_insights: Optional[bool] = True  # Generate LLM summary of results
    max_insight_results: Optional[int] = 50  # Max results to send to insight LLM (saves tokens)
    max_response_results: Optional[int] = 100  # Max results to return in API response


class ExecuteQueryResponse(BaseModel):
    """Response model for query execution"""
    query_id: str
    status: str
    intent: Optional[str] = None
    result_count: int
    results: List[Dict[str, Any]]
    insights: Optional[str] = None
    execution_time: float
    structured_params: Dict[str, Any]


class QueryHistoryResponse(BaseModel):
    """Response model for query history"""
    queries: List[Dict[str, Any]]
    total: int


class QuerySuggestion(BaseModel):
    """Suggested query template"""
    category: str
    query: str
    description: str


def get_meili_client():
    """Get MeiliSearch client instance"""
    from meilisearch import Client as MeiliClient
    MEILI_URL = os.getenv("MEILI_URL", "http://localhost:7700")
    MEILI_KEY = os.getenv("MEILI_KEY", None)
    return MeiliClient(MEILI_URL, MEILI_KEY)


def get_or_create_system_user(session: Session) -> User:
    """Get or create a default system user for queries without explicit user_id"""
    statement = select(User).where(User.email == "system@ufdr-analyzer.local")
    system_user = session.exec(statement).first()

    if not system_user:
        system_user = User(
            name="System",
            email="system@ufdr-analyzer.local",
            role="system"
        )
        session.add(system_user)
        session.commit()
        session.refresh(system_user)
        logger.info(f"Created system user: {system_user.id}")

    return system_user


@router.post("/execute", response_model=ExecuteQueryResponse)
async def execute_query(
    request: ExecuteQueryRequest,
    session: Session = Depends(get_session),
    meili_client: MeiliClient = Depends(get_meili_client)
):
    """
    Execute a natural language query against UFDR data.

    Flow:
    1. Validate run_id exists
    2. Use LLM to parse NL query → structured parameters
    3. Execute structured query against DB + search indexes
    4. Optionally generate insights summary
    5. Save query to history
    """
    start_time = time.time()
    logger.info(f"Executing query: '{request.query}' for run_id: {request.run_id}")

    # Validate run exists
    try:
        run_uuid = uuid.UUID(request.run_id)
        run = session.get(Run, run_uuid)
        if not run:
            raise HTTPException(status_code=404, detail=f"Run not found: {request.run_id}")
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid run_id format: {request.run_id}")

    # Get or create user
    if request.user_id:
        try:
            user_uuid = uuid.UUID(request.user_id)
            user = session.get(User, user_uuid)
            if not user:
                raise HTTPException(status_code=404, detail=f"User not found: {request.user_id}")
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid user_id format: {request.user_id}")
    else:
        user = get_or_create_system_user(session)

    # Create query record
    query_record = Query(
        run_id=run_uuid,
        user_id=user.id,
        query_text=request.query,
        status="processing"
    )
    session.add(query_record)
    session.commit()
    session.refresh(query_record)

    try:
        # Step 1: Parse NL query with LLM
        logger.info(f"Parsing query with {request.provider} LLM...")
        llm_client = LLMClient(provider=request.provider)

        # Build context about the run
        context = {
            "run_id": request.run_id,
            "device_info": run.extraction_metadata if hasattr(run, 'extraction_metadata') else None,
            "file_name": run.ufdr_file_name
        }

        structured_params = llm_client.parse_query(request.query, context=context)
        logger.info(f"LLM parsed intent: {structured_params.get('intent')}")

        # Update query record with intent and parameters
        query_record.intent = structured_params.get("intent", "unknown")
        query_record.parameters = str(structured_params)
        session.add(query_record)
        session.commit()

        # Step 2: Execute structured query
        logger.info("Executing structured query against DB and search indexes...")
        executor = QueryExecutor(session=session, meili_client=meili_client)
        execution_result = executor.execute(request.run_id, structured_params)

        results = execution_result.get("results", [])
        result_count = len(results)
        logger.info(f"Query returned {result_count} results")

        # Step 3: Generate insights (always generate for conversational response)
        insights = None
        if request.generate_insights:
            logger.info(f"Generating conversational response...")
            try:
                if result_count > 0:
                    # Create subset of results for insight generation (token optimization)
                    insight_results = {
                        "results": results[:request.max_insight_results],
                        "total_results": result_count
                    }
                    insights = llm_client.generate_insights(
                        query_results=insight_results,
                        original_query=request.query,
                        max_results=request.max_insight_results
                    )
                else:
                    # No results - generate helpful response
                    insights = f"I searched for '{request.query}' but didn't find any matching data in this device. Would you like me to try different search terms or broaden the criteria?"
                logger.info("Insights generated successfully")
            except Exception as insight_error:
                logger.warning(f"Failed to generate insights: {insight_error}")
                insights = f"Found {result_count} results matching your query." if result_count > 0 else "No results found."

        # Calculate execution time
        execution_time = time.time() - start_time

        # Update query record with results
        query_record.result_count = result_count
        query_record.execution_time = execution_time
        query_record.status = "completed"
        query_record.results_summary = insights if insights else f"{result_count} results"
        session.add(query_record)
        session.commit()

        logger.info(f"Query completed successfully in {execution_time:.2f}s")

        # Return controlled number of results based on max_response_results
        response_results = results[:request.max_response_results]
        logger.info(f"Returning {len(response_results)} of {result_count} total results in API response")

        return ExecuteQueryResponse(
            query_id=str(query_record.id),
            status="success",
            intent=structured_params.get("intent"),
            result_count=result_count,
            results=response_results,  # Controlled via max_response_results parameter
            insights=insights,
            execution_time=execution_time,
            structured_params=structured_params
        )

    except Exception as e:
        # Update query record with error
        error_msg = str(e)
        query_record.status = "failed"
        query_record.error_message = error_msg
        query_record.execution_time = time.time() - start_time
        session.add(query_record)
        session.commit()

        logger.error(f"Query execution failed: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")

        raise HTTPException(
            status_code=500,
            detail=f"Query execution failed: {error_msg}"
        )


@router.get("/history/{run_id}", response_model=QueryHistoryResponse)
async def get_query_history(
    run_id: str,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session)
):
    """
    Get query history for a specific run.

    Returns recent queries executed against this run, newest first.
    """
    logger.info(f"Fetching query history for run_id: {run_id}")

    # Validate run_id
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid run_id format: {run_id}")

    # Check run exists
    run = session.get(Run, run_uuid)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    # Fetch queries for this run
    statement = (
        select(Query)
        .where(Query.run_id == run_uuid)
        .order_by(Query.created_at.desc())
        .offset(offset)
        .limit(limit)
    )

    queries = session.exec(statement).all()

    # Convert to dict format
    query_list = []
    for q in queries:
        query_list.append({
            "query_id": str(q.id),
            "query_text": q.query_text,
            "intent": q.intent,
            "result_count": q.result_count,
            "execution_time": q.execution_time,
            "status": q.status,
            "created_at": q.created_at.isoformat(),
            "error_message": q.error_message
        })

    # Get total count
    count_statement = select(Query).where(Query.run_id == run_uuid)
    total_count = len(session.exec(count_statement).all())

    logger.info(f"Found {len(query_list)} queries (total: {total_count})")

    return QueryHistoryResponse(
        queries=query_list,
        total=total_count
    )


@router.get("/suggestions", response_model=List[QuerySuggestion])
async def get_query_suggestions():
    """
    Get suggested query templates for common forensic analysis tasks.

    Helps investigators discover what kinds of queries they can run.
    """
    suggestions = [
        # Cryptocurrency queries
        QuerySuggestion(
            category="cryptocurrency",
            query="Find all messages mentioning Bitcoin or cryptocurrency wallet addresses",
            description="Search for crypto-related communications"
        ),
        QuerySuggestion(
            category="cryptocurrency",
            query="Show transactions or wallet addresses discussed in the last 30 days",
            description="Recent crypto activity"
        ),

        # International/suspicious contacts
        QuerySuggestion(
            category="contacts",
            query="Find all calls and messages with international phone numbers",
            description="Identify foreign contacts"
        ),
        QuerySuggestion(
            category="contacts",
            query="Show all contacts not in the contact list",
            description="Find unknown or unlisted numbers"
        ),

        # Timeline/temporal queries
        QuerySuggestion(
            category="timeline",
            query="Show all activity between 2AM and 6AM",
            description="Unusual hour activity"
        ),
        QuerySuggestion(
            category="timeline",
            query="What happened on January 15, 2024?",
            description="Specific date investigation"
        ),

        # Content searches
        QuerySuggestion(
            category="keywords",
            query="Search for messages containing 'deal' or 'payment'",
            description="Financial discussion search"
        ),
        QuerySuggestion(
            category="keywords",
            query="Find deleted messages or call logs",
            description="Recover deleted data"
        ),

        # Media/files
        QuerySuggestion(
            category="media",
            query="Show all images and videos shared with contact +91-XXXXXXXXXX",
            description="Media exchange with specific contact"
        ),

        # Pattern matching
        QuerySuggestion(
            category="patterns",
            query="Find messages with addresses or location coordinates",
            description="Location-related communications"
        ),
        QuerySuggestion(
            category="patterns",
            query="Search for email addresses or URLs in messages",
            description="Extract communication channels"
        )
    ]

    logger.info(f"Returning {len(suggestions)} query suggestions")
    return suggestions
