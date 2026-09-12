import portfolio_manager

# Test hard stop loss for a LONG position
# Expected: current_price 96.9 with entry_price 100 triggers -3% stop.

# Prepare a minimal position in memory by calling update_all_positions requires CSV state,
# so this script only demonstrates the runtime value check for now.
print("module:", portfolio_manager.__file__)
print("hard_stop_pct:", portfolio_manager.HARD_STOP_PCT)
print("long_stop_price_for_100:", 100 * (1 - portfolio_manager.HARD_STOP_PCT))
print("short_stop_price_for_100:", 100 * (1 + portfolio_manager.HARD_STOP_PCT))
