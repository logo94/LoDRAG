# Default
import asyncio

# FastAPI
from fastapi import FastAPI

# Scripts
import src.script.wiki as wiki
import src.script.rank as rank

async def reconcile_with_wikidata(
    app: FastAPI, 
    gliner_outputs: list[dict], 
    app_cache: dict, 
    alias_cache: dict
    ):
    
    macro_classes_map = app.state.schema.get("entities", {})
        
    # Gliner outputs iteration: for each paragraph, extract entities and their relations, prepare API calls to Wikidata, execute them in parallel, and then rank and filter candidates based on the enriched schema and relation context. Update the gliner output with reconciliation results and maintain caches for optimization.
    for gliner_output in gliner_outputs:
        entities = gliner_output.get("entities", {})
        
        # Extracting relations from GLiNER output to use as context for candidate ranking, mapping mention texts to their associated relation attributes and subjects for later use in coherence scoring during candidate evaluation
        gliner_relations_map = {}
        subject_of_map = {}
        for key, instances in gliner_output.items():
            if key == "entities": continue
            if isinstance(instances, list):
                for instance in instances:
                    if isinstance(instance, dict):
                        
                        name_field = instance.get("name")
                        subject_txt = None
                        if isinstance(name_field, dict) and name_field.get("text"):
                            subject_txt = name_field["text"].lower()
                        
                        for rel_attr, rel_values in instance.items():
                            if isinstance(rel_values, list):
                                for val in rel_values:
                                    if isinstance(val, dict) and "text" in val:
                                        txt = val["text"]
                                        if txt:
                                            mention_txt = txt.lower()
                                            if mention_txt not in gliner_relations_map:
                                                gliner_relations_map[mention_txt] = []
                                            gliner_relations_map[mention_txt].append(rel_attr)

                                            if subject_txt and subject_txt != mention_txt:
                                                subject_of_map.setdefault(mention_txt, []).append(
                                                    (rel_attr, subject_txt)
                                                )

        tasks = []                          
        task_mapping = []

        for macro_class, entity_list in entities.items():
            
            if macro_class not in macro_classes_map: continue
            if macro_class not in app_cache: app_cache[macro_class] = {}
            if macro_class not in alias_cache: alias_cache[macro_class] = {}
            
            sorted_entities = sorted(entity_list, key=lambda x: len(x.get("text") or ""), reverse=True)

            for entity in sorted_entities:
                raw_text = entity.get("text")
                if not raw_text:
                    continue
                
                mention_text = raw_text.lower()
                
                if mention_text in app_cache[macro_class]:
                    entity["reconciliation"] = app_cache[macro_class][mention_text]
                    continue
                
                if macro_class in ["person", "work"]:
                    match_trovato = False
                    for alias_suffix, result in alias_cache[macro_class].items():
                        if mention_text.endswith(alias_suffix):
                            entity["reconciliation"] = result
                            match_trovato = True
                            break
                    if match_trovato: continue
                    
                active_relations = gliner_relations_map.get(mention_text, [])
                task = wiki.get_wikidata_candidates(app, mention_text, macro_class)
                tasks.append(task)
                task_mapping.append((entity, macro_class, mention_text, active_relations))
            

        if tasks:
            
            responses = await asyncio.gather(*tasks, return_exceptions=True)

            mention_to_candidates = {}
            for k, (_, _, mtext_k, _) in enumerate(task_mapping):
                resp_k = responses[k]
                if not isinstance(resp_k, Exception) and resp_k:
                    mention_to_candidates[mtext_k] = resp_k.get("entities", {})

            label_to_pid = {}
            for cls_cfg in getattr(app.state, "enriched_schema", {}).get("entities", {}).values():
                for prop in cls_cfg.get("relations", []):
                    pid = prop.get("pid")
                    raw = prop.get("labels", {}).get("en") or pid
                    if pid and raw:
                        clean = (str(raw).lower().replace(" ", "_")
                                 .replace("-", "_").replace("/", "_").replace("'", ""))
                        label_to_pid.setdefault(clean, pid)
            
            for i, (entity, macro_class, mention_text, active_relations) in enumerate(task_mapping):
            
                response = responses[i]
            
                if mention_text in app_cache[macro_class]:
                    entity["reconciliation"] = app_cache[macro_class][mention_text]
                    continue
                
                if isinstance(response, Exception) or not response:
                    entity["reconciliation"] = {
                        "rejected": True,
                        "score": 0.0,
                        "reason": "Errore durante la chiamata API di riconciliazione."
                    }
                    continue

                candidates = response.get("entities", {})
                
                coherent_qids = set()
                for rel_attr, subject_txt in subject_of_map.get(mention_text, []):
                    pid = label_to_pid.get(rel_attr)
                    if not pid:
                        continue
                    for subj_cand in mention_to_candidates.get(subject_txt, {}).values():
                        for v in subj_cand.get(pid, []):
                            coherent_qids.add(str(v))
                
                # Ranking
                evaluated_list = rank.rank_and_filter_candidates(
                    mention=mention_text,
                    candidates=candidates,
                    app=app,
                    macro_class=macro_class,
                    active_gliner_relations=active_relations,
                    coherent_qids=coherent_qids
                )
                
                if evaluated_list:
                    
                    best_match = evaluated_list[0]
                    meta = best_match.get("reconciliation_meta", {})
                    score = meta.get("score", 0.0)
                    
                    lang = app.state.language
                    label = best_match.get("labels", {}).get(lang) or best_match.get("labels", {}).get("en", "")
                    description = best_match.get("descriptions", {}).get(lang) or best_match.get("descriptions", {}).get("en", "")
                    
                    reconciliation_result = {
                        "wikidata_id": best_match.get("qid") or best_match.get("id"),
                        "score": score,
                        "label_wikidata": label,
                        "description": description,
                    }
                    
                    if score < app.state.config.get('wikidata_threshold', 0.5):
                        reconciliation_result["rejected"] = True
                        reconciliation_result["reason"] = f"Score sotto soglia ({score:.2f} < threshold)"
                
                else:        
                    reconciliation_result = {"rejected": True, "score": 0.0, "reason": "No match"}
                
                # App cache update with the reconciliation result for the current mention and macro class, to optimize future lookups and avoid redundant API calls for the same mention in subsequent paragraphs or entities. Additionally, for person and work macro classes, maintain an alias cache mapping suffixes of entity names to their reconciliation results to further enhance matching capabilities for mentions that may only partially match cached entries.
                app_cache[macro_class][mention_text] = reconciliation_result
                
                if macro_class in ["person", "work"] and not reconciliation_result.get("rejected"):

                    tokens = mention_text.lower().split()
                    suffix = tokens[-1] if len(tokens) > 1 else mention_text
                    
                    if len(suffix) > 2:
                        existing = alias_cache[macro_class].get(suffix)
                        if existing and existing["wikidata_id"] != reconciliation_result["wikidata_id"]:
                            del alias_cache[macro_class][suffix]
                        else:
                            alias_cache[macro_class][suffix] = reconciliation_result
                
                entity["reconciliation"] = reconciliation_result
                
    return gliner_outputs