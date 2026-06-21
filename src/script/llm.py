# Default
import os

# FastAPI
from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool, iterate_in_threadpool

# Llama (LLM)
from llama_cpp import Llama

# HuggingFace Hub
from huggingface_hub import hf_hub_download

# Utils
import src.utils.files as files


async def load_llm(app: FastAPI):
    
    model_config = app.state.models["llm"]
    models_dir = app.state.base_dir / "models"
    
    if not os.path.exists(models_dir):
        os.makedirs(models_dir)
    
    repo_id = model_config.get("repo_id")
    filename = model_config.get("filename")
    
    if repo_id:
        model_path = await run_in_threadpool(
            hf_hub_download,
            repo_id=repo_id,
            filename=filename,
            cache_dir=models_dir 
        )
    else:
        model_path = os.path.join(models_dir, filename)
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model not found: {model_path}")
    
    app.state.llm = await run_in_threadpool(
        Llama,
        model_path=model_path,
        n_ctx=model_config["config"]["n_ctx"],
        n_threads=model_config["config"]["n_threads"],
        top_p=model_config["config"]["top_p"],
        n_batch=model_config["config"]["n_batch"],
        f16_kv=True,
        verbose=False
    )
    
    return True

async def expand_text(app, paragraphs: list[str]):
    
    template = app.state.models['llm']['config']['chat_template']
    prompts = files.read_json_file("config/prompts.json")
    config = prompts["expansion_task"]
    system_rules = "\n".join(config["system_rules"])
    
    results = []

    for paragraph in paragraphs:
        
        full_prompt = (
            f"{template['system_start']}{system_rules}{template['system_end']}"
            f"{template['user_start']}{paragraph}{template['user_end']}"
            f"{template['assistant_start']}"
        )
        
        response = await run_in_threadpool(
            app.state.llm,
            full_prompt,
            max_tokens=config["max_tokens"],
            temperature=config["temperature"],
            stop=app.state.models['llm']['config']["stop"]
        )
        
        result = response["choices"][0]["text"].strip()
        results.append(result)
            
    return results
    
    
async def generate_final_answer(app, extracted_data: dict, user_query: str):
    
    prompts = files.read_json_file("config/prompts.json")
    config = prompts["final_response_task"]
    system_rules = "\n".join(config["system_rules"])
    
    template = app.state.models['llm']['config']['chat_template']
    
    full_prompt = (
        f"{template['system_start']}{system_rules}{template['system_end']}"
        f"{template['user_start']}### CONTEXT:\n[PARAGRAPHS]\n{extracted_data['paragraphs']}\n\n[ENTITY DETAILS]\n{extracted_data['entities']}\n\n### USER QUERY:\n{user_query}{template['user_end']}"
        f"{template['assistant_start']}"
    )
    
    def get_stream():
        return app.state.llm(
            prompt=full_prompt,
            max_tokens=config["max_tokens"],
            temperature=config["temperature"],
            repeat_penalty=config["repeat_penalty"],
            top_p=config["top_p"],
            top_k=config["top_k"],
            stop=app.state.models['llm']['config']["stop"],
            stream=True
        )
        
    async for chunk in iterate_in_threadpool(get_stream()):
        token = chunk["choices"][0].get("text", "")
        if token:
            yield token