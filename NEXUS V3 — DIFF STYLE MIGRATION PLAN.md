NEXUS V3 — DIFF STYLE MIGRATION PLAN
🔴 PHASE 1 — NEW CORE (NO BREAK CHANGES)
➕ ADD: state_machine.py
+ /state_machine.py   (NEW FILE)  
YAPILDI

✔ önce tamamen ekle
❌ hiçbir dosya buna bağlanmaz

➕ ADD: event_router.py
+ /event_router.py
class EventRouter:
    def __init__(self, sm):
        self.sm = sm

    def publish(self, symbol, event):
        self.sm.update_from_event(symbol, event)
YAPILDI

🟡 PHASE 2 — ANALYZER → SENSOR TRANSFORMATION
📄 analyzer.py
❌ REMOVE (BÜYÜK BLOK)
- def is_valid_signal(...)
- def check_ltf_trigger(...)
- ADX veto logic
- scoring calls
- compute_fvg_quality usage as decision gate
- direction override logic (H4 / CHoCH conflict resolution)
🔁 CHANGE: analyze()
BEFORE:
def analyze(self):
    if adx < threshold:
        return None

    if fvg_quality < 0.4:
        return None

    return Signal(...)
AFTER:
- def analyze(self):
-     ... return Signal

+ def analyze(self):
+     events = []
+
+     if sweep_detected:
+         events.append({"type": "SWEEP", "level": x})
+
+     if mss_detected:
+         events.append({"type": "MSS", "level": x, "direction": x})
+
+     if fvg_detected:
+         events.append({"type": "FVG_CREATED", "upper": x, "lower": x})
+
+     if retrace_detected:
+         events.append({"type": "RETRACE", "price": x})
+
+     return events
YAPILDI

🎯 RESULT
analyzer = event generator ONLY
🟡 PHASE 3 — CHOCH → MSS CLEAN CONVERSION
📄 choch.py
❌ REMOVE
- trend bias override logic
- signal validation logic
- direction filtering
🔁 KEEP ONLY
+ detect_mss()
+ return MSS_EVENT
🔁 OPTIONAL RENAME
- choch.py
+ mss.py
YAPILDI

🟡 PHASE 4 — FVG SIMPLIFICATION
📄 fvg.py
❌ REMOVE
- compute_fvg_quality()
- veto logic inside FVG
- scoring dependencies
✔ KEEP
+ detect_fvgs()
+ update_fvg_states()
+ find_latest_unfilled_fvg()
🔁 ADD OUTPUT FORMAT
+ return {
+   "type": "FVG_CREATED",
+   "upper": ...,
+   "lower": ...,
+   "time": ...
+ }
YAPILDI

🟡 PHASE 5 — MAIN.PY REFACTOR (CRITICAL)
❌ REMOVE
- analyzer → risk → executor direct flow
- any decision logic in main
- signal validation logic
🔁 BEFORE FLOW
on_5m_close():
    signal = analyzer.analyze()
    if signal.valid:
        risk.evaluate(signal)
        executor.send(signal)
🔁 AFTER FLOW
on_5m_close():

    events = analyzer.analyze(symbol)

    for event in events:
        event_router.publish(symbol, event)
➕ ADD
state_machine = StateMachine()
event_router = EventRouter(state_machine)


🟡 PHASE 6 — STATE MACHINE HOOK
📄 state_machine.py integration
ADD ENTRY POINT:
+ def update_from_event(symbol, event)

✔ analyzer → state_machine only entry

🟡 PHASE 7 — RISK MANAGER SIMPLIFICATION
📄 risk_manager.py
❌ REMOVE
- signal scoring evaluation
- entry validation logic
✔ KEEP ONLY
+ build_trade(state)
+ calculate_sl()
+ calculate_tp()
+ calculate_lot()
🔁 BEFORE
evaluate(signal)
🔁 AFTER
build_trade(state_machine.get(symbol))
🟡 PHASE 8 — EXECUTION LAYER (NO LOGIC CHANGE)
📄 trader.py

❌ değişmez
✔ sadece input değişir

BEFORE:
execute(signal)
AFTER:
execute(trade = risk_manager.build_trade(state))
🟢 PHASE 9 — MAIN STATE STORAGE CLEANUP
📄 main.py
❌ REMOVE
- analyzer signal storage
- used_fvg_signals logic dependency
- duplicate CHoCH states
✔ KEEP
+ active_trades
+ state_machine
+ flush_state()
➕ ADD
symbol_states = state_machine
🟢 PHASE 10 — FINAL SYSTEM FLOW (NEW REALITY)
BEFORE:
WS → Analyzer → Risk → Executor
AFTER:
WS
 ↓
Analyzer (EVENTS ONLY)
 ↓
EventRouter
 ↓
StateMachine (DECISION CORE)
 ↓
RiskManager (math only)
 ↓
Executor
🔥 MIGRATION ORDER (CRITICAL)

Bunu sırayla yap:

1. state_machine.py ADD
2. event_router ADD
3. analyzer → event-only conversion
4. main.py flow rewrite
5. fvg.py cleanup
6. choch → mss conversion
7. risk_manager simplification
8. scoring removal (if still exists anywhere)
9. config cleanup
⚠️ EN KRİTİK KURAL
NO LIVE DECISION OUTSIDE STATE MACHINE
🚀 SON DURUM (V3 TARGET)
SYSTEM CHARACTER:
event-driven ✔
stateless analyzer ✔
centralized decision engine ✔
no scoring dependency ✔
liquidity-based logic ✔