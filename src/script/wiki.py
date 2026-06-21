# FastAPI
from fastapi import FastAPI

# Utils
from src.utils.api import wikidata_api_call


async def get_items_by_id(app: FastAPI, ids: list):
    if not ids:
        return {"entities": {}}
    
    chunk_size = app.state.config["wikidata_api_chunk_size"]
    language = app.state.language

    all_entities = {}

    for i in range(0, len(ids), chunk_size):
        chunk = ids[i:i + chunk_size]

        params = {
            "action": "wbgetentities",
            "ids": "|".join(chunk),
            "props": "labels|aliases|descriptions|claims|sitelinks",
            "languages": f"{language}|en",
            "format": "json"
        }

        data = await wikidata_api_call(params)
        if not data:
            continue
        
        entities = data.get("entities", {})
        for qid, item in entities.items():
            cleaned_entity = await clean_response_object(qid, item)
            if cleaned_entity:
                all_entities[qid] = cleaned_entity

    return {
        "entities": all_entities
    }


async def get_schema_details(app: FastAPI):

    config_schema = app.state.schema
    config_entities = config_schema.get("entities", {})
    allowed_authority_pids = config_schema.get("allowed_external_authority_pids", [])
    
    # Extract all QIDs and property IDs from the configuration for batch fetching
    all_qids = []
    all_property_ids = set()
    for macro_data in config_entities.values():
        if isinstance(macro_data, dict):
            all_qids.extend(macro_data.get("qids", []))
            for pid in macro_data.get("relations", []):
                all_property_ids.add(pid)
    
    # Unique QIDs and property IDs to avoid redundant API calls
    all_qids = list(set(all_qids))

    # Wikidata entities Fetch
    wikidata_qids = {}
    if all_qids:
        qids_response = await get_items_by_id(app, ids=all_qids)
        wikidata_qids = qids_response.get("entities", {}) if qids_response else {}
    
    # Wikidata property fetch
    wikidata_pids = {}
    if all_property_ids:
        pids_response = await get_items_by_id(app, ids=list(all_property_ids))
        wikidata_pids = pids_response.get("entities", {}) if pids_response else {}
        
    # Build enriched schema with Wikidata data, ensuring that only valid QIDs and properties are included, and that descriptions are optimized for GLiNER's schema builder.
    enriched_schema = {
        "entities": {},
        "allowed_external_authority_pids": allowed_authority_pids
    }
    
    for macro_name, macro_data in config_entities.items():
        enriched_schema["entities"][macro_name] = {
            "description": macro_data.get("description", ""),
            "qids": [],
            "relations": []
        }
        
        for qid in macro_data.get("qids", []):
            if qid in wikidata_qids:
                enriched_schema["entities"][macro_name]["qids"].append(wikidata_qids[qid])
                
        for pid in macro_data.get("relations", []):
            if pid in wikidata_pids:
                enriched_schema["entities"][macro_name]["relations"].append(wikidata_pids[pid])

    return enriched_schema

async def get_wikidata_candidates(app: FastAPI, label: str, target_class: str):

    params = {
        "action": "wbsearchentities",
        "format": "json",
        "language": app.state.language,
        "usselang": app.state.language,
        "search": label,
        "type": "item"
    }
    
    data = await wikidata_api_call(params)
    if not data:
        return {"entities": {}}
    
    candidates = data.get("search", [])
    
    if not candidates and app.state.language != "en":
        params["language"] = "en"
        params["usselang"] = "en"
        data = await wikidata_api_call(params)
        candidates = data.get("search", []) if data else []
        
    qids = [c["id"] for c in candidates if "id" in c]
    
    if not qids:
        return {"entities": {}}
    
    response = await get_items_by_id(app, ids=qids)
    
    if response and "entities" in response:
        raw_candidates = response["entities"]
    else:
        raw_candidates = response if response else {}
        
    filtered_candidates = {}
    
    schema = getattr(app.state, "schema", {})
    entity_constraints = schema.get("entities", {})
    macro_config = entity_constraints.get(target_class, {})
    
    allowed_qids = set(macro_config.get("qids", []))
    allowed_relations = macro_config.get("relations", [])

    for qid, entity_data in raw_candidates.items():
        if not allowed_qids:
            filtered_candidates[qid] = entity_data
            continue
        
        instance_of = entity_data.get("P31", [])
        subclass_of = entity_data.get("P279", [])
        all_mapped_classes = set(instance_of + subclass_of)
        all_mapped_classes.add(qid)
        
        if allowed_qids.intersection(all_mapped_classes):
            filtered_candidates[qid] = entity_data
            continue
        
        has_structural_relation = any(entity_data.get(prop) is not None for prop in allowed_relations)
        
        if target_class == "place" and entity_data.get("P625") is not None:
            has_structural_relation = True
            
        if target_class == "person" and entity_data.get("P1441") is not None:
            has_structural_relation = True
            
        if has_structural_relation:
            filtered_candidates[qid] = entity_data
            continue
        
        if target_class == "concept":
            # Class exclusions
            strong_categories_noise = {
                # 1. Biographical and creative works
                "Q5",        # Human
                "Q571",      # Book / Novel
                "Q11424",    # Film
                "Q202866",   # Animated film
                "Q5398426",  # Television series
                
                # 2. Music
                "Q7366",     # Song / Music track
                "Q58483083", # Musical drama work
                "Q482994",    # Music album
                
                # 3. Places and administration
                "Q515",      # City
                "Q1549592",  # Geopolitical entity / Historical state
                
                # 4. Print and media
                "Q11032"     # Newspaper / Daily paper
            }
            
            if not strong_categories_noise.intersection(all_mapped_classes):
                filtered_candidates[qid] = entity_data
                continue
    
    return {
        "entities": filtered_candidates
    }
    

##############################################
# HELPERS
##############################################
async def clean_response_object(qid: str, raw_item: dict):
    if not raw_item:
        return None

    clean_item = {
        'pid' if qid.startswith('P') else 'qid': qid
    }

    for field in ['labels', 'descriptions']:
        field_data = raw_item.get(field, {})
        parsed_field = {
            lang: data.get("value") if isinstance(data, dict) else data
            for lang, data in field_data.items()
        }
        clean_item[field] = parsed_field

    aliases = raw_item.get("aliases", {})
    parsed_aliases = {
        lang: [
            alias.get("value") for alias in alias_list
            if isinstance(alias, dict) and "value" in alias
        ]
        for lang, alias_list in aliases.items()
    }
    clean_item['aliases'] = parsed_aliases

    claims = raw_item.get("claims", {})
    for pid, claim_list in claims.items():
        
        clean_item[pid] = []
        
        for claim in claim_list:
            mainsnak = claim.get("mainsnak", {})
            datatype = mainsnak.get("datatype")
            
            # Items
            if datatype == "wikibase-item":
                value = mainsnak.get("datavalue", {}).get("value", {})
                value_id = value.get("id")
                if value_id and value_id not in clean_item[pid]:
                    clean_item[pid].append(value_id)
            
            # Authorities
            elif datatype in ["string", "external-id"]:
                value_str = mainsnak.get("datavalue", {}).get("value")
                if value_str and value_str not in clean_item[pid]:
                    clean_item[pid].append(value_str)

    clean_item['sitelinks'] = raw_item.get("sitelinks", {})

    return clean_item