# Default
import time

# FastAPI
from fastapi import FastAPI
import json

# Utils
import src.utils.files as files

# Scripts
import src.script.llm as llm
import src.script.gliner as gliner
import src.script.reconcilier as reconcilier
import src.script.chroma as chroma


async def ingest_text(app: FastAPI, text: str, project_id: str, ai_mode: bool = False, test_mode: bool = False):
    
    app.state.language = app.state.projects.get(project_id, {}).get("language", "en")
    
    start_time = time.time()
    print("Start processing text...")
    
    # Split text in paragraphs
    paragraphs = await files.split_text_in_paragraphs(text)
    
    split_time = time.time() - start_time
    print(f"Text splitted in {split_time:.2f} seconds")
    
    ingest_start = time.time()
    
    app_cache = {
        "person": {}, "place": {}, "work": {}, "concept": {}, "organization": {}
    }
    
    alias_cache = {
        "person": {}, "place": {}, "work": {}, "concept": {}, "organization": {}
    }
    
    final_output = []
    
    batch_size = app.state.config.get('ingest_batch_size', 1)
    
    for i in range(0, len(paragraphs), batch_size):
        batch = paragraphs[i : i + batch_size]
        
        try:
            # Expand and simplify text by LLM
            simplified_batch = await llm.expand_text(app, batch) if ai_mode else batch
        except Exception as err:
            print(err)
            simplified_batch = batch
            
        # Extract information with gliner
        structured_data_batch = await gliner.extract_structured_data(app, simplified_batch)
        
        # Reconciliation
        reconciliation_ok = True
        try:
            await reconcilier.reconcile_with_wikidata(
                app, 
                structured_data_batch, 
                app_cache,
                alias_cache
            )
        except Exception as err:
            print(err)
            reconciliation_ok = False
                
        # Chroma entries
        chroma_ids = []
        chroma_texts = []
        chroma_metadatas = []
        
        for j in range(len(batch)):
            
            orig_text = batch[j]
            simplified_text = simplified_batch[j]
            gliner_data = structured_data_batch[j]
                        
            paragraph_id = f"{i + j:06d}"
            
            readable_entities = {mc: [] for mc in app_cache.keys()}
            accepted_entities = []
            rejected_entities = []
            
            # Reconciliation results formatting
            for macro_class, items in gliner_data.get("entities", {}).items():
                for item in items:
                    
                    rec = item.get("reconciliation", {"rejected": True, "reason": "No reconciliation"})
            
                    if rec and not rec.get("rejected"):
                        
                        entity_info = rec.copy()
                
                        entity_info["name"] = item.get("text")
                        
                        readable_entities[macro_class].append(entity_info)
                        
                        accepted_entities.append({
                            "wikidata_id": rec.get("wikidata_id"),
                            "name": item.get("text"),
                            "label": rec.get("label_wikidata"),
                            "description": rec.get("description"),
                            "score": rec.get("score", 0.0)
                        })            

                    else:
                        rejected_entities.append({
                            "name": item.get("text"),
                            "reason": rec.get("reason", "No match"),
                            "score": rec.get("score", 0.0),
                            "wikidata_id": rec.get("wikidata_id") if "wikidata_id" in rec else None,
                            "label_wikidata": rec.get("label_wikidata") if "label_wikidata" in rec else None,
                            "description": rec.get("description") if "description" in rec else None
                        })

            # Extracted relations formatting
            try:
                extracted_relations = gliner.extract_graph_relations(gliner_data, app)
            except Exception as err:
                print(err)
                extracted_relations = []

            # Final result formatting
            paragraph_result = {
                "id_paragrafo": paragraph_id,
                "testo_originale": orig_text,
                "testo_semplificato": simplified_text,
                "accepted_entities": accepted_entities,
                "rejected_entities": rejected_entities,
                "entities": readable_entities,
                "relations": extracted_relations
            }
            final_output.append(paragraph_result)
            
            chroma_ids.append(paragraph_id)
            chroma_texts.append(orig_text)
            chroma_metadatas.append({
                "source_type": "paragraph",
                "testo_semplificato": simplified_text,
                "entities_json": json.dumps(readable_entities), 
                "relations_json": json.dumps(extracted_relations)
            })
        
        # Insert in ChromaDB if not in test mode and reconciliation was successful
        if not test_mode and reconciliation_ok:
            try:
                await chroma.add_db_entries_batch(
                    app=app,
                    project_id=project_id,
                    documents=chroma_texts,
                    metadatas=chroma_metadatas,
                    ids=chroma_ids
                )
            except Exception as e:
                print(f"[Chroma] insert error {i}: {e}")
                continue
            
    ingest_time = time.time() - ingest_start
    print(f"{len(paragraphs)} paragraphs processed in {ingest_time:.2f} seconds")
    
    return final_output