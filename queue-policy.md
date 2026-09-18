Queue policy

At >=1000 pending: Pump.fun every 900s, market every 1800s, 5 profiles/batch. At >=200: 300s/1200s/5. Below 200: 60s/900s/3. Intervals start at completion. Shared 6s GMGN pacer unchanged.

30D first; request 7D only if all other admission conditions pass. Missing 7D remains unavailable, never inferred. Every fifth completed slot targets an overdue observing/signal_only profile; every preceding fourth slot targets oldest pending. Other pending sorted by absence of blocking observation tags, profitable token hits, then age. Manual-review dossiers are not overwritten by this scheduler.

Repeatability update: missing discovery hits no longer blocks 7D fetching. If the remaining gates pass and fewer than two discovery tokens are profitable, fetch up to 3 activity pages. Count distinct tokens with positive net PnL across fully closed cycles after available fees, excluding invalid inventory/transfers. Union token identities with discovery hits. Insufficient history remains observing with HISTORY_REPEATABILITY_INSUFFICIENT, eligible for later refresh; never classify missing evidence as negative PnL. Reuse fetched metrics for the manual dossier.
