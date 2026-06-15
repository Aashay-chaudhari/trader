## 2026-06-15 — Evening Reflection

### [HIGH] [execution] Separate Hold From Add Signals
Today the profile accumulated UAL repeatedly even when monitor reports said to hold or explicitly said not to duplicate the active position. Add a hard execution gate that only places a new order when the recommendation is buy, ready_to_trade is true, the symbol is not already at its max position budget, and an explicit add_reason is present.
**Expected impact:** Prevents one valid entry from becoming eleven correlated orders and would have materially reduced today's UAL drawdown.

### [HIGH] [risk_management] Add Position-Level Exposure Throttle
UAL grew to 57% invested in a single intraday thesis while the confirmation signal weakened. Add per-symbol and per-thesis caps, plus a cooldown after a position flips from positive to negative P&L.
**Expected impact:** Keeps one deteriorating setup from dominating account-level P&L and would have limited the final -0.98% portfolio hit.

### [MEDIUM] [screening] Escalate Confirmed Sector Leaders After The Open
The morning research correctly identified AMD, MU, and WDC as memory/AI beneficiaries, but the system did not rotate back to them after the sector confirmed with large moves. Add a post-open sector breadth scan that promotes watch-only names when multiple related leaders break out on volume.
**Expected impact:** Improves participation in the strongest theme of the day instead of over-focusing on a weaker sympathy setup.

### [MEDIUM] [data_source] Require Live Catalyst Inputs For Commodity-Linked Trades
XOM decisions repeatedly stalled because live WTI confirmation was missing or inconsistent, even though crude was the core catalyst. Add a reliable intraday WTI/Brent feed to the monitor context.
**Expected impact:** Reduces hesitation on valid oil-linked shorts and prevents trades when the commodity catalyst cannot be verified.

### [LOW] [knowledge] Track Sympathy Confirmation Decay
UAL depended on DAL remaining strong, but DAL lost the required levels while UAL continued to be accumulated. Store cross-symbol confirmation failures as a reusable pattern.
**Expected impact:** Helps future airline, cruise, and sector-pair trades exit or stop adding when the confirmation leg fails.
