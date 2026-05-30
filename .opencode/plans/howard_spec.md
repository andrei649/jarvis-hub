# SPECIFICATION: Howard — Digital Twin Agent

## 1. Overview

Howard is Andrei's digital twin — an archive agent that ingests 15+ years of Facebook Messenger and WhatsApp conversations, extracts a stylometric voice profile, and can respond "as Andrei" via RAG + fine-tuned LLM.

**Archetype:** Digital Twin / Archive
**Tier:** Foundation (local-only, like Frigga)
**LLM Policy:** `local` — zero cloud, zero internet
**Primary Model:** `howard-lora-qwen-14b` (fine-tuned via QLoRA, served via Ollama)
**Fallback Model:** `google/gemma-4-26b-a4b` (existing LM Studio, with RAG few-shot)

## 2. Agent Registration

| File | Change |
|---|---|
| `agents/howard/SOUL.md` | New — full agent soul |
| `agents/_system/agents.yaml` | Howard moved from bench → active, `status: active`, `tier: foundation`, `llm_policy: local` |
| `agents/core/router.py` | Added `howard` to `ROUTING_TABLE` + keywords: `archive`, `what would i`, `remember`, `digital twin`, `voice`, etc. |
| `agents/core/llm/hybrid_router.py` | Added `howard` to `LOCAL_ONLY_AGENTS` |

## 3. Data Ingestion Pipeline

**Location:** `agents/core/ingestion/`

| File | Purpose |
|---|---|
| `pipeline.py` | Orchestrates full pipeline: parse → normalize → analyze → store |
| `parser_facebook.py` | Parses Facebook DYI JSON (`message_1.json`) |
| `parser_whatsapp.py` | Parses WhatsApp `.txt` exports (RO + EN date formats) |
| `normalizer.py` | `NormalizedMessage` dataclass — common format |
| `stylometry.py` | `VoiceProfile` + `StylometryAnalyzer` — extracts word choice, code-switching RO/EN, emoji patterns, sentence rhythm, formality score |
| `knowledge.py` | `KnowledgeExtractor` — entities, relationships, decision patterns, topic clusters |

**Output:**
- `memory_logs/archive/archive.db` — SQLite with all messages indexed
- `memory_logs/archive/messages.jsonl` — JSONL for training data export
- `memory_logs/archive/voice_profile.json` — stylometric fingerprint
- `memory_logs/archive/knowledge.json` — extracted entities + relationships + decisions
- `memory_logs/archive/ingestion_summary.json` — full run stats

### 3.1 Facebook Parser

Expects: `data/facebook/messages/inbox/<conversation>/message_1.json`

Handles:
- Multiple `message_N.json` files per conversation
- System messages filtered (type != "Generic")
- Empty/whitespace-only messages filtered
- Name variant matching (full name, first name, last name)

### 3.2 WhatsApp Parser

Expects: `data/whatsapp/<conversation_name>.txt`

Handles:
- RO format: `[dd.mm.yyyy, hh:mm:ss] Sender: message`
- EN format: `[m/d/yy, h:mm:ss AM/PM] Sender: message`
- System messages filtered ("joined using this group", "changed the group", etc.)

### 3.3 Stylometry

Extracts per-batch:

| Metric | Description |
|---|---|
| `top_words` | Top 100 most frequent words (Andrei only) |
| `top_bigrams` | Top 50 word pairs |
| `signature_phrases` | Andrei's characteristic words and phrases |
| `ro_ratio` / `en_ratio` | Language distribution in his messages |
| `code_switch_rate` | How often he switches RO↔EN mid-message |
| `emoji_usage` | Top 30 emojis by frequency |
| `avg_message_length` | Mean characters per message |
| `formality_score` | 0.0 (casual) – 1.0 (formal) based on known indicators |

### 3.4 Knowledge Extraction

- **Entities:** Topics (bmw, cosmina, tech, fitness) with mention count, first/last seen, context snippets
- **Relationships:** Person → relation type (partner, son, close_friend, colleague, etc.) with confidence score
- **Decisions:** Messages containing decision triggers ("am ales", "i chose", "prefer") with full context

## 4. RAG Architecture

### 4.1 Vector Store

Initial: `VectorStore` (numpy, 768-dim) — existing in `agents/core/memory/store.py`
Future: Qdrant on Pi 5 (planned H3.1)

### 4.2 Search Flow

```
How are you?

→ Embed query using local embedding model
→ Search VectorStore top-5 Andrei messages on similar topic
→ Return message text + conversation context + sender info
→ Inject as few-shot into Howard's system prompt
→ Howard generates response in Andrei's voice
```

### 4.3 New Methods Added

- `VectorStore.search_by_sender(sender, k)` — filter by message author
- `VectorStore.search_by_text_subset(query, sender, k)` — search filtered by author

## 5. Fine-Tuning Pipeline

### 5.1 Data Preparation

Convert `memory_logs/archive/messages.jsonl` → ShareGPT format:

```json
[
  {
    "conversations": [
      {"from": "user", "value": "Salut, ce faci?"},
      {"from": "assistant", "value": "Salut, bine, tu ce mai faci?"}
    ]
  }
]
```

Andrei's messages → `assistant`, others → `user`.

### 5.2 Training

| Parameter | Value |
|---|---|
| Base model | Qwen 2.5 14B-Instruct (GGUF Q4_K_M) |
| Method | QLoRA (Unsloth) |
| LoRA rank | 16–32 |
| Target modules | q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj |
| Epochs | 3–5 (monitor eval loss) |
| Learning rate | 2e-4 |
| Batch size | 4 (gradient accumulation 2) |
| Max seq length | 2048 |

### 5.3 Deployment

1. Export LoRA adapter
2. Merge into base model GGUF
3. Create Ollama Modelfile: `ollama create howard-lora -f Modelfile`
4. Register in Ollama: `MODEL=howard-lora-qwen-14b`

### 5.4 Serving

- **Inference via Ollama** (port 11434, CPU + optional GPU offload)
- **Fallback** to Gemma 4 (LM Studio) with RAG few-shot when Ollama unavailable

## 6. Ollama Backend

### 6.1 New File: `agents/core/llm/ollama_howard.py`

A lightweight backend that connects to Ollama for Howard's fine-tuned model:

```python
class OllamaHowardBackend(LLMBackend):
    async def generate(self, model, prompt, system):
        response = ollama.chat(
            model="howard-lora-qwen-14b",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return response["message"]["content"]
```

Integrated into `HybridRouter` as a second local backend — used specifically when agent_id == "howard".

### 6.2 Architecture

```
┌─────────────────────────────────────────┐
│              LM Studio                   │
│  Model: Gemma 4 26B MoE (16.7GB VRAM)  │
│  Used by: all agents except howard      │
└────────────────┬────────────────────────┘
                 │ port 1234
                 ▼
┌─────────────────────────────────────────┐
│              Ollama                      │
│  Model: howard-lora-qwen-14b (~8GB)    │
│  Used by: howard only                   │
└────────────────┬────────────────────────┘
                 │ port 11434 (CPU + partial GPU)
                 ▼
┌─────────────────────────────────────────┐
│              Jarvis Orchestrator        │
│  Routes howard queries → Ollama        │
│  All other agents → LM Studio          │
└─────────────────────────────────────────┘
```

## 7. Query Flow

### 7.1 Direct Query ("Howard, ce știi despre X?")

1. IntentRouter → target: `["howard"]`
2. Orchestrator → Agent("howard").process()
3. Agent._load_soul() → SOUL.md system prompt
4. HybridRouter → select_backend("howard", prompt) → Ollama
5. Before generation: RAG lookup in VectorStore for top-5 matching past messages
6. Few-shot injected into prompt
7. Ollama generates response in Andrei's voice
8. Response returned to user

### 7.2 Consulted by Jarvis ("Jarvis, ce aș face eu aici?")

1. IntentRouter → keywords match "what would i" → target: `["howard"]`
2. Actually: routed through Jarvis → Jarvis calls Howard
3. Howard returns analysis + suggested response in Andrei's voice
4. Jarvis synthesizes into final reply

## 8. Files Created / Modified

| Status | File | Action |
|---|---|---|
| ✅ | `agents/howard/SOUL.md` | CREATE |
| ✅ | `agents/core/ingestion/__init__.py` | CREATE |
| ✅ | `agents/core/ingestion/pipeline.py` | CREATE |
| ✅ | `agents/core/ingestion/normalizer.py` | CREATE |
| ✅ | `agents/core/ingestion/parser_facebook.py` | CREATE |
| ✅ | `agents/core/ingestion/parser_whatsapp.py` | CREATE |
| ✅ | `agents/core/ingestion/stylometry.py` | CREATE |
| ✅ | `agents/core/ingestion/knowledge.py` | CREATE |
| ✅ | `agents/_system/agents.yaml` | MODIFY |
| ✅ | `agents/core/router.py` | MODIFY |
| ✅ | `agents/core/llm/hybrid_router.py` | MODIFY |
| ✅ | `agents/core/memory/store.py` | MODIFY |
| ⬜ | `agents/core/llm/ollama_howard.py` | CREATE |
| ⬜ | `agents/core/ingestion/embedder.py` | CREATE |
| ⬜ | `.opencode/plans/howard_spec.md` | CREATE |

## 9. Future Upgrades

- **Qdrant Vector DB**: Migrate from numpy VectorStore to Qdrant on Pi 5 for persistent, scalable storage
- **Neo4j Knowledge Graph**: Migrate relationship extraction to Neo4j for graph queries
- **Continuous Ingestion**: Watch `data/` for new exports and auto-ingest
- **Voice Channel**: Allow Howard to speak via TTS (in Andrei's voice via XTTS-cloned-Andrei)
- **Periodic Re-tuning**: Monthly re-fine-tune with new conversation data
