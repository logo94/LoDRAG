# Default
import time

# FastAPI
from fastapi import FastAPI

# Scripts
from src.script.config import load_config_files
from src.script.chroma import start_db_client
from src.script.llm import load_llm
from src.script.gliner import load_gliner


async def startup_load(app: FastAPI):
    
    start_time = time.time()

    try:
        # Config file loading
        ok = await load_config_files(app)
        if not ok:
            raise RuntimeError("Caricamento configurazione fallito, vedi log sopra")
        print("Config files loaded")
        
        # ChromaDB Client startup
        await start_db_client(app)
        print(f"ChromaDB Client started with embedding function {app.state.models['embedding']['repo_id']}")

        # GLiNER2 loading
        await load_gliner(app)
        print(f"GLiNER2 ({app.state.models['gliner']['repo_id']}) loaded...")

        # Llama (LLM) loading
        await load_llm(app)
        print(f"LLM ({app.state.models['llm']['filename']}) loaded...")

        total_duration = time.time() - start_time
        print(f"Startup completed in {total_duration:.2f} seconds")

    except Exception as e:
        raise e