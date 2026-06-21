# Default
import math
from difflib import SequenceMatcher

# FastAPI
from fastapi import FastAPI


def rank_and_filter_candidates(
    mention: str,
    candidates: list | dict,
    app: FastAPI,
    macro_class: str,
    active_gliner_relations: list | dict,
    coherent_qids: set | None = None
) -> list:

    if not candidates:
        return []

    # Candidates normalization: support both list and dict formats, ensuring we always work with a list of candidate dicts
    normalized_candidates = []
    if isinstance(candidates, list):
        normalized_candidates = candidates
    elif isinstance(candidates, dict):
        for qid, data in candidates.items():
            if isinstance(data, dict):
                if "qid" not in data:
                    data["qid"] = qid
                normalized_candidates.append(data)

    if not normalized_candidates:
        return []

    # Get schema config and relation mappings for the given macro class
    config_schema = app.state.schema
    macro_config = config_schema.get("entities", {}).get(macro_class, {})
    allowed_authorities = config_schema.get("allowed_external_authority_pids", [])
    
    enriched_schema = getattr(app.state, "enriched_schema", {})
    enriched_relations = enriched_schema.get("entities", {}).get(macro_class, {}).get("relations", [])
    
    
    own_pids = set(macro_config.get("relations", []))
    foreign_pids = set()
    for cls_name, cls_cfg in config_schema.get("entities", {}).items():
        if cls_name != macro_class:
            foreign_pids |= set(cls_cfg.get("relations", []))
    foreign_pids -= own_pids
    
    # Map cleaned relation labels to PIDs for quick lookup during relation score calculation
    label_to_pid_map = {}
    for prop in enriched_relations:
        pid = prop.get("pid")
        raw_name = prop.get("labels", {}).get("en") or pid
        if pid and raw_name:
            clean_label = (
                str(raw_name).lower()
                .replace(" ", "_").replace("-", "_").replace("/", "_").replace("'", "")
            )
            label_to_pid_map[clean_label] = pid

    clean_mention = mention.lower().strip()

    # Extract relation keys to consider for relation score calculation, excluding non-relation keys
    rel_keys = []
    if isinstance(active_gliner_relations, dict):
        rel_keys = [
            k for k, v in active_gliner_relations.items()
            if k not in ["name", "text", "confidence", "reconciliation", "rejected_candidates"]
        ]
    elif isinstance(active_gliner_relations, list):
        rel_keys = active_gliner_relations
    
    # candidates evaluation and scoring
    all_evaluated_candidates = []

    for index, c in enumerate(normalized_candidates):
        
        qid = c.get("qid") or c.get("id") or f"UNKNOWN_QID_{index}"
        label = (
            c.get("labels", {}).get(app.state.language)
            or c.get("labels", {}).get("en")
            or c.get("label", "")
        )
        
        # ----------------------------------------------------------------------
        # A. TEXT MATCHING SCORE (Max: 0.30)
        # ----------------------------------------------------------------------
        main_label_clean = str(label).lower().strip()
        
        aliases_to_check = []
        for lang in [app.state.language, 'en']:
            for alias in c.get("aliases", {}).get(lang, []):
                aliases_to_check.append(str(alias).lower().strip())
        
        # Perfect match with label
        if clean_mention == main_label_clean:
            text_score = 0.30
        
        # Perfect match with one alias
        elif clean_mention in aliases_to_check:
            if abs(len(clean_mention) - len(main_label_clean)) <= 3:
                text_score = 0.23  
            else:
                text_score = 0.14
        
        else:
            text_score = 0.00
            # Partial match
            all_names = [main_label_clean] + aliases_to_check
            best_ratio = 0.0
            for name in all_names:
                if name:
                    ratio = SequenceMatcher(None, clean_mention, name).ratio()
                    if ratio > best_ratio:
                        best_ratio = ratio

            if best_ratio >= 0.78:
                text_score = round(0.24 * best_ratio, 3)
            elif len(clean_mention) >= 5:
                for name in all_names:
                    if clean_mention in name or name in clean_mention:
                        text_score = 0.10
                        break

        # ----------------------------------------------------------------------
        # B. POPULARITY SCORE (Max: 0.08)
        # ----------------------------------------------------------------------
        sitelinks_raw = c.get("sitelinks", {})
        sitelinks_count = (
            sitelinks_raw.get("count", len(sitelinks_raw))
            if isinstance(sitelinks_raw, dict)
            else (int(sitelinks_raw) if str(sitelinks_raw).isdigit() else 0)
        )
        
        if sitelinks_count == 0:
            popularity_score = 0.0
        else:
            popularity_score = round(min(0.08, math.log10(sitelinks_count + 1) * 0.047), 3)
            
        # ----------------------------------------------------------------------
        # C. ONTOLOGY TYPE MATCH (Max: 0.25)
        # ----------------------------------------------------------------------
        expected_qids = macro_config.get("qids", [])
        instance_of_values = [str(q).strip() for q in c.get("P31", []) + c.get("P279", []) if q]
        has_ontology_match = any(q in expected_qids for q in instance_of_values)
        
        own_hits = sum(1 for pid in own_pids if c.get(pid))
        foreign_hits = sum(1 for pid in foreign_pids if c.get(pid))
        
        is_violation = False
        ontology_score = 0.00
        
        if macro_class == "concept":
            if (
                c.get("P625")   # geographical coordinates
                or c.get("P1282")   # Open StreetMap tag
                or "Q5" in instance_of_values   # istance of human
            ):
                is_violation = True
                
        elif macro_class == "person":
            if c.get("P625"):   # geographical coordinates
                is_violation = True

        if foreign_hits >= 2 and own_hits == 0:
            is_violation = True
            
        # Ontology score assignment based on violation status, ontology match, macro class specific rules, and presence of own relation hits
        if is_violation:
            ontology_score = -0.40 
            
        elif has_ontology_match:
            ontology_score = 0.25
            
        else:
            if macro_class == "concept":
                if "Q28640" in instance_of_values:  # Job
                    ontology_score = 0.23
                else:
                    ontology_score = 0.05
            elif macro_class == "person":
                if "Q5" in instance_of_values or c.get("P1080") or c.get("P1441"): # instance of human or has role or position held
                    ontology_score = 0.10
            elif macro_class == "place":
                if c.get("P625"):
                    ontology_score = 0.10
            
            if ontology_score < 0.10 and own_hits >= 2:
                ontology_score = 0.10

        # ----------------------------------------------------------------------
        # D. AUTHORITY CONTROL (Max: 0.20)
        # ----------------------------------------------------------------------
        found_authorities = 0
        for auth_pid in allowed_authorities:
            if c.get(auth_pid):
                found_authorities += 1
        
        if found_authorities == 0:
            authority_score = 0.0
        elif found_authorities >= 3:
            authority_score = 0.20
        else:
            authority_score = round(found_authorities * 0.07, 2)

        # ----------------------------------------------------------------------
        # E. RELATION SCORE (Max: 0.10)
        # ----------------------------------------------------------------------
        relation_score = 0.10 if coherent_qids and qid in coherent_qids else 0.00
        
        
        # ----------------------------------------------------------------------
        # F. RANK BONUS (Max: 0.07)
        # ----------------------------------------------------------------------
        rank_bonus = 0.07 if index == 0 else 0.00
        
        # ----------------------------------------------------------------------
        # FINAL SCORE
        # ----------------------------------------------------------------------
        total_score = round(
            text_score + popularity_score + ontology_score
            + authority_score + relation_score + rank_bonus,
            3
        )
        total_score = min(1.00, total_score)
        
        all_evaluated_candidates.append({
            **c,  
            "reconciliation_meta": {
                "wikidata_id": qid,
                "score": total_score,
                "breakdown": {
                    "text_score": text_score,
                    "popularity_score": popularity_score,
                    "ontology_score": ontology_score,
                    "authority_score": authority_score,
                    "relation_score": relation_score,
                    "wikidata_rank_bonus": rank_bonus
                }
            }
        })

    all_evaluated_candidates.sort(key=lambda x: x['reconciliation_meta']["score"], reverse=True)
    return all_evaluated_candidates