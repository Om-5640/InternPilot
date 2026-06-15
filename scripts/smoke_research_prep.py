"""One-shot smoke test: research prep path against the live LLM.

Run:  uv run python scripts/smoke_research_prep.py
"""
from __future__ import annotations

import asyncio
import json

from app.llm.extract import extract_structured
from app.schemas.interview_prep import PrepExtract

PROFILE_TEXT = """\
Skills: Python, PyTorch, Hugging Face Transformers, scikit-learn, SQL
Research interests: natural language processing, low-resource machine translation, multilingual models
Project 'LowResourceMT': Fine-tuned mBART-50 for Hindi→Marathi translation with back-translation \
augmentation | Tech: Python, PyTorch, Hugging Face
Project 'SentimentBERT': Adapter-tuned BERT for aspect-level sentiment on product reviews | \
Tech: Python, Transformers, HuggingFace
Experience: NLP Research Intern @ IIIT Hyderabad — implemented subword tokenisation experiments \
for low-resource Dravidian languages"""

INSTRUCTIONS = """\
Generate interview prep for a RESEARCH POSITION at MIT NLP Group (Prof. Regina Barzilay's lab), \
role: Research Intern.
Research area / topic: low-resource NLP, multilingual machine translation

STRUCTURE — include these categories (no coding, no GD):
  research_fit (2–3 questions): Why this lab/professor; how the student's interests align; \
evidence of engagement with the research area.
  domain_depth (3–4 questions): Core technical concepts, seminal papers, open problems \
in low-resource NLP and multilingual MT.
  methods (2–3 questions): Techniques, tools, experimental or theoretical approaches \
relevant to the area (mBART, back-translation, adapter tuning, etc.).
  project (2–3 questions): The student's REAL projects/papers as evidence of research \
aptitude. ONLY reference these real projects: 'LowResourceMT', 'SentimentBERT'.
  behavioral (1–2 questions): Motivation, independence, long-term research goals. STAR format.

SKILL WHITELIST (only reference skills/tech from this list): \
Hugging Face, Hugging Face Transformers, PyTorch, Python, SQL, Transformers, scikit-learn

OUTPUT RULES:
  - Total 10–14 questions.
  - Each question: q, type ('technical'/'behavioral'), category, difficulty, \
answer_guidance, ideal_answer_outline.
  - weak_spots: 3–5 real gaps between student background and research area requirements.
  - reverse_questions: exactly 2 smart questions the student can ask the professor/PI.
  - NEVER invent skills, projects, or research interests not in the profile."""


async def main() -> None:
    print("Calling LLM (research prep path)...\n")
    result: PrepExtract = await extract_structured(
        text=PROFILE_TEXT,
        schema=PrepExtract,
        instructions=INSTRUCTIONS,
    )

    print(f"=== {len(result.questions)} questions ===\n")
    by_cat: dict[str, list] = {}
    for q in result.questions:
        by_cat.setdefault(q.category or "other", []).append(q)

    for cat, qs in by_cat.items():
        print(f"--- {cat.upper()} ---")
        for q in qs:
            print(f"  [{q.difficulty}] {q.q}")
            if q.answer_guidance:
                print(f"    guidance: {q.answer_guidance}")
        print()

    print("=== WEAK SPOTS ===")
    for ws in result.weak_spots:
        print(f"  • {ws}")

    print("\n=== REVERSE QUESTIONS ===")
    for rq in result.reverse_questions:
        print(f"  • {rq}")

    print("\n--- raw JSON (truncated) ---")
    raw = json.dumps(result.model_dump(), indent=2)
    print(raw[:3000] + (" …" if len(raw) > 3000 else ""))


if __name__ == "__main__":
    asyncio.run(main())
