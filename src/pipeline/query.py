# Default
import json

# Scripts
import src.script.chroma as chroma
import src.script.llm as llm


async def generate_answer(app, project_id: str, query: str, limit: int):
    
    app.state.language = app.state.projects.get(project_id, {}).get("language", "en")
    
    # Get relevant entries from ChromaDB
    results = await chroma.query_db_entries(app, project_id, query, limit)
        
    documents_list = [item["document"] for item in results]
    paragraphs_str = "\n\n".join(documents_list)
    
    entities_context_str = ""
    seen_qids = set()
    
    for item in results:
        
        metadata = item.get("metadata", {})
        entities_json = metadata.get("entities_json", "{}")
        
        readable_entities = json.loads(entities_json) if isinstance(entities_json, str) else entities_json
        
        # Preparing a context string with unique entities and their descriptions, avoiding duplicates based on Wikidata QIDs
        for macro_class, items in readable_entities.items():
            for item_ent in items:

                recon = item_ent.get("reconciliation") or item_ent
                
                if recon and not item_ent.get("rejected") and not (isinstance(recon, dict) and recon.get("rejected")):
                    qid = recon.get("wikidata_id")
                    
                    if qid and qid not in seen_qids:
                        seen_qids.add(qid)
                        label = recon.get("label_wikidata") or item_ent.get("name") or item_ent.get("text") or "N/A"
                        description = recon.get("description", "N/A")
                        entities_context_str += f"- {label}: {description}\n"
    
    # First yield the retrieved documents and entities as context for the answer generation
    yield {
        "type": "results", 
        "data": results
    }
    
    # Then generate the answer token by token using the LLM, providing both the retrieved documents and the entities context
    context_data = {
        "paragraphs": paragraphs_str,
        "entities": entities_context_str
    }
    async for token in llm.generate_final_answer(app, context_data, query):
        yield {"type": "stream", "token": token}
