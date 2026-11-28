# Paper: Promise-Based Wake Scheduling for UAV Data Collection

`main.tex` (IEEE two-column conference template), `refs.bib`, and the figures in `figures/`.
The draft covers the whole project: system model and wake rule, the PPO agent, results on ten
unseen networks, larger hotspot networks with the reduced noise (UAV speed 9–11 m/s), the
robustness sweeps of Phase 4, and the event-burst test.

## Build

- **Locally:** `cd paper && tectonic main.tex` (or `latexmk -pdf main.tex` with a TeX
  distribution such as MacTeX).
- **Overleaf:** upload `main.tex`, `refs.bib` and the `figures/` folder, compile with pdfLaTeX.

Fig. 1 is drawn in TikZ inside `main.tex`. Figs. 2–4 are made from the experiment results:

    cd paper && python3 make_figures.py --results ../results --phase4 ../results_phase4

This needs the raw runs in `results/` (git-ignored), which the configs below regenerate.

## Where the numbers come from

| Table / figure | Source |
|---|---|
| Simulation settings | `simulation/ns3/wsn-uav/config.h`, `configs/phase3_eval.toml` |
| Results on ten unseen networks, PPO minus tour | `docs/handoff/phase3.md` §5; Q-learning row: `configs/qlearning/phase3_eval.toml` |
| Effect of each training choice | `docs/handoff/phase3.md` §4 |
| Larger networks (Table VI, Fig. 3) | `results_phase3_ppo/README.md`, `configs/phase3_gaussian_scaling.toml`, `configs/phase3_ch_sweep_*.toml`, `configs/qlearning/` |
| Robustness of the wake rule (Table VII, Fig. 4) | `results_phase4/*/summary.md` |
| Small buffers and event bursts (Table VIII) | `docs/handoff/phase3.md` §6 and §13 |
| Routes (Fig. 2) | `results/phase3_eval/n100/s3/`, `results/qlearning_phase3_eval/n100/s3/` |

When a result changes, update the handoff first and then the paper.

## Writing rules

- Plain, short sentences.
- Every symbol is defined where it first appears and in the notation table.
- Only add an equation if everyone on the team can explain it.
