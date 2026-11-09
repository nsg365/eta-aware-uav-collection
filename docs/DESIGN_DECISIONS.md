# Design decisions and open issues

Reference: *Energy-Aware WSN–UAV Data Muling with ETA-Risk-Aware PPO and Adaptive Wake
Scheduling* .


## D1. 802.15.4 member→CH hop is an analytic model — Decided

**Issue.** The paper (Sec. III-A) uses IEEE 802.15.4 for sensor→CH links, with custom radio-state
energy accounting. ns-3.47 `lr-wpan` has no device energy model: the only "energy" in
`src/lr-wpan/model` is CCA/energy detection, checked with grep.
**Decision.** The simulation does **not** simulate the 802.15.4 hop with ns-3. Each reading costs
the member `txPower154 × airtime` and the CH `rxPower154 × airtime`, where
airtime = 8·(readingBytes + overhead154)/rate154. The CH also pays a continuous 802.15.4 listen
duty `chListenDuty154`. Loss on the hop is Bernoulli(`lossProb154`), default 0. Plain members are
not ns-3 nodes.
**Impact.** There are no intra-cluster collisions, hidden terminals or MAC delay. The paper must
not claim an 802.15.4 simulation unless Phase 1 replaces this with the lr-wpan MCPS data
path (with our energy ledger driven by its PHY state traces).

## D2. ns-3 `WifiRadioEnergyModel` switches the radio OFF prematurely — Decided (workaround)

**Evidence.** Setup: always-on CH, E0 = 500 J in `BasicEnergySource`, 0.3 W idle. The model's
total consumption froze at 241.7 J around 700–805 s, with about 258 J still left. The model
schedules an automatic OFF at `GetMaximumTimeInState()` = remaining / (I_state·V). The observed
OFF times match a prediction made at TX current during the first upload
(≈ 30 s + 491 J / 0.72 W ≈ 712 s) that was never replaced. The exact cancellation path was
**not fully root-caused**.
**Decision.** The ns-3 source capacity is set far above any in-horizon need (1e6 J, or less if
needed to keep the predicted time-to-empty inside the int64-ns range of `ns3::Time`; a guard
aborts if the margin is too small). The real budget E0 is enforced by our own check every
`energyCheckInterval` on the combined energy:

    E_used = sleepPower·t + E_154,tx + E_154,rx + chListenDuty154·(rxPower154 − sleepPower)·t
             + E_wifi(ns-3 WifiRadioEnergyModel)

At depletion, the node's PHY is set OFF and its buffer is counted as `lost_ch_dead`.
**Guard.** `tests/test_simulation.py::test_always_on_wifi_energy_matches_idle_power`.
**Follow-up.** Phase 1 should reproduce this on a minimal ns-3 example and check the ns-3
issue tracker before the paper relies on the native depletion path.

## D3. CH score eq. (3) mixes units — Decided (minimal correction)

**Issue.** S_i = α·E_res/E_max + (1−α)·1/(d + ε0). The first term is dimensionless; the second is
in 1/m and unbounded as d → 0, so α has no consistent meaning.
**Decision.** S_i = α·E_res/E_max + (1−α)·(1 − d/R_UAV), with both terms in [0, 1].
Feasibility (eq. 2) already guarantees d ≤ R_UAV.
**Impact.** None on the initial election: all batteries are full, so the closest feasible
candidate wins in both forms. It matters for energy-triggered re-election (Phase 1).

## D4. "Split if fewer than three feasible candidates" — Decided (configurable)

**Issue.** Primary + backup needs two candidates, not three. Requiring three is impossible for
clusters of size < 3, which the paper itself creates ("noise points … form a small cluster").
**Decision.** `min_candidates = 2` (configurable). Singleton clusters have a primary and no
backup; their count is reported in `meta.json` (`clusters_without_backup`).

## D5. DBSCAN does little on uniform deployments — Open (team decision)

**Observation.** At defaults (N = 100, 500 m × 500 m, R_s = 80 m, κ = 0.8), DBSCAN finds a few
large density-connected components. The eq. (2) feasibility constraint then forces 21 recursive
2-means splits to reach 23 clusters (with R_s = 60 m: 24 splits, 35 clusters). The final
clustering is mostly determined by the feasibility splitting, not by DBSCAN.
**Options.** (a) State this honestly and keep DBSCAN as the first stage. (b) Evaluate on
clustered (non-uniform) deployments, where DBSCAN's density reasoning is what matters. (c)
Replace it with a constraint-aware method (e.g. size-/diameter-constrained k-means).
**Recommendation.** (a) + (b): add a Gaussian-hotspot deployment generator (Phase 2).

## D6. Noise-point handling — Decided

Noise joins the cluster of its nearest clustered sensor if within R_s, else it becomes a
singleton. This is followed by the feasibility split (D4).

## D7. Who tells a sleeping CH when the UAV will come? — **Decided: promise-then-honour** (2026-10-23)

**Issue (central).** A CH can only sleep until τ_k − w_k if it already knows τ_k, and it can only
learn τ_k while the UAV is in contact. Algorithm 2 line 7 hands over "the ETA range … to the
current primary CH" on arrival, which is too late for that visit. Eq. (10) gives ETA = d/v to the
*selected* cluster, which is only known when PPO picks the next cluster. At that moment the CH
is asleep and unreachable. A one-step PPO policy therefore has no ETA to promise to the
clusters it leaves.

**Decision.** Promise-then-honour:
1. When the UAV finishes a contact with cluster k, it sends a PLAN promising a revisit time T_k.
2. CH k sleeps until T_k − w_k and listens until T_k + w_k (missed window → DISCOVERY now, RETRY
   in Phase 1).
3. At every decision epoch PPO picks the next cluster *knowing the outstanding promises*.

**Consequences for PPO (Phase 3).**
- Observation per cluster adds time-to-promise (T_k − now), alongside belief state.
- Reward: R_miss (eq. 36) = a broken promise, i.e. the UAV reaches cluster k after T_k + w_k.
- Mask: optional. Masking clusters that would make an earlier promise unreachable is a design
  choice to test, not a requirement.

**Consequences for ETA risk / adaptive window (Phases 2–3).**
- The prediction target is *lateness relative to the promise*, e_k = t_arrive,k − T_k (signed),
  measured in `visits.csv`. This replaces eq. (10)–(12) as the learning target (see D9).
- The adaptive half-width w_k is sized from a predicted upper quantile of e_k.

**Who sets T_k — Decided (2026-10-23): fixed period.** T_k = now + P, where P is the nominal
period of the committed timetable: tour legs at `planSpeedFactor·v` plus `hoverBudget` per stop
(computed in `UavApp::PromisePeriod`, about 300–320 s at defaults). P is derived from
the tour, not hand-tuned. The same rule applies to *every* routing policy (tour, heuristics,
PPO), so all comparison models run under the same wake mechanism and differ only in visit order.
Broken promises are a reward penalty (R_miss) in the first PPO version, not a hard action mask.
Reasons: a promise-keeping policy is known to exist (the tour: 0 missed windows in Phase 0 runs);
"tour + fixed wake" vs PPO then isolates the routing gain; one derived parameter; no feedback
loop (an earlier "now + measured lap time" rule drifted to ~285 s ETA error).
*Extension, only if needed:* PPO chooses T_k ∈ {0.75, 1, 1.5}·P at each contact (option b).

**Compatibility with the proposal (checked against the PDF).**
- Unchanged: action (eq. 28); state W_i (eq. 23), which becomes time-to-promise; wake window
  (eq. 17); R_miss / R_risk (eqs. 31, 36); survey-lap bootstrap; retry window (eq. 20) with
  τ_k = T_k; failover; all comparison models and ablations A1–A9. The proposal already uses
  promises (Table II "promised window"; metric "promise violations").
- Deviation 1: the time handed to a CH is T_k = now + P, not the eq. (10) straight-line ETA
  rolled along a route. Eq. (10) remains the UAV's own arrival estimate (lateness features,
  optional feasibility checks). The proposal did not specify how an eq. (10) ETA could reach a
  CH that is already asleep.
- Deviation 2: one added parameter, P, derived from the tour.

**What is implemented (4 Nov).** At each contact the UAV promises T_k = now + P. P is one tour
lap with legs at `planSpeedFactor·v` and `hoverBudget` per stop. While some clusters have never
been contacted (survey lap), the promise adds T_b/2 − `hoverBudget` per such cluster, because
the UAV waits about T_b/2 for a CH in DISCOVERY (measured: 3.7–5.1 s per stop at T_b = 10 s).
Budgeting the worst case T_b + t_l instead over-promised the first clusters by about 2 min; the
UAV's hold there made the rest of the next lap late. This replaced a committed absolute timetable
(slot of cluster k in lap n), which works only for the fixed tour. `wakeMode=scheduled` is still
rejected for policies that do not commit to an order; Phase 2 lifts this.

**Rejected alternatives.** No promises / adaptive duty cycling only (drops the paper's ETA-window
contribution). A separate wake-up or long-range radio to deliver ETAs (hardware assumption
outside the paper's scope).

## D8. Early UAV holds until the window opens — Decided

If the UAV arrives before τ − w, it keeps polling until the window opens plus `contactWait`. If it arrives after
τ + w, it holds until the next retry window opens (D16), unless all retries are over.
Without this, an early arrival is a guaranteed miss (observed in the first run). Consequence: an
early arrival costs UAV hover energy, not CH energy. Since the UAV holds, only the *late* side of
the window needs width. Phase 2 should use an asymmetric window
[τ − w_margin, τ + w_late] instead of eq. (18).

## D9. Eqs. (11), (12), (17): the drift term — Proposed correction

**Issue (instructor's question).** With e_res = max(0, e − w_drift) and w = w_drift + Q_p(e_res) +
w_margin: since Q_p(max(0, e − c)) = max(0, Q_p(e) − c), we get w_drift + Q_p(e_res) =
max(w_drift, Q_p(e)). Subtracting and re-adding w_drift is a no-op; drift is not "handled
explicitly". It is only learned implicitly inside e.
**Correction.** Measure arrival error in *true (simulator) time*, signed: e_arr = t_actual − t_pred.
Clock offset is a separate bounded term |δ_clk| ≤ w_drift that the simulator applies to the CH's
clock. Window: [t_pred − w_drift − w_margin − q_lo, t_pred + w_drift + q_hi], where q_lo and q_hi
are quantiles of e_arr; with D8, q_lo ≈ 0. No subtraction is needed.
**Also.** Absolute error discards the sign, but early and late arrivals have different costs
(D8). In Phase 0 runs, *all* errors were early (mean −24 s, 0 % late beyond w), because the
timetable has slack. Clock drift is **not modelled** yet (Phase 1).
**Missing factors (Fig. 4).** Hover/upload-time variability at the intermediate stops dominated
the first ETA errors and is absent from z_i. Several listed inputs (ρ̂_clk, δ̂_UAV, Δ_route)
have no defined estimator.

## D10. p_q = 0.95 — Proposed

It is a target coverage probability, not a derived constant. Sweep p_q ∈ {0.8, 0.9, 0.95, 0.99}
and report CH listening energy vs meeting success. The knee of that curve is the justification.

## D11. Energy scale and radio parameters — Decided (with documented assumptions)

**Initial energy.** Each sensor starts with E₀ = 500 J. This is a simulation assumption selected to allow energy depletion within the 2-hour simulation horizon; it is not a measured battery capacity. Results should be compared across variants using the same energy budget.

**802.15.4 member-to-CH link.** The analytical energy model uses a 3 V supply and the following CC2420 reference-radio values:

| Parameter | Value | Basis |
|---|---:|---|
| TX current | 17.4 mA | Texas Instruments CC2420 datasheet |
| RX current | 18.8 mA | Texas Instruments CC2420 datasheet |
| TX power | 52.2 mW | 3 V × 17.4 mA |
| RX power | 56.4 mW | 3 V × 18.8 mA |

These powers are used by the analytical 802.15.4 energy ledger (D1); the member-to-CH packet exchange is not simulated using ns-3's LR-WPAN model.

**Wi-Fi CH-to-UAV link.** The simulated link uses ns-3 802.11g. The current parameters are reference-device approximations, not a claim that the simulated cluster head is a particular physical device.

| Parameter | Value | Basis |
|---|---:|---|
| TX current | 190 mA | ESP32 reference: typical 802.11g TX at 16 dBm |
| RX current | 100 mA | Approximation within the ESP32 datasheet's typical receive-current range |
| Idle current | 100 mA | Approximation using receive/listen current |
| Sleep current | 0.15 mA | Simulation assumption; not established here as a directly equivalent ESP32 radio-sleep measurement |

The Wi-Fi currents configure ns-3's `WifiRadioEnergyModel`. The supply voltage used for energy accounting is 3 V. Actual current depends on hardware, radio state, transmit power, and operating conditions; these values should therefore be treated as a documented reference model rather than universal device characteristics.

**Reproducibility.** Energy comparisons must use the same parameters across the compared variants. Report these assumptions alongside energy and lifetime results, and revisit the sleep-current assumption if a more closely matched radio-state measurement is identified.

## D12–D17. Smaller modelling choices — Decided

- **D12.** "Delivered" = received at the UAV. Depot offload and UAV battery limits/returns are not
  modelled yet. UAV flight/hover energy is reported as an *estimate* (eq. 9), separate
  from simulated radio energy.
- **D13.** Readings leave the CH buffer when handed to the socket. 802.11 MAC retransmits unicast
  frames; residual loss is `lost_wifi`. There is no application-level ACK.
- **D14.** Timetable slack parameters `hoverBudget` and `planSpeedFactor` exist only because a
  committed schedule needs slack (D7).
- **D15.** The UAV flies at constant altitude H everywhere, including the depot. Takeoff and
  landing are not modelled.
- **D16.** Retry windows (eq. 20). When a promised window [τ − w, τ + w] closes without contact,
  the CH sleeps and opens retry m = 1..`maxMissedRetries` at τ + w + m·`retryInterval` for
  `retryListen` s; after the last one it returns to DISCOVERY. A late UAV holds for the next retry
  window (D8). A missed promise is counted once (`windows_missed` = `promise_violations`); a
  contact in a retry window counts as `retry_successes`, not as a met window. Defaults 12 s /
  10 s / 5 retries were chosen from a sweep (N = 100, 5 seeds, 10 % of legs delayed 10–30 s,
  with and without CH failures): spacing 30 s recovered as many misses but the UAV's longer holds
  made later clusters late and raised CH energy (172 J vs 106 J); 5 retries instead of 3
  recovered 93 % instead of 79 % of meetings with CH failures on.
- **D17.** PDR = delivered / generated over the horizon, including readings still buffered at
  the end (`in_buffer_at_end`). This is about 2 % at defaults; report it alongside PDR.

## D18. Scope reduction for the paper — Proposed

Keep: DBSCAN/feasibility clustering, primary/backup, survey-lap bootstrap, promise-at-contact
wake windows, PPO next-cluster selection, ETA-lateness quantile, failover vs missed-meeting
separation.

Simplify first, add back only if an ablation shows a gain:
- Reward (31) has six terms. Start with R_D − β_E·R_UAV − β_M·R_miss.
- Urgency (29) adds three more coefficients.
- Semi-MDP discount γ^{Δt/T0}: SB3 PPO uses a fixed γ; this needs a custom wrapper, so verify
  before claiming it.
- Shannon planning rate (7): use the configured ns-3 PHY rate instead.
- The 9-feature quantile MLP: start with an empirical quantile per (distance, stops-ahead) bin.

### UAV–Cluster Head Wi-Fi Range Calibration

**Decision:** Use `uav_range_m = 30.0 m` as the initial horizontal coverage radius for topology construction and cluster-head meeting-point feasibility.

**Method:** A separate ns-3.47 calibration experiment used two Wi-Fi nodes, a 30 m UAV altitude, 802.11g at 6 Mbps, 16 dBm transmit power, a log-distance propagation model (path-loss exponent 3.0), and Nakagami fading. Each run attempted 1,000 UDP packets. Five random seeds were tested at each distance.

**Results:**

| Horizontal distance | Mean delivery ratio | Minimum across five seeds |
|---:|---:|---:|
| 30 m | 99.96% | 99.9% |
| 35 m | 97.60% | 89.7% |
| 40 m | 92.46% | 86.0% |
| 42 m | 73.76% | 54.6% |

At 30 m, 4,998 of 5,000 packets were delivered. Delivery degraded and became more variable at larger distances.

**Rationale:** The 30 m radius is a conservative initial choice based on the tested simulation configuration and a target of at least 99% delivery in each of the five tested seeds. The parameter represents horizontal CH-to-meeting-point distance, consistent with the topology feasibility check.

**Limitations:** This experiment is a simulation calibration, not a measurement of real-world Wi-Fi range. Results depend on the propagation model, fading, PHY/MAC settings, altitude, traffic pattern, and random seed.

**Reproduction (4 Nov).** The original sweep program was not committed and its fading parameter was not recorded, so the table above could not be reproduced exactly. `simulation/ns3/wsn-uav-range` (same link settings as the simulation, 1,000 frames per distance, 5 seeds, `--nakagamiM` for fading) gives, mean delivery (minimum over seeds):

| Fading | 25 m | 30 m | 35 m | 40 m | 41 m | 42 m |
|---|---:|---:|---:|---:|---:|---:|
| none (as in the main simulation) | 100 % | 100 % | 100 % | 100 % | 100 % | 0 % |
| Nakagami m = 1 (Rayleigh) | 95.9 % (93.1) | 74.6 % (72.2) | 56.0 % | 43.3 % | 40.9 % | 37.4 % |
| Nakagami m = 2 | 100 % | 100 % (99.9) | 77.6 % | 53.4 % | 47.7 % | 42.1 % |
| Nakagami m = 3 | 100 % | 100 % | 92.8 % (89.8) | 55.9 % | 50.5 % | 46.6 % |

The simulated link has no fading, so it is a hard cutoff at 41 m (ns-3's −82 dBm preamble-detection threshold at 30 m altitude). 30 m is kept as a conservative radius: it is the largest that keeps ≥ 99 % delivery in every seed under moderate fading (m ≥ 2). Data: `results/sample/range_calibration.csv`. Reproduce: `./ns3 build wsn-uav-range`, then `build/scratch/wsn-uav-range/ns3.47-wsn-uav-range-default --out=range.csv --maxRho=50 --step=1 --packets=1000 --nakagamiM=2 --seed=1`.
