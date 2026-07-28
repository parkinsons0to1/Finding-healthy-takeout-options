# MacroMeter

*A thermometer for your macros.*

Finding the best calorie:protein:price ratio in fast food menus and supermarket meal deals near you — with dietary filters (halal, kosher, vegetarian, vegan) and automatic discount application (StudentBeans, UNiDAYS, first-order app offers).

📄 **[Technical Implementation Plan](docs/TECHNICAL_IMPLEMENTATION_PLAN.md)** — product definition, sources of truth, architecture, data model, scoring engine, and phased roadmap.

📊 **[Phase 0 results — SM1 4FR](docs/PHASE0_SM1_4FR_RESULTS.md)** — hand-rolled dataset for Sutton High Street proving the MacroScore ranking: 24 real outlets (FSA FHRS API), live-scraped McDonald's nutrition, curated data for 11 more chains, discount rules, and the v0 scoring engine (`python3 scripts/phase0_rank.py`).
