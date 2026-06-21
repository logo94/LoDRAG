# Default
import json
from pathlib import Path
import re
import html

# FastAPI
from fastapi import UploadFile
from typing import Union

# Utility functions for the project

# Funzione Helper ottimizzata per estrarre il testo da un UploadFile
async def extract_text_from_txt(file: UploadFile) -> str:
    try:
        content_bytes = await file.read()
        
        try:
            text = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = content_bytes.decode("latin-1")
        
        return text.strip()
        
    finally:
        await file.close()
        

async def split_text_in_paragraphs(content: str):
    
    content = html.unescape(content)

    start_pattern = r"\*\*\* START OF .*? \*\*\*"
    end_pattern = r"\*\*\* END OF .*? \*\*\*"
    start_match = re.search(start_pattern, content, re.IGNORECASE)
    end_match = re.search(end_pattern, content, re.IGNORECASE)
    start_idx = start_match.end() if start_match else 0
    end_idx = end_match.start() if end_match else len(content)
    content = content[start_idx:end_idx]

    content = content.replace('_', '')
    content = re.sub(r'\[\d+\]', '', content)

    raw_blocks = re.split(r'\n\s*\n', content)
    
    clean_paragraphs = []
    for block in raw_blocks:
        clean_p = " ".join(block.split()).strip()
        
        if len(clean_p) > 40 and len(clean_p.split()) >= 6: 
            clean_paragraphs.append(clean_p)

    if not clean_paragraphs and content.strip():
        backup_p = " ".join(content.split()).strip()
        if len(backup_p) > 40:
            clean_paragraphs.append(backup_p)

    return clean_paragraphs


# Function to read JSON files
def read_json_file(filepath):
    
    path = Path(filepath).resolve()
    
    path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError as e:
        print(f"Errore: JSON malformato in {path}: {str(e)}")
        return None
    except Exception as e:
        print(f"Errore imprevisto leggendo {path}: {str(e)}")
        return None

# Function to write JSON files
def write_json_file(filepath: str, data: Union[dict, list]):
    
    path = Path(filepath).resolve()

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w+", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)