# Work Allocation Report — [Team 03]

> **Instructions:** Complete this document as a team before or alongside your final submission.
> Submit one copy per team via EEClass. This document is shared with all markers.
> Be specific — vague entries ("we all helped") will prevent individual contribution adjustments from being applied in your favour.

---

## 1. Team Members

| Full Name | Student ID | GitHub Username | Email |
|-----------|-----------|----------------|-------|
| 陳映均 | 110707519| chunchuninn | inkinbb15@gmail.com |
| 池翊寧 | 112302534 | ch1ng_9412 | ian9404120927@gmail.com |
| 莊可翰 | 111409016 | hank1030zz | hank1030zz@gmail.com |

---

## 2. Task Ownership

For each task, name the **primary owner** (the person most responsible for delivering it)
and any **supporting members** (who assisted but were not the lead). Leave the Notes column
for anything that deviates from the standard expectation (e.g., task was pair-programmed,
or reassigned mid-project).

### Code Repository

| Task | Primary Owner | Supporting Member(s) | Notes |
|------|--------------|---------------------|-------|
| **Task 1** — Relational schema design (`schema.sql`) | 池翊寧 | 陳映均、莊可翰 | |
| **Task 2a** — Core availability & fare queries (`query_national_rail_availability`, `query_metro_schedules`, `query_national_rail_fare`, `query_metro_fare`) | 莊可翰 | 池翊寧、陳映均 | |
| **Task 2b** — Seat & user queries (`query_available_seats`, `query_user_profile`, `query_user_bookings`, `query_payment_info`) | 莊可翰 | 池翊寧、陳映均 | |
| **Task 2c** — Write operations (`execute_booking`, `execute_cancellation`) | 莊可翰 | 池翊寧、陳映均 | |
| **Task 2d** — Authentication queries (`login_user`, `register_user`, `get_user_secret_question`, `verify_secret_answer`, `update_password`) | 陳映均 | 池翊寧、莊可翰 | |
| **Task 3** — PostgreSQL seeding (`seed_postgres.py`) | 池翊寧 | 陳映均、莊可翰 | |
| **Task 4** — Neo4j graph design & seeding (`seed_neo4j.py`, `seed.cypher`) | 陳映均、莊可翰 | 池翊寧 | |
| **Task 5** — Neo4j query functions (`graph/queries.py`) | 陳映均 | 池翊寧、莊可翰 | |

### Design Document

| Section | Primary Author | Supporting Member(s) | Notes |
|---------|--------------|---------------------|-------|
| Section 1 — ER Diagram | 池翊寧 | | |
| Section 2 — Normalisation Justification | 池翊寧 | | |
| Section 3 — Graph Database Design Rationale | 陳映均 | | |
| Section 4 — Vector / RAG Design | 莊可翰 | | |
| Section 5 — AI Tool Usage Evidence | 莊可翰 | 池翊寧、陳映均 | |
| Section 6 — Reflection & Trade-offs | 莊可翰 | 池翊寧、陳映均 | |

---

## 3. Estimated Contribution Percentages

Based on the task allocation above, what percentage of total team effort do you estimate each member contributed?
All members must sum to 100%.

| Member | Estimated % | Brief justification |
|--------|-----------|---------------------|
| 池翊寧 | 33% | 起初先完成 schema.sql, seed_postgres.py 的編程，以利後續開發作業 |
| 莊可翰 | 33% | 完成seed_neo4j.py以利後續開發作業, 完成最初問題相關queries  |
| 陳映均 | 33% | 完成graph database(seed.cypher),Neo4j query functions以及登入介面 |
| **Total** | **100%** | |

---

## 4. Mid-Project Changes

If any tasks were reassigned or the original plan changed significantly, document it here.
If nothing changed, write "No changes."

| Change | Original plan | Revised plan | Reason |
|--------|--------------|-------------|--------|
| No changes. | | | |

---

## 5. Team Declaration

We confirm that this work allocation accurately reflects how responsibilities were divided within our team.

| Name | Signature / Typed name | Date |
|------|----------------------|------|
| 池翊寧 | 池翊寧 | 2026/6/3 |
| 莊可翰 | 莊可翰 | 2026/6/3 |
| 陳映均 | 陳映均 | 2026/6/3 |
