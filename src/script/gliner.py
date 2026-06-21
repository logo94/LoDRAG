# Default
import asyncio

# FastAPI
from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

# GLiNER2
from gliner2 import GLiNER2

# Scripts
import src.script.wiki as wiki

async def load_gliner(app: FastAPI):
    
    extractor = await run_in_threadpool(GLiNER2.from_pretrained, app.state.models['gliner']['repo_id'])
    
    app.state.extractor = extractor
    
    enriched_schema = await wiki.get_schema_details(app)
    
    app.state.enriched_schema = enriched_schema
    
    schema_builder = await build_gliner_schema(app.state.extractor, enriched_schema)
    
    app.state.schema_builder = schema_builder
    
    return True


async def build_gliner_schema(extractor, enriched_schema: dict):

    config_entities = enriched_schema.get("entities", {})
    
    macro_entities_defs = {}
    for macro_name, macro_data in config_entities.items():
        macro_entities_defs[macro_name] = macro_data.get(
            "description", 
            f"Represents entities of type {macro_name}."
        )

    # Gliner schema builder initialization
    schema_builder = extractor.create_schema()
    schema_builder = schema_builder.entities(macro_entities_defs)


    for macro_name, macro_data in config_entities.items():

        struct_config = schema_builder.structure(macro_name)
        
        struct_config = struct_config.field("name", dtype="str")

        # Extract and optimize property descriptions for GLiNER schema builder
        allowed_relations = macro_data.get("relations", [])
        for prop in allowed_relations:
            pid = prop.get("pid")
            if not pid:
                continue
                
            # Label cleaning: normalize to lowercase and replace spaces and special characters with underscores
            raw_prop_name = prop.get("labels", {}).get("en") or pid
            prop_label = (
                str(raw_prop_name).lower()
                .replace(" ", "_")
                .replace("-", "_")
                .replace("/", "_")
                .replace("'", "")
            )

            # Get the English description from Wikidata, if available
            wiki_prop_desc = prop.get("descriptions", {}).get("en", "").strip()
            
            # If no description is available, create a default one. Otherwise, truncate to the first sentence and ensure it is concise (max 90 characters).
            if not wiki_prop_desc:
                short_desc = f"Property representing {prop_label.replace('_', ' ')}."
            else:
                if "." in wiki_prop_desc:
                    short_desc = wiki_prop_desc.split(".")[0].strip() + "."
                else:
                    short_desc = wiki_prop_desc
                
                if ";" in short_desc:
                    short_desc = short_desc.split(";")[0].strip() + "."

            # Length check: if the description exceeds 90 characters, truncate and add ellipsis
            if len(short_desc) > 90:
                short_desc = short_desc[:87] + "..."

            # Inject the property into the GLiNER schema builder with the cleaned label and optimized description
            struct_config = struct_config.field(
                prop_label, 
                dtype="list", 
                description=short_desc
            )

    return schema_builder


async def extract_structured_data(app: FastAPI, paragraphs: list[str]):
    
    tasks = [
        run_in_threadpool(
            app.state.extractor.extract,
            p, 
            app.state.schema_builder,
            threshold=app.state.models['gliner']["config"]['threshold'],
            include_confidence=True
        )
        for p in paragraphs
    ]
    
    return await asyncio.gather(*tasks)


def extract_graph_relations(gliner_data: dict, app: FastAPI) -> list:

    relations = []
    schema_entities = app.state.schema.get("entities", {})
    
    local_reconciliation_map = {}
    for macro_class, items in gliner_data.get("entities", {}).items():
        for item in items:
            txt = item.get("text")
            if txt:
                local_reconciliation_map[txt.lower()] = {
                    "recon": item.get("reconciliation", {"rejected": True}),
                    "macro_class": macro_class
                }

    for macro_class, instances in gliner_data.items():
        if macro_class == "entities":
            continue
            
        if isinstance(instances, list):
            for instance in instances:
                if not isinstance(instance, dict):
                    continue
                
                subject_text = None
                if instance.get("name") and isinstance(instance["name"], dict):
                    subject_text = instance["name"].get("text")
                
                if not subject_text:
                    for role, role_vals in instance.items():
                        if role != "name" and isinstance(role_vals, list):
                            for r_val in role_vals:
                                r_txt = r_val.get("text", "")
                                r_data = local_reconciliation_map.get(r_txt.lower())
                                if r_data and r_data["macro_class"] == macro_class:
                                    subject_text = r_txt
                                    break
                            if subject_text: break

                if not subject_text:
                    continue
                
                sub_data = local_reconciliation_map.get(subject_text.lower())
                if not sub_data or sub_data["recon"].get("rejected"):
                    continue
                
                for gliner_predicate, targets in instance.items():
                    if gliner_predicate == "name" or not isinstance(targets, list):
                        continue
                        
                    for target in targets:
                        if not isinstance(target, dict) or "text" not in target:
                            continue
                            
                        object_text = target["text"]
                        obj_data = local_reconciliation_map.get(object_text.lower())
                        
                        if not obj_data or obj_data["recon"].get("rejected"):
                            continue
                        
                        sub_qid = sub_data["recon"].get("wikidata_id")
                        obj_qid = obj_data["recon"].get("wikidata_id")
                        
                        if subject_text.lower() == object_text.lower():
                            continue
                        if sub_qid and obj_qid and sub_qid == obj_qid:
                            continue
                        
                        wikidata_p = None
                        final_predicate_label = gliner_predicate
                        
                        sub_class = sub_data["macro_class"]
                        sub_schema = schema_entities.get(sub_class, {})
                        schema_relations = sub_schema.get("relations", {})
                        
                        if gliner_predicate in schema_relations:
                            schema_val = schema_relations[gliner_predicate]
                            if isinstance(schema_val, dict):
                                wikidata_p = schema_val.get("p_id") or schema_val.get("id")
                                final_predicate_label = schema_val.get("label", final_predicate_label)
                            elif isinstance(schema_val, str):
                                wikidata_p = schema_val
                        else:
                            print(f"[Schema Missing] La classe '{sub_class}' non ha la relazione '{gliner_predicate}' nel file config.")

                        relations.append({
                            "subject": {
                                "id": sub_qid, 
                                "label": sub_data["recon"].get("label_wikidata") or subject_text,
                                "type": sub_class
                            },
                            "predicate": {
                                "p_id": wikidata_p,
                                "label": final_predicate_label
                            },
                            "object": {
                                "id": obj_qid, 
                                "label": obj_data["recon"].get("label_wikidata") or object_text,
                                "type": obj_data["macro_class"],
                                "confidence": target.get("confidence", 1.0)
                            }
                        })
                            
    return relations