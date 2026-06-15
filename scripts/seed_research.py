"""Seed research opportunities (Module 12).

Usage:
    uv run python scripts/seed_research.py            # seed if table is empty
    uv run python scripts/seed_research.py --reset    # delete all + re-seed

Inserts 20 representative research opportunities spanning NLP/ML, systems,
bioinformatics, robotics, and HCI across IITs, IISc, and global universities.
Embeddings are computed locally (all-MiniLM-L6-v2) — no API cost.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings  # noqa: E402
from app.models.research_opportunity import ResearchOpportunity  # noqa: E402
from app.services.research_service import create_opportunity  # noqa: E402

# ---------------------------------------------------------------------------
# Opportunity definitions
# ---------------------------------------------------------------------------

_OPPORTUNITIES: list[dict] = [
    # ---- IIT Delhi ----
    {
        "professor_name": "Prof. Tanvir Ahmed",
        "institution": "IIT Delhi",
        "lab_name": "Language Technology Lab",
        "research_area": "Natural Language Processing",
        "description": (
            "We are working on low-resource NLP for Indic languages, including "
            "cross-lingual transfer learning and multilingual pre-training. "
            "Projects include building named entity recognition systems for Hindi, "
            "Bengali, and Tamil using transformer models fine-tuned with limited labelled data."
        ),
        "desired_skills": ["Python", "PyTorch", "Transformers", "NLP", "HuggingFace"],
        "program": "Summer Research Internship",
        "region": "India",
        "contact_email": "tanvir@cse.iitd.ac.in",
        "url": None,
        "posted_at": "2026-04-01",
    },
    {
        "professor_name": "Prof. Ritu Gupta",
        "institution": "IIT Delhi",
        "lab_name": "Systems and Networks Lab",
        "research_area": "Distributed Systems",
        "description": (
            "Research on fault-tolerant consensus protocols and geo-distributed "
            "databases. Current focus: extending Raft with learner nodes for "
            "multi-region deployments and measuring tail latency under network partitions."
        ),
        "desired_skills": ["Go", "C++", "Distributed Systems", "gRPC", "Linux"],
        "program": "Research Intern (6 months)",
        "region": "India",
        "contact_email": "ritu@cse.iitd.ac.in",
        "url": None,
        "posted_at": "2026-03-15",
    },
    # ---- IIT Bombay ----
    {
        "professor_name": "Prof. Shweta Jain",
        "institution": "IIT Bombay",
        "lab_name": "Machine Learning Lab",
        "research_area": "Federated Learning and Privacy",
        "description": (
            "Investigating privacy-preserving machine learning techniques including "
            "differential privacy, secure aggregation, and federated fine-tuning of "
            "large language models across heterogeneous client devices."
        ),
        "desired_skills": ["Python", "PyTorch", "Federated Learning", "Differential Privacy", "Machine Learning"],
        "program": "Summer Intern",
        "region": "India",
        "contact_email": "shweta@cse.iitb.ac.in",
        "url": None,
        "posted_at": "2026-04-10",
    },
    {
        "professor_name": "Prof. Arjun Nair",
        "institution": "IIT Bombay",
        "lab_name": "Computer Vision and Graphics Group",
        "research_area": "3D Computer Vision",
        "description": (
            "We develop neural rendering and 3D reconstruction methods, including "
            "NeRF variants for indoor scenes and real-time Gaussian splatting pipelines. "
            "Looking for interns to work on depth completion and surface normal estimation."
        ),
        "desired_skills": ["Python", "PyTorch", "OpenCV", "CUDA", "3D Vision"],
        "program": "Research Intern",
        "region": "India",
        "contact_email": "arjun@cse.iitb.ac.in",
        "url": None,
        "posted_at": "2026-03-20",
    },
    # ---- IIT Madras ----
    {
        "professor_name": "Prof. Vijayalakshmi Priya",
        "institution": "IIT Madras",
        "lab_name": "Bioinformatics and Computational Biology Lab",
        "research_area": "Computational Genomics",
        "description": (
            "Our group applies deep learning to genome-wide association studies, "
            "protein structure prediction, and single-cell RNA sequencing analysis. "
            "Intern will work on graph neural networks for gene regulatory network inference."
        ),
        "desired_skills": ["Python", "PyTorch", "Bioinformatics", "pandas", "scikit-learn"],
        "program": "SURGE Equivalent — Summer",
        "region": "India",
        "contact_email": "vijaya@cse.iitm.ac.in",
        "url": None,
        "posted_at": "2026-04-05",
    },
    {
        "professor_name": "Prof. Karthik Subramanian",
        "institution": "IIT Madras",
        "lab_name": "Robotics Lab",
        "research_area": "Robot Learning and Manipulation",
        "description": (
            "Research on learning-based robot manipulation including imitation learning "
            "from human demonstrations and sim-to-real transfer. Intern will implement "
            "diffusion-based policy learning for pick-and-place tasks on a 7-DOF arm."
        ),
        "desired_skills": ["Python", "ROS", "PyTorch", "Robotics", "Reinforcement Learning"],
        "program": "Summer Research Intern",
        "region": "India",
        "contact_email": "karthik@ee.iitm.ac.in",
        "url": None,
        "posted_at": "2026-03-25",
    },
    # ---- IISc Bangalore ----
    {
        "professor_name": "Prof. Meera Rao",
        "institution": "IISc Bangalore",
        "lab_name": "Speech and Audio Research Lab",
        "research_area": "Speech Processing and Automatic Speech Recognition",
        "description": (
            "We build ASR systems for low-resource Indian languages using end-to-end "
            "models (Whisper fine-tuning, CTC, attention-based encoder-decoder). "
            "Ongoing project: building a multilingual speech corpus for 11 Indian languages "
            "and evaluating zero-shot cross-lingual transfer."
        ),
        "desired_skills": ["Python", "PyTorch", "Speech Processing", "HuggingFace", "librosa"],
        "program": "IISc Summer Fellowship",
        "region": "India",
        "contact_email": "meera@dese.iisc.ac.in",
        "url": None,
        "posted_at": "2026-04-08",
    },
    {
        "professor_name": "Prof. Sundar Krishnamurthy",
        "institution": "IISc Bangalore",
        "lab_name": "Theory of Computation Group",
        "research_area": "Algorithms and Complexity",
        "description": (
            "Research on approximation algorithms for NP-hard combinatorial optimization "
            "problems and parameterized complexity. Current projects include algorithms for "
            "cluster editing, feedback arc set, and fair clustering."
        ),
        "desired_skills": ["C++", "Algorithms", "Competitive Programming", "Graph Theory", "Mathematics"],
        "program": "Research Intern",
        "region": "India",
        "contact_email": "sundar@csa.iisc.ac.in",
        "url": None,
        "posted_at": "2026-03-28",
    },
    # ---- IIT Kharagpur ----
    {
        "professor_name": "Prof. Dipankar Roy",
        "institution": "IIT Kharagpur",
        "lab_name": "Data Analytics and Intelligence Lab",
        "research_area": "Knowledge Graphs and Reasoning",
        "description": (
            "We build large-scale knowledge graphs for academic and enterprise domains "
            "and develop neural-symbolic reasoning systems. Interns will work on "
            "entity alignment across heterogeneous knowledge graphs using GNNs."
        ),
        "desired_skills": ["Python", "PyTorch Geometric", "SPARQL", "Knowledge Graphs", "NLP"],
        "program": "Summer Research Intern",
        "region": "India",
        "contact_email": "dipankar@cse.iitkgp.ac.in",
        "url": None,
        "posted_at": "2026-04-02",
    },
    {
        "professor_name": "Prof. Ananya Mukherjee",
        "institution": "IIT Kharagpur",
        "lab_name": "HCI and Accessibility Lab",
        "research_area": "Human-Computer Interaction and Accessibility",
        "description": (
            "We design and evaluate assistive technologies for users with visual impairments "
            "and motor disabilities. Current projects: screen-reader improvements using "
            "multimodal LLMs and gaze-based alternative input for mobile devices."
        ),
        "desired_skills": ["Python", "User Research", "Prototyping", "React", "Accessibility"],
        "program": "Summer Intern",
        "region": "India",
        "contact_email": "ananya@cse.iitkgp.ac.in",
        "url": None,
        "posted_at": "2026-03-18",
    },
    # ---- IIT Kanpur ----
    {
        "professor_name": "Prof. Raghunath Sharma",
        "institution": "IIT Kanpur",
        "lab_name": "Security and Cryptography Lab",
        "research_area": "Applied Cryptography and Secure Systems",
        "description": (
            "Research on post-quantum cryptography, zero-knowledge proofs, and secure "
            "multi-party computation. Intern projects include benchmarking lattice-based "
            "key encapsulation mechanisms and implementing ZK-SNARK circuits for private ML."
        ),
        "desired_skills": ["C++", "Python", "Cryptography", "Mathematics", "Rust"],
        "program": "Research Intern",
        "region": "India",
        "contact_email": "raghunath@cse.iitk.ac.in",
        "url": None,
        "posted_at": "2026-04-12",
    },
    # ---- Global — US ----
    {
        "professor_name": "Prof. Emily Zhang",
        "institution": "MIT CSAIL",
        "lab_name": "Probabilistic Computing Group",
        "research_area": "Probabilistic Programming and Bayesian ML",
        "description": (
            "We develop probabilistic programming languages and inference engines "
            "for scientific computing. Current focus: variational inference scalable to "
            "large hierarchical models and differentiable simulators for climate science."
        ),
        "desired_skills": ["Python", "PyTorch", "Bayesian Inference", "Julia", "Statistics"],
        "program": "UROP / Visiting Research",
        "region": "USA",
        "contact_email": None,
        "url": "https://groups.csail.mit.edu/probcomp/",
        "posted_at": "2026-04-01",
    },
    {
        "professor_name": "Prof. David Hernandez",
        "institution": "Stanford University",
        "lab_name": "Human-Centered AI Lab",
        "research_area": "Explainable AI and Fairness",
        "description": (
            "Our lab studies how to make AI systems interpretable, fair, and accountable. "
            "Current projects: post-hoc explanation methods for LLMs, bias measurement in "
            "hiring algorithms, and participatory design of AI audit frameworks."
        ),
        "desired_skills": ["Python", "Machine Learning", "Fairness", "Data Analysis", "Statistics"],
        "program": "UGVR Summer Research",
        "region": "USA",
        "contact_email": None,
        "url": "https://hai.stanford.edu/",
        "posted_at": "2026-03-22",
    },
    {
        "professor_name": "Prof. Aisha Williams",
        "institution": "Carnegie Mellon University",
        "lab_name": "Robotics Institute — RPAD Lab",
        "research_area": "Planning and Decision Making under Uncertainty",
        "description": (
            "Research on POMDP solvers, safe reinforcement learning, and task-and-motion "
            "planning for household robots. Interns work on extending Monte-Carlo tree search "
            "with learned heuristics for long-horizon manipulation tasks."
        ),
        "desired_skills": ["Python", "C++", "Reinforcement Learning", "ROS", "Planning Algorithms"],
        "program": "CMU RISS",
        "region": "USA",
        "contact_email": None,
        "url": "https://riss.ri.cmu.edu/",
        "posted_at": "2026-04-15",
    },
    {
        "professor_name": "Prof. Marcus Lee",
        "institution": "UC Berkeley",
        "lab_name": "RISE Lab",
        "research_area": "Real-Time Intelligent Secure Explainable Systems",
        "description": (
            "We build systems infrastructure for the next generation of real-time AI "
            "applications. Current focus: Ray architecture improvements for heterogeneous "
            "GPU clusters, streaming data pipelines, and ML serving at sub-10ms latency."
        ),
        "desired_skills": ["Python", "C++", "Distributed Systems", "Kubernetes", "Ray"],
        "program": "SUPERB Research",
        "region": "USA",
        "contact_email": None,
        "url": "https://rise.cs.berkeley.edu/",
        "posted_at": "2026-03-30",
    },
    # ---- Global — Europe / Asia ----
    {
        "professor_name": "Prof. Sophie Müller",
        "institution": "ETH Zürich",
        "lab_name": "Computational Imaging Lab",
        "research_area": "Medical Image Analysis",
        "description": (
            "We apply deep learning to clinical imaging data including MRI, CT, and "
            "histopathology slides. Projects include self-supervised pre-training on "
            "unlabelled medical images and uncertainty quantification for radiology AI."
        ),
        "desired_skills": ["Python", "PyTorch", "Medical Imaging", "scikit-image", "MONAI"],
        "program": "ETH Excellence Scholarship Research",
        "region": "Europe",
        "contact_email": "smueller@inf.ethz.ch",
        "url": None,
        "posted_at": "2026-04-08",
    },
    {
        "professor_name": "Prof. Yuki Tanaka",
        "institution": "University of Tokyo",
        "lab_name": "Matsuo Lab",
        "research_area": "Deep Learning and World Models",
        "description": (
            "Research on learning compact world models for model-based reinforcement "
            "learning and video prediction. Intern projects include multi-step latent "
            "dynamics models with structured state spaces applied to robotic locomotion."
        ),
        "desired_skills": ["Python", "PyTorch", "Reinforcement Learning", "JAX", "Deep Learning"],
        "program": "Research Intern (remote possible)",
        "region": "Asia",
        "contact_email": "tanaka@weblab.t.u-tokyo.ac.jp",
        "url": None,
        "posted_at": "2026-04-03",
    },
    {
        "professor_name": "Prof. Lars Eriksson",
        "institution": "KTH Royal Institute of Technology",
        "lab_name": "Software Systems Lab",
        "research_area": "Programming Languages and Compilers",
        "description": (
            "Research on type systems, program verification, and compiler optimizations "
            "for safety-critical embedded systems. Interns work on implementing abstract "
            "interpretation passes in LLVM and formalizing semantics in Coq or Lean."
        ),
        "desired_skills": ["C++", "LLVM", "Rust", "Type Theory", "Compilers"],
        "program": "Summer Research Visitor",
        "region": "Europe",
        "contact_email": "larse@kth.se",
        "url": None,
        "posted_at": "2026-03-25",
    },
    # ---- TIFR / ISI / CMI ----
    {
        "professor_name": "Prof. Balasubramanian Krishnan",
        "institution": "TIFR Mumbai",
        "lab_name": "Theoretical Computer Science Group",
        "research_area": "Communication Complexity and Circuit Complexity",
        "description": (
            "We study fundamental lower bounds in computational complexity theory, "
            "including multi-party communication complexity, pseudorandomness, and "
            "the power of algebraic circuits. Strong mathematical background required."
        ),
        "desired_skills": ["Mathematics", "Algorithms", "Complexity Theory", "Probability Theory"],
        "program": "Visiting Student Research Program (VSRP)",
        "region": "India",
        "contact_email": "bala@tifr.res.in",
        "url": None,
        "posted_at": "2026-03-15",
    },
    {
        "professor_name": "Prof. Priya Subramaniam",
        "institution": "ISI Kolkata",
        "lab_name": "Machine Intelligence Unit",
        "research_area": "Statistical Learning Theory",
        "description": (
            "Research on PAC learning, online learning, and bandit algorithms with "
            "applications to online recommendation and adaptive clinical trials. "
            "Interns will work on regret bounds for contextual bandits under covariate shift."
        ),
        "desired_skills": ["Python", "Statistics", "Machine Learning", "Mathematics", "numpy"],
        "program": "Summer Research Intern",
        "region": "India",
        "contact_email": "priya@isical.ac.in",
        "url": None,
        "posted_at": "2026-04-05",
    },
]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main(reset: bool = False) -> None:
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        if reset:
            await db.execute(delete(ResearchOpportunity))
            await db.commit()
            print("Deleted existing research opportunities.")

        count_before = (
            await db.execute(select(ResearchOpportunity))
        ).scalars().all()
        if not reset and count_before:
            print(f"Table already has {len(count_before)} opportunities. Skipping. Use --reset to re-seed.")
            await engine.dispose()
            return

        print(f"Seeding {len(_OPPORTUNITIES)} research opportunities ...")
        for i, data in enumerate(_OPPORTUNITIES, 1):
            opp = await create_opportunity(
                db,
                professor_name=data["professor_name"],
                institution=data["institution"],
                lab_name=data.get("lab_name"),
                research_area=data["research_area"],
                description=data["description"],
                desired_skills=data["desired_skills"],
                program=data.get("program"),
                region=data.get("region"),
                contact_email=data.get("contact_email"),
                url=data.get("url"),
                source="demo_seed",
                posted_at=data.get("posted_at"),
            )
            print(f"  [{i}/{len(_OPPORTUNITIES)}] {opp.professor_name} — {opp.institution}")

        await db.commit()
        print("Done.")

    await engine.dispose()


if __name__ == "__main__":
    reset_flag = "--reset" in sys.argv
    asyncio.run(main(reset=reset_flag))
