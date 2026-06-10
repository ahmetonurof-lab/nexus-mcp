# NEXUS V3 — İşleme Giriş Mimarisi

```mermaid
flowchart TD
    subgraph HTF["1️⃣ HTF Analysis (H1/2H)"]
        A1[HTF Bias] --> A2[Sweep @ 15m]
        A2 --> A3[MSS / CHoCH]
        A3 --> A4[FVG Detection]
        A4 --> A5{FVG Active?}
        A5 -->|is_active=True ✅| A6[FVG Kaydedildi]
        A5 -->|is_active=False 🔥| A7[REDDEDİLDİ]
    end

    subgraph STATE["2️⃣ State Machine (10 State)"]
        B1[IDLE] -->|Sweep| B2[ARMED]
        B2 -->|MSS| B3[WAIT_RETRACE]
        B3 --> B4{check_retrace<br/>PenetrationEngine}
        B4 -->|pen 0.15-0.70 ✅| B5[WAIT_CONFIRM]
        B4 -->|pen < 0.15 ❌| B6[MISSED_FVG]
        B6 --> B7{check_poi_retrace}
        B7 -->|POI bölgesinde| B8[WAIT_POI_CONFIRM]
        B5 --> B9{LTF Confirm}
        B8 --> B9
        B9 -->|pen ≤ 0.70 ✅| B10[READY_TO_ENTER]
        B9 -->|pen > 0.70 🚫| B11[WAIT_NEW_FVG]
        B11 -->|yeni FVG<br/>is_active=True ✅| B3
        B11 -->|is_active=False 🔥| B6
    end

    subgraph EXEC["3️⃣ Execution"]
        C1[READY_TO_ENTER] --> C2[Order Gönder]
        C2 --> C3[SL @ 4H Swing]
        C2 --> C4[TP @ 1H Likidite]
    end

    subgraph CLEANUP["4️⃣ Zombie Cleanup"]
        D1[_check_stale_state]
        D1 -->|expired ⏰| D2[→ IDLE]
    end

    A6 --> B3
    B10 --> C1
    B11 -.->|stale| D1
    B6 -.->|stale| D1
    B8 -.->|stale| D1
```

## Özet

| Aşama | Açıklama |
|-------|----------|
| **1️⃣ HTF** | H1 birincil, 2H fallback. `is_active=False` olan FVG reddedilir |
| **2️⃣ State Machine** | 10 state: IDLE → ARMED → WAIT_RETRACE → WAIT_CONFIRM / MISSED_FVG → READY_TO_ENTER |
| **🔁 Döngü** | pen > 0.70 (FVG delinmiş) → WAIT_NEW_FVG → yeni FVG beklenir |
| **❌ Zombi** | WAIT_NEW_FVG, MISSED_FVG, WAIT_POI_CONFIRM expire olursa IDLE |
| **3️⃣ Execution** | READY_TO_ENTER → order → 4H swing SL + 1H likidite TP |
