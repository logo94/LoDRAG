# FastAPI
from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool
from typing import List

# ChromaDB
import chromadb
from chromadb.utils import embedding_functions

# Utils
import src.utils.models as models


async def start_db_client(app: FastAPI):
    
    db_path = app.state.base_dir / "db"
    
    if not db_path.exists():
        db_path.mkdir(parents=True, exist_ok=True)
        print(f"Database directory created at: {db_path}")
    
    app.state.chroma_client = chromadb.PersistentClient(str(db_path))
        
    try:
        app.state.emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=app.state.models["embedding"]["repo_id"]
        )
    except Exception as err:
        print('Error loading embedding function: ', str(err))
        return False
    
    app.state.projects = {}
    app.state.chroma_collections = {}

    for col in app.state.chroma_client.list_collections():
        name = col if isinstance(col, str) else col.name
        collection = await run_in_threadpool(
            app.state.chroma_client.get_collection,
            name=name,
            embedding_function=app.state.emb_fn
        )
        meta = {k: v for k, v in (collection.metadata or {}).items() if not k.startswith("hnsw:")}
        app.state.projects[name] = {"id": name, **meta}
        if "language" not in meta:
            print(f"[WARN] progetto '{name}' senza lingua nei metadata (creato prima della migrazione?)")
        app.state.chroma_collections[name] = collection
        print(f"Collection initialized for project: {name}")
        
    return True
    

async def create_db_collection(app: FastAPI, project_data: models.projectModel):
    
    pid = project_data["id"]
    
    collection = await run_in_threadpool(
        app.state.chroma_client.get_or_create_collection,
        name=pid,
        embedding_function=app.state.emb_fn,
        metadata={
            "hnsw:space": app.state.models["embedding"]["config"]["distance_metric"],
            "description": project_data.get("description", ""),
            "language": project_data.get("language", "en"),
        }
    )
    
    # Update app state collections
    app.state.chroma_collections[pid] = collection
    app.state.projects[pid] = {
        "id": pid,
        "description": project_data.get("description", ""),
        "language": project_data.get("language", "en"),
    }
    return collection


async def delete_project(project_id: str, app: FastAPI):
    
    try:
        await run_in_threadpool(app.state.chroma_client.delete_collection, name=project_id)
    except Exception as chroma_err:
        print(f"[Chroma Alert] Collezione non trovata o già rimossa: {chroma_err}")

    app.state.projects.pop(project_id, None)
    app.state.chroma_collections.pop(project_id, None)

    return True


async def get_db_entries(
    app: FastAPI, 
    project_id: str, 
    limit: int = 100, 
    offset: int = 0
):
    collection = app.state.chroma_collections.get(project_id)
    
    if not collection:
        raise Exception(f"Collection '{project_id}' not found")
    
    data = await run_in_threadpool(
        collection.get,
        limit=limit,
        offset=offset
    )
    
    formatted_entries = []
    for i in range(len(data['ids'])):
        formatted_entries.append({
            "id": data['ids'][i],
            "document": data['documents'][i],
            "metadata": data['metadatas'][i]
        })
    
    return formatted_entries

async def query_db_entries(
    app: FastAPI, 
    project_id: str, 
    query_text: str, 
    limit: int = 10
):

    collection = app.state.chroma_collections.get(project_id)
    if not collection:
        raise Exception(f"Project '{project_id}' not found")
    
    distance_threshold = app.state.models.get('embedding').get("config").get("distance_threshold", 0.60)
    
    raw_results = await run_in_threadpool(
        collection.query,
        query_texts=[query_text],
        n_results=limit
    )
    
    if not raw_results or not raw_results.get("documents"):
        return []
    
    formatted_query_entries = []
    
    for doc, meta, _id, dist in zip(
        raw_results["documents"][0], 
        raw_results["metadatas"][0], 
        raw_results["ids"][0], 
        raw_results["distances"][0]
    ):
        if dist <= distance_threshold:
            formatted_query_entries.append({
                "id": _id,
                "document": doc,
                "metadata": meta,
                "score": round(1 - dist, 3)
            })
            
            if len(formatted_query_entries) == limit:
                break
            
    return formatted_query_entries

    
async def add_db_entries_batch(app: FastAPI, project_id: str, documents: List[str], metadatas: List[dict], ids: List[str]):
    
    collection = app.state.chroma_collections.get(project_id)
    
    if not collection:
        raise Exception(f"Collection '{project_id}' not found")
    
    await run_in_threadpool(
        collection.add,
        documents=documents,
        metadatas=metadatas,
        ids=ids
    )
    
