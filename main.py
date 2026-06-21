# Default
import sys
import json
from pathlib import Path
from contextlib import asynccontextmanager

# FastAPI
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from typing import Literal

# Pipeline
import src.pipeline.startup as startup
import src.pipeline.ingest as ingest
import src.pipeline.query as query_pipe

# Script
import src.script.chroma as chroma
import src.script.config as pyconfig

# Utils
import src.utils.files as files
import src.utils.models as models

################################################################
############################# APP ##############################
################################################################
# Startup processes  
@asynccontextmanager
async def lifespan(app: FastAPI):
    
    # --- STARTUP EVENTS ---
    print("Starting async component loading...")
    try:
        await startup.startup_load(app)
        print("Startup complete!")
        
    except Exception as e:
        print(f"!!! CRITICAL ERROR DURING STARTUP !!!")
        print(f"{str(e)}")
        raise e
    
    yield
    
    # --- SHUTDOWN EVENTS ---
    print("Shutting down application...")
    try:
        if hasattr(app.state, "chroma_client"):
            try:
                app.state.chroma_client.persist() 
            except AttributeError:
                pass
    except Exception as e:
        print(f"Error during shutdown: {e}", file=sys.stderr)

### FastAPI ###
app = FastAPI(
    title="LoDRAG",
    description="A Human-driven Linked Open Data Framework for Local Retrieval-Augmented Generation",
    version="0.0.1",
    swagger_ui_parameters={"defaultModelsExpandDepth": -1},
    lifespan=lifespan
)

BASE_DIR = Path(__file__).resolve().parent
app.state.base_dir = BASE_DIR

################################################################
########################### CONFIG #############################
################################################################

###########
# Projects
###########
@app.get(
    "/api/config/projects",
    tags=["Config"],
    description="Get active projects list"
    )
async def get_all_projects():
    return list(app.state.projects.values())

@app.post(
    "/api/config/projects",
    tags=["Config"],
    description="Add new project"
    )
async def add_project_endpoint(project: models.projectModel):
    
    if project.id in app.state.projects:
        raise HTTPException(status_code=400, detail="Project already exists")
    
    # Create new collection
    await chroma.create_db_collection(app, project.model_dump())
    
    return {"status": "success", "projects": list(app.state.projects.values())}

@app.delete(
    "/api/projects/{project_id}",
    tags=["Config"],
    description="Delete project"
    )
async def delete_project(project_id: str):
    try:
        await chroma.delete_project(project_id, app)
        return {"status": "success", "message": f"Project {project_id} successful deleted"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error during delete: {str(e)}")


###############
# Config files
###############
@app.get(
    "/api/config/{config_filename}",
    tags=["Config"],
    description="Get config file content"
    )
async def get_schema_endpoint(config_filename: Literal["schema", "enriched_schema", "prompts", "config", "models", "projects"]):
    
    value = getattr(app.state, config_filename, None)
    if value is None:
        raise HTTPException(status_code=404, detail=f"Config '{config_filename}' not loaded")
    return value


@app.put(
    "/api/config/{config_filename}", 
    tags=["Config"],
    description="Update config schema"
    )
async def edit_config_endpoint(config_filename: Literal["schema","prompts","models", "config"], updated_content: dict):
    
    if config_filename == "schema":
        app.state.schema = updated_content
        return await pyconfig.update_config_schema(app)
    else:
        return await pyconfig.update_config_file(app, config_filename, updated_content)
    
    


################################################################
########################## PIPELINE ############################
################################################################

#########
# Ingest
#########

# Test
@app.post(
    "/api/ingest/test",
    tags=['Ingest'],
    description="Testing loading and reconciliation of input text"
    )
async def ingest_test_text(payload: models.testIngestRequest):
    
    text_content = payload.text_input.strip()
    
    if not text_content:
        raise HTTPException(status_code=400, detail="Loaded file is empty")
        
    try:
        result = await ingest.ingest_text(
            app=app, 
            text=text_content, 
            project_id=payload.project_id, 
            ai_mode=payload.ai_mode, 
            test_mode=True
        )
        return {
            "status": "success", 
            "processed_paragraphs": len(result), 
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error testing pipeline: {str(e)}")
    
# Process file
@app.post(
    "/api/ingest/upload",
    tags=['Ingest'],
    description="Loading, reconciliation, embedding and chromadb saving of input .txt file"
    )
async def ingest_file(
    project_id: str = Form(...),
    ai_mode: bool = Form(False),
    file: UploadFile = File(...)
):
        
    if not file.filename.endswith('.txt'):
        raise HTTPException(
            status_code=400, 
            detail="Invalid file format. Only .txt files allowed"
        )
        
    try:
        text_content = await files.extract_text_from_txt(file)
    except Exception as err:
        raise HTTPException(
            status_code=400, 
            detail=f"Error during text processing: {str(err)}"
        )
        
    if not text_content:
        raise HTTPException(
            status_code=400, 
            detail="Loaded file is empty"
        )
        
    collection = app.state.chroma_collections.get(project_id)
    if collection is None:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    if collection.count() > 0:
        raise HTTPException(
            status_code=409,
            detail="Project already populated. Resubmit with force=true to reingest."
        )
        
    try:
        result = await ingest.ingest_text(
            app=app, 
            text=text_content, 
            project_id=project_id, 
            ai_mode=ai_mode, 
            test_mode=False
        )
        return {
            "status": "success", 
            "processed_paragraphs": len(result), 
            "data": result
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Critical error during ingest: {str(e)}"
        )
        
#########
# Query
#########
@app.get(
    "/api/projects/entries",
    tags=["Query"],
    description="Get ChromaDB records by collection ID"
    )
async def get_entries(project_id: str, limit: int = 50, offset: int = 0):
    try:
        formatted_entries = await chroma.get_db_entries(app, project_id, limit=limit, offset=offset)
        return {"entries": formatted_entries, "count": len(formatted_entries)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    
@app.post(
    "/api/query",
    tags=["Query"],
    description="Exceute vector search in ChromaDB and elaborate response with LLM"
    )
async def query_project(
    project_id: str = Form(...), 
    text: str = Form(...), 
    limit: int = Form(10)
):
    
    async def event_generator():
        async for chunk in query_pipe.generate_answer(app, project_id, text, limit):
            yield f"data: {json.dumps(chunk)}\n\n"
        
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


################################################################
########################## FRONTEND ############################
################################################################
@app.get(
    "/", 
    tags=["WebUI"],
    response_class=HTMLResponse, 
    include_in_schema=False
    )
async def render_frontend():
    html_path = Path("src/index.html")
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")