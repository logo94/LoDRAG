# FastAPI
from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool

# Scripts
import src.script.wiki as wiki

# Utils
import src.utils.files as files


async def load_config_files(app: FastAPI):
    
    config_dir = app.state.base_dir / "config"
    config_dir.mkdir(exist_ok=True)
    
    json_files = list(config_dir.glob("*.json"))
    loaded_configs = {}
    
    for file_path in json_files:
        config_key = file_path.stem 
        try:
            content = await run_in_threadpool(files.read_json_file, file_path)
            loaded_configs[config_key] = content
            print(f"Loaded: config/{file_path.name} -> app.state.{config_key}")
        except Exception as e:
            print(f"Error loading {file_path.name}: {e}")
            return False
    
    # Dinamic setting of app.state attributes based on loaded config files
    for key, data in loaded_configs.items():
        setattr(app.state, key, data)
        
    if "config" in loaded_configs:
        app.state.language = loaded_configs["config"].get("language", "en")

    # Enriched schema loading with fallback to generation if not present or empty
    if "enriched_schema" in loaded_configs and loaded_configs["enriched_schema"]:
        print("Enriched schema loaded from local file (cache active).")
        app.state.enriched_schema = loaded_configs["enriched_schema"]
    else:
        new_schema = await update_config_schema(app)
        if not new_schema:
            return False
        
    return True


async def update_config_schema(app: FastAPI):
    
    if not hasattr(app.state, 'schema'):
        print("Error: schema.json not found, impossible to generate enriched_schema")
        return None
    
    try:
        enriched_schema = await wiki.get_schema_details(app)
        app.state.enriched_schema = enriched_schema
        
        enriched_path = app.state.base_dir / "config" / "enriched_schema.json"
        await run_in_threadpool(files.write_json_file, enriched_path, enriched_schema)
        print(f"Enriched schema saved successfully to local file: {enriched_path}")
        
        return enriched_schema
        
    except Exception as e:
        print(f"Critical error during enriched_schema generation: {e}")
        app.state.enriched_schema = {}
        return {}
    
    
async def update_config_file(app: FastAPI, config_key: str, new_content: dict):
    
    if not hasattr(app.state, config_key):
        print(f"Error: {config_key}.json not found in app.state")
        return False
    
    setattr(app.state, config_key, new_content)
    
    config_path = app.state.base_dir / "config" / f"{config_key}.json"
    await run_in_threadpool(files.write_json_file, config_path, new_content)
    print(f"Config file {config_key}.json updated successfully.")
    
    return new_content
