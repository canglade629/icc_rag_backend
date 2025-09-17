# Databricks Configuration for ICC Judgment Processing
"""
Unified configuration for ICC Judgment processing on Databricks.
This file contains all the settings needed for the three main notebooks.
"""

# ======================
# DATABRICKS ENDPOINTS
# ======================

# Vector Search Configuration
VECTOR_SEARCH_ENDPOINT = "jgmt"
VECTOR_SEARCH_INDEX = "icc.jugement.main_text_summarized"

# Model Endpoints
BGE_MODEL_ENDPOINT = "databricks-bge-large-en"
LLAMA_MODEL_ENDPOINT = "databricks-meta-llama-3-3-70b-instruct"

# ======================
# DOCUMENT METADATA
# ======================

DOCUMENT_INFO = {
    "case_name": "The Prosecutor v. Patrice-Edouard Ngaïssona and Alfred Yekatom",
    "case_number": "ICC-01/14-01/18",
    "court": "International Criminal Court",
    "chamber": "Trial Chamber IX",
    "date": "24 July 2025",
    "document_id": "ICC-01/14-01/18-2784-Red"
}

# ======================
# CHUNKING PARAMETERS
# ======================

CHUNKING_CONFIG = {
    # Basic chunking settings
    "min_paragraph_length": 50,
    "max_tokens_per_chunk": 1000,
    "large_paragraph_strategy": "split",  # "split" or "truncate"
    
    # Conservative footnote detection
    "conservative_footnote_threshold": 0.9,
    "preserve_paragraph_boundaries": True,
    
    # Text cleaning patterns
    "header_patterns": [
        r"ICC-01/14-01/18-2784-Red \d{2}-\d{2}-\d{4} \d+/\d+ T",
        r"No\. ICC-01/14-01/18 \d+/\d+ \d{2} July \d{4}"
    ],
    
    # Footnote processing
    "footnote_enabled": True,
    "footnote_conservative_mode": True,
    "footnote_min_confidence": 0.9
}

# ======================
# VECTOR SEARCH SETTINGS
# ======================

# Section weights based on data analysis (from optimized_databricks_vector_search.py)
SECTION_WEIGHTS = {
    "VERDICT": 1.5,                    # 87.5% legal concept density - highest priority
    "SENTENCE": 1.4,                   # 40.7% legal concept density - high priority  
    "FINDINGS_OF_FACT": 1.3,           # Critical factual content
    "OVERVIEW": 1.1,                   # 45.5% legal concept density - good context
    "EVIDENTIARY_CONSIDERATIONS": 1.0,  # 7.0% density but 88% of content - baseline
    "HEADER": 0.5                      # Minimal relevance
}

# Legal terminology for query enhancement
LEGAL_EXPANSIONS = {
    # Core ICC crimes (high priority)
    "war crimes": ["war crime", "violations of the laws of war", "grave breaches"],
    "crimes against humanity": ["crime against humanity", "systematic attack", "widespread attack"],
    "genocide": ["genocidal acts", "intent to destroy", "ethnic cleansing"],
    
    # Specific acts (based on data analysis)
    "murder": ["kill", "killing", "assassination", "homicide", "unlawful killing"],
    "persecution": ["persecute", "persecuted", "discriminatory acts", "targeting"],
    "torture": ["ill-treatment", "cruel treatment", "inhuman treatment"],
    
    # ICC-specific structure  
    "evidentiary": ["evidence", "proof", "testimony", "witness"],
    "sentence": ["sentencing", "punishment", "penalty", "years"],
    "verdict": ["finding", "conclusion", "determination", "guilty", "not guilty"],
    
    # Person-specific (based on 723 Yekatom, 646 Ngaïssona mentions)
    "anti-balaka": ["anti balaka", "anti-balaka forces", "militia"],
    "elements": ["subordinates", "fighters", "combatants", "forces", "troops"],
    "command": ["instruct", "order", "direct", "tell", "responsibility"]
}

# Key entities found in data
KEY_ENTITIES = {
    "persons": ["Yekatom", "Ngaïssona", "Alkanto"],
    "locations": ["Bangui", "CAR", "Central African Republic"],
    "concepts": ["Muslim", "Christian", "Anti-Balaka", "war crime", "persecution"]
}

# ======================
# RAG SYSTEM SETTINGS
# ======================

RAG_CONFIG = {
    # LLM settings
    "temperature": 0.1,
    "max_tokens": 2048,
    
    # Retrieval settings
    "default_num_results": 8,
    "max_contexts": 15,
    
    # Conversation settings
    "conversation_memory_window": 5,
    "enable_conversation_memory": True,
    
    # Response settings
    "include_sources": True,
    "max_source_preview": 150
}

# ======================
# DATABRICKS PATHS
# ======================

DATABRICKS_PATHS = {
    # Volume paths (using Unity Catalog volumes instead of DBFS)
    "pdf_input": "/Volumes/icc/jugement/files/",
    "chunks_output": "/Volumes/icc/jugement/files/processed/",
    "temp_files": "/Volumes/icc/jugement/files/temp/",
    
    # Table names (using icc.jugement schema)
    "chunks_table": "icc.jugement.chunks",
    "rag_table": "icc.jugement.chunks_for_rag",
    "summary_table": "icc.jugement.chunks_summary",
    "parsed_document_table": "icc.jugement.parsed_document",
    "parsed_for_chunking": "icc.jugement.parsed_for_chunking",
    
    # Model names
    "vector_search_model": "icc.jugement.vector_search_model",
    "rag_model": "icc.jugement.rag_model",
    
    # Endpoint names
    "vector_search_endpoint_name": "icc-vector-search-endpoint",
    "rag_endpoint_name": "icc-rag-production-endpoint"
}

# ======================
# QUALITY CONTROL
# ======================

QUALITY_CONFIG = {
    "min_chunk_quality_score": 0.8,
    "validate_paragraph_numbers": True,
    "detect_text_corruption": True,
    "min_chunk_length": 20,
    "max_empty_chunks_ratio": 0.05
}

# ======================
# LOGGING AND MONITORING
# ======================

LOGGING_CONFIG = {
    "level": "INFO",
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    "enable_mlflow_tracking": True,
    "enable_performance_metrics": True
}

# ======================
# DEPLOYMENT SETTINGS
# ======================

DEPLOYMENT_CONFIG = {
    # Serving endpoint settings
    "workload_size": "Small",
    "scale_to_zero_enabled": False,
    "workload_type": "CPU",
    
    # Auto-scaling
    "min_capacity": 1,
    "max_capacity": 5,
    
    # Health checks
    "health_check_timeout": 60,
    "readiness_timeout": 300
}

# ======================
# PDF SOURCE CONFIGURATION
# ======================

# Main PDF file location in Unity Catalog volume
PDF_SOURCE_PATH = "/Volumes/icc/jugement/files/jugement.pdf"

# ======================
# HELPER FUNCTIONS
# ======================

def get_section_weight(section_type: str) -> float:
    """Get the weight for a specific section type."""
    return SECTION_WEIGHTS.get(section_type, 1.0)

def get_legal_expansions(term: str) -> list:
    """Get legal term expansions for query enhancement."""
    return LEGAL_EXPANSIONS.get(term.lower(), [])

def get_databricks_path(path_type: str) -> str:
    """Get a specific Databricks path."""
    return DATABRICKS_PATHS.get(path_type, "")

def get_model_endpoint(model_type: str) -> str:
    """Get the endpoint for a specific model type."""
    if model_type.lower() == "bge":
        return BGE_MODEL_ENDPOINT
    elif model_type.lower() == "llama":
        return LLAMA_MODEL_ENDPOINT
    elif model_type.lower() == "vector_search":
        return VECTOR_SEARCH_ENDPOINT
    else:
        raise ValueError(f"Unknown model type: {model_type}")

# Validation function
def validate_config():
    """Validate that all required configuration values are set."""
    required_endpoints = [VECTOR_SEARCH_ENDPOINT, VECTOR_SEARCH_INDEX, BGE_MODEL_ENDPOINT, LLAMA_MODEL_ENDPOINT]
    missing = [endpoint for endpoint in required_endpoints if not endpoint]
    
    if missing:
        raise ValueError(f"Missing required configuration values: {missing}")
    
    print("✅ Configuration validation passed")
    return True

# Print configuration summary
def print_config_summary():
    """Print a summary of the current configuration."""
    print("🔧 DATABRICKS CONFIGURATION SUMMARY")
    print("=" * 50)
    print(f"Vector Search Endpoint: {VECTOR_SEARCH_ENDPOINT}")
    print(f"Vector Search Index: {VECTOR_SEARCH_INDEX}")
    print(f"BGE Model: {BGE_MODEL_ENDPOINT}")
    print(f"Llama Model: {LLAMA_MODEL_ENDPOINT}")
    print(f"Case: {DOCUMENT_INFO['case_name']}")
    print(f"Document: {DOCUMENT_INFO['case_number']}")
    print("=" * 50)

if __name__ == "__main__":
    validate_config()
    print_config_summary()
