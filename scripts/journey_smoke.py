"""Journey smoke test — walks the full user journey against the live backend."""
import asyncio
import time

import httpx

BASE = "http://localhost:8000/api"
TS = int(time.time())
EMAIL = f"smoketest{TS}@test.com"


async def main() -> None:
    async with httpx.AsyncClient(timeout=60) as c:
        print("=== JOURNEY SMOKE TEST ===\n")

        # [1] Signup
        r = await c.post(f"{BASE}/auth/signup", json={"name": "Smoke User", "email": EMAIL, "password": "testpass123"})
        d = r.json()
        token = d.get("token", "ERROR")
        user_id = d.get("user", {}).get("id", "ERROR")
        print(f"[1] POST /auth/signup -> {r.status_code}  token={token[:20]}...  user_id={str(user_id)[:8]}...")
        assert r.status_code == 201, f"Signup failed: {d}"

        headers = {"Authorization": f"Bearer {token}"}

        # [2] PUT /profile
        r = await c.put(f"{BASE}/profile", headers=headers, json={
            "university": "IIT Delhi", "university_tier": 1, "degree": "B.Tech",
            "branch": "Computer Science", "gpa": 8.9,
            "skills": ["Python", "PyTorch", "NLP", "Machine Learning"],
            "research_interests": ["NLP", "computer vision"],
            "target_roles": ["Research Intern"], "target_sectors": ["Technology"],
            "year_of_study": 3,
        })
        print(f"[2] PUT /profile -> {r.status_code}")
        assert r.status_code == 200, f"Profile failed: {r.text}"

        # [3] GET /matches — returns {data, page, limit, total}
        r = await c.get(f"{BASE}/matches", headers=headers)
        d = r.json()
        total = d.get("total", 0)
        matches = d.get("data", [])
        posting_id = matches[0]["posting_id"] if matches else None
        match_exp = matches[0].get("match_explanation", "NONE")[:70] if matches else "NONE"
        print(f"[3] GET /matches -> {r.status_code}  total={total}  top_posting={str(posting_id)[:8]}...")
        print(f'    match_explanation: "{match_exp}"')
        assert r.status_code == 200
        assert posting_id, "No matches returned"

        # [4] POST /applications/draft — requires posting_id, type, channel
        r = await c.post(f"{BASE}/applications/draft", headers=headers, json={
            "posting_id": posting_id,
            "type": "cover_letter",
            "channel": "email",
        })
        d = r.json()
        artifact = d.get("artifact", {})
        artifact_id = artifact.get("id", "ERROR")
        art_type = artifact.get("type", "ERROR")
        ats = artifact.get("ats_score", "N/A")
        grounding = artifact.get("grounding_score", "N/A")
        missing_kw = len(artifact.get("missing_keywords", []))
        print(f"[4] POST /applications/draft -> {r.status_code}  type={art_type}  ats={ats}  grounding={grounding}  missing_kw={missing_kw}")
        print(f"    artifact_id={str(artifact_id)[:8]}...")
        assert r.status_code == 200, f"Draft failed: {r.text}"
        assert artifact_id != "ERROR", "No artifact_id in draft response"

        # [5] POST /applications — requires posting_id + channel + artifact_id
        r = await c.post(f"{BASE}/applications", headers=headers, json={
            "posting_id": posting_id,
            "channel": "email",
            "artifact_id": artifact_id,
        })
        d = r.json()
        app_id = d.get("application", {}).get("id", "ERROR")
        app_status = d.get("application", {}).get("status", "ERROR")
        print(f"[5] POST /applications -> {r.status_code}  app_id={str(app_id)[:8]}...  status={app_status}")
        assert r.status_code in (200, 201), f"Create application failed: {r.text}"

        # [6] GET /applications
        r = await c.get(f"{BASE}/applications", headers=headers)
        d = r.json()
        count = len(d.get("data", []))
        print(f"[6] GET /applications -> {r.status_code}  count={count}")
        assert r.status_code == 200
        assert count >= 1, "Application list should have at least 1 item"

        print("\n--- Part 2: Referrals + Research ---")

        # [7] GET /referrals/candidates — requires posting_id or company_id query param
        r = await c.get(f"{BASE}/referrals/candidates", headers=headers, params={"posting_id": posting_id})
        d = r.json()
        cands = d.get("data", d.get("candidates", d if isinstance(d, list) else []))
        cand_count = len(cands)
        print(f"[7] GET /referrals/candidates -> {r.status_code}  candidates={cand_count}")
        assert r.status_code == 200, f"Referrals candidates failed: {r.text}"

        # [8] GET /research/opportunities — returns {data, page, limit, total}
        r = await c.get(f"{BASE}/research/opportunities", headers=headers)
        d = r.json()
        opp_total = d.get("total", 0)
        opp_items = d.get("data", [])
        opp_id = opp_items[0].get("opportunity", {}).get("id", "NONE") if opp_items else "NONE"
        fit_score = opp_items[0].get("fit_score", "N/A") if opp_items else "N/A"
        fit_exp = opp_items[0].get("fit_explanation", "")[:60] if opp_items else ""
        print(f"[8] GET /research/opportunities -> {r.status_code}  total={opp_total}  top_opp={str(opp_id)[:8]}...  fit={fit_score:.3f}")
        print(f'    fit_explanation: "{fit_exp}"')
        assert r.status_code == 200
        assert opp_id != "NONE", "No research opportunities returned"

        # [9] POST /research/pitch — returns flat Artifact (no nesting), Subject: in content
        r = await c.post(f"{BASE}/research/pitch", headers=headers, json={"opportunity_id": opp_id})
        d = r.json()
        pitch_art_id = d.get("id", "ERROR")
        pitch_type = d.get("type", "ERROR")
        content = d.get("content", "")
        subj_line = next((ln.replace("Subject:", "").strip() for ln in content.splitlines() if ln.startswith("Subject:")), "NONE")
        pitch_grounding = d.get("grounding_score", "N/A")
        print(f"[9] POST /research/pitch -> {r.status_code}  type={pitch_type}  grounding={pitch_grounding}")
        print(f'    subject: "{subj_line[:70]}"')
        print(f"    artifact_id: {str(pitch_art_id)[:8]}...")
        assert r.status_code == 200, f"Research pitch failed: {r.text}"
        assert pitch_type == "research_pitch", f"Expected type=research_pitch, got {pitch_type}"

        print("\n--- Part 3: Notifications + Dashboard + Evaluation ---")

        # [10] GET /notifications — returns list[Notification]
        r = await c.get(f"{BASE}/notifications", headers=headers)
        notifications = r.json()
        notif_count = len(notifications) if isinstance(notifications, list) else 0
        unread = sum(1 for n in notifications if not n.get("read_at")) if isinstance(notifications, list) else 0
        print(f"[10] GET /notifications -> {r.status_code}  count={notif_count}  unread={unread}")
        assert r.status_code == 200, f"Notifications failed: {r.text}"

        # [11] GET /dashboard — shape: {pipeline:{saved,applied,...}, platform_iq, iq_trend, ...}
        r = await c.get(f"{BASE}/dashboard", headers=headers)
        d = r.json()
        pipeline = d.get("pipeline", {})
        pipeline_total = sum(pipeline.get(k, 0) for k in ["saved", "applied", "viewed", "responded", "interview", "offer"])
        platform_iq = d.get("platform_iq", "N/A")
        iq_trend = d.get("iq_trend", [])
        resp_rate = d.get("response_rate", "N/A")
        print(f"[11] GET /dashboard -> {r.status_code}  pipeline_total={pipeline_total}  platform_iq={platform_iq}  resp_rate={resp_rate}")
        print(f"     iq_trend: len={len(iq_trend)}  ghosts_avoided={d.get('ghosts_avoided', 0)}  time_saved={d.get('time_saved_hours', 0)}h")
        assert r.status_code == 200, f"Dashboard failed: {r.text}"
        assert "pipeline" in d, "Dashboard missing pipeline key"
        assert "platform_iq" in d, "Dashboard missing platform_iq key"

        # [12] GET /evaluation/metrics — shape: {latest: EvaluationSchema|null, iq_trend: []}
        r = await c.get(f"{BASE}/evaluation/metrics", headers=headers)
        d = r.json()
        latest = d.get("latest")
        eval_iq = latest.get("platform_iq") if latest else "null (no evaluations yet)"
        print(f"[12] GET /evaluation/metrics -> {r.status_code}  latest={eval_iq}")
        assert r.status_code == 200, f"Evaluation metrics failed: {r.text}"
        assert "latest" in d, "Evaluation metrics missing latest key"
        assert "iq_trend" in d, "Evaluation metrics missing iq_trend key"

        print("\n=== ALL 12 STEPS PASSED ===")


if __name__ == "__main__":
    asyncio.run(main())
