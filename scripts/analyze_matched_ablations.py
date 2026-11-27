#!/usr/bin/env python3
"""Paired statistical analysis for the Phase 4 matched ablation runs.

Reads results_phase4_full_ablation/*/runs.csv and writes analysis tables,
summary Markdown, and effect plots beneath results_phase4_full_ablation/analysis.
Pairing key: (run.num_sensors, run.seed).
"""
from __future__ import annotations

import argparse
import csv
import math
import warnings
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import stats

EXPERIMENTS = {
    "A7_backup_CH": {
        "folder": "a7_matched_multiseed",
        "comparisons": [("backup_enabled_control", "a7_no_backup")],
        "metrics": [
            "data.pdr", "energy.sensor_total_J", "energy.sensor_mean_J",
            "reliability.backup_promotions", "reliability.failures_no_backup",
            "reliability.failures_backup_dead", "reliability.retry_exhaustions",
            "lifetime.dead_nodes_at_end", "uav.distance_m",
        ],
        "plot_metrics": ["data.pdr", "energy.sensor_total_J", "reliability.failures_no_backup"],
    },
    "A8_immediate_failover": {
        "folder": "a8_matched_multiseed",
        "comparisons": [("a8_immediate_missed_meeting", "heartbeat_baseline")],
        "metrics": [
            "data.pdr", "energy.sensor_total_J", "reliability.backup_promotions",
            "reliability.failures_no_backup", "reliability.missed_meeting_triggers",
            "reliability.post_death_contact_triggers", "reliability.heartbeat_failure_triggers",
            "reliability.retry_attempts", "reliability.retry_successes",
            "reliability.retry_exhaustions", "wake.meeting_success_rate",
            "wake.windows_met", "wake.windows_missed",
        ],
        "plot_metrics": ["data.pdr", "energy.sensor_total_J", "reliability.backup_promotions", "reliability.retry_exhaustions"],
    },
    "A9_survey_lap": {
        "folder": "a9_matched_multiseed",
        "comparisons": [("a9_no_survey_lap", "a4_survey_lap_control")],
        "metrics": [
            "data.pdr", "energy.sensor_total_J", "uav.distance_m",
            "uav.flight_energy_J_est", "uav.hover_energy_J_est",
            "wake.meeting_success_rate", "wake.windows_scheduled", "wake.windows_met",
            "wake.windows_missed", "wake.mean_window_listen_s",
            "wake.scheduled_window_energy_J", "wake.ch_wifi_awake_fraction",
            "uav.contacts", "uav.failed_contacts", "reliability.retry_attempts",
            "reliability.retry_successes", "reliability.promise_violations",
        ],
        "plot_metrics": ["data.pdr", "uav.distance_m", "wake.scheduled_window_energy_J", "wake.meeting_success_rate"],
    },
    "wake_modes": {
        "folder": "phase4_wake_modes_multiseed",
        "comparisons": [
            ("a6_duty_cycle", "a5_always_on"),
            ("scheduled_wake_control", "a5_always_on"),
            ("scheduled_wake_control", "a6_duty_cycle"),
        ],
        "metrics": [
            "data.pdr", "energy.sensor_total_J", "energy.sensor_mean_J",
            "uav.distance_m", "uav.flight_time_s", "uav.hover_time_s",
            "uav.flight_energy_J_est", "uav.hover_energy_J_est",
            "uav.bytes_per_uav_joule", "wake.meeting_success_rate",
            "wake.ch_wifi_awake_fraction", "wake.scheduled_window_energy_J",
            "wake.mean_window_listen_s", "wake.windows_met", "wake.windows_missed",
        ],
        "plot_metrics": ["data.pdr", "energy.sensor_total_J", "wake.ch_wifi_awake_fraction", "uav.distance_m"],
    },
}


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def number(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def write_csv(path: Path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def holm_adjust(p_values):
    """Holm-Bonferroni adjusted p-values, preserving input order."""
    m = len(p_values)
    order = sorted(range(m), key=lambda i: p_values[i])
    adjusted = [1.0] * m
    running = 0.0
    for rank, idx in enumerate(order):
        value = min(1.0, (m - rank) * p_values[idx])
        running = max(running, value)
        adjusted[idx] = running
    return adjusted


def paired_stats(treatment, control):
    d = np.asarray(treatment, dtype=float) - np.asarray(control, dtype=float)
    n = len(d)
    mean_d = float(np.mean(d))
    sd_d = float(np.std(d, ddof=1)) if n > 1 else float("nan")
    se = sd_d / math.sqrt(n) if n > 1 and math.isfinite(sd_d) else float("nan")
    if n > 1 and math.isfinite(se):
        half = float(stats.t.ppf(0.975, n - 1) * se)
        ci_low, ci_high = mean_d - half, mean_d + half
    else:
        ci_low = ci_high = float("nan")
    if n > 1:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                t_p = float(stats.ttest_rel(treatment, control, nan_policy="omit").pvalue)
            except Exception:
                t_p = 1.0
        if np.allclose(d, 0):
            w_p = 1.0
        else:
            try:
                w_p = float(stats.wilcoxon(d, alternative="two-sided", zero_method="wilcox", method="auto").pvalue)
            except TypeError:  # Older SciPy versions
                w_p = float(stats.wilcoxon(d, alternative="two-sided", zero_method="wilcox", mode="auto").pvalue)
            except ValueError:
                w_p = 1.0
    else:
        t_p = w_p = 1.0
    dz = mean_d / sd_d if sd_d > 0 and math.isfinite(sd_d) else (0.0 if mean_d == 0 else float("nan"))
    return {
        "n_pairs": n,
        "treatment_mean": float(np.mean(treatment)),
        "control_mean": float(np.mean(control)),
        "mean_difference_treatment_minus_control": mean_d,
        "sd_paired_difference": sd_d,
        "ci95_low": ci_low,
        "ci95_high": ci_high,
        "paired_t_p": t_p,
        "wilcoxon_p": w_p,
        "cohen_dz": dz,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="results_phase4_full_ablation", help="Experiment results root")
    ap.add_argument("--expected-seeds", type=int, default=10)
    args = ap.parse_args()

    root = Path(args.root)
    out = root / "analysis"
    out.mkdir(parents=True, exist_ok=True)
    summary_rows, stat_rows = [], []
    plot_payload = defaultdict(list)

    for exp_name, spec in EXPERIMENTS.items():
        path = root / spec["folder"] / "runs.csv"
        if not path.exists():
            raise SystemExit(f"Missing input file: {path}")
        rows = read_csv(path)
        if not rows:
            raise SystemExit(f"Empty input file: {path}")
        required = {"variant", "run.num_sensors", "run.seed"}
        missing = required - set(rows[0])
        if missing:
            raise SystemExit(f"{path}: missing required columns {sorted(missing)}")

        by_variant = defaultdict(dict)
        for r in rows:
            variant = r["variant"]
            key = (str(r["run.num_sensors"]), str(r["run.seed"]))
            if key in by_variant[variant]:
                raise SystemExit(f"Duplicate cell in {path}: variant={variant}, key={key}")
            by_variant[variant][key] = r

        expected_variants = set(v for pair in spec["comparisons"] for v in pair)
        absent = expected_variants - set(by_variant)
        if absent:
            raise SystemExit(f"{path}: missing variants {sorted(absent)}; found {sorted(by_variant)}")

        sizes = sorted({int(r["run.num_sensors"]) for r in rows})
        # Descriptive summaries
        for variant in sorted(by_variant):
            for size in sizes:
                subset = [r for (n, _), r in by_variant[variant].items() if int(n) == size]
                for metric in spec["metrics"]:
                    vals = [number(r.get(metric)) for r in subset]
                    vals = [v for v in vals if v is not None]
                    if not vals:
                        continue
                    summary_rows.append({
                        "experiment": exp_name, "num_sensors": size, "variant": variant,
                        "metric": metric, "n": len(vals), "mean": float(np.mean(vals)),
                        "sd": float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0,
                        "median": float(np.median(vals)),
                    })

        # Paired tests per size and per pre-declared comparison
        family_indices = []
        for size in sizes:
            for treatment_name, control_name in spec["comparisons"]:
                treatment_map = {seed: row for (n, seed), row in by_variant[treatment_name].items() if int(n) == size}
                control_map = {seed: row for (n, seed), row in by_variant[control_name].items() if int(n) == size}
                common = sorted(set(treatment_map) & set(control_map), key=lambda x: int(x))
                if len(common) != args.expected_seeds:
                    raise SystemExit(
                        f"Pair count mismatch: {exp_name}, N={size}, {treatment_name} vs {control_name}: "
                        f"{len(common)} pairs (expected {args.expected_seeds}); "
                        f"treatment={len(treatment_map)}, control={len(control_map)}"
                    )
                for metric in spec["metrics"]:
                    treatment_vals, control_vals = [], []
                    for seed in common:
                        a = number(treatment_map[seed].get(metric))
                        b = number(control_map[seed].get(metric))
                        if a is not None and b is not None:
                            treatment_vals.append(a)
                            control_vals.append(b)
                    if len(treatment_vals) < 2:
                        continue
                    result = paired_stats(treatment_vals, control_vals)
                    row = {
                        "experiment": exp_name, "num_sensors": size,
                        "comparison": f"{treatment_name} - {control_name}",
                        "treatment": treatment_name, "control": control_name,
                        "metric": metric, **result, "holm_wilcoxon_p": None,
                        "significant_holm_0_05": None,
                    }
                    stat_rows.append(row)
                    family_indices.append(len(stat_rows) - 1)

        # Correct all Wilcoxon tests together within each experiment x network-size family.
        for size in sizes:
            idxs = [i for i, r in enumerate(stat_rows) if r["experiment"] == exp_name and r["num_sensors"] == size]
            adjusted = holm_adjust([float(stat_rows[i]["wilcoxon_p"]) for i in idxs])
            for i, adj in zip(idxs, adjusted):
                stat_rows[i]["holm_wilcoxon_p"] = adj
                stat_rows[i]["significant_holm_0_05"] = bool(adj < 0.05)

        for metric in spec["plot_metrics"]:
            for treatment_name, control_name in spec["comparisons"]:
                for size in sizes:
                    match = next((r for r in stat_rows if r["experiment"] == exp_name and r["num_sensors"] == size
                                  and r["treatment"] == treatment_name and r["control"] == control_name and r["metric"] == metric), None)
                    if match:
                        plot_payload[(exp_name, metric)].append(match)

    summary_fields = ["experiment", "num_sensors", "variant", "metric", "n", "mean", "sd", "median"]
    stat_fields = ["experiment", "num_sensors", "comparison", "treatment", "control", "metric", "n_pairs",
                   "treatment_mean", "control_mean", "mean_difference_treatment_minus_control",
                   "sd_paired_difference", "ci95_low", "ci95_high", "paired_t_p", "wilcoxon_p",
                   "holm_wilcoxon_p", "significant_holm_0_05", "cohen_dz"]
    write_csv(out / "variant_summary_by_size.csv", summary_rows, summary_fields)
    write_csv(out / "paired_statistics.csv", stat_rows, stat_fields)

    # One standalone effect plot per selected metric. Values are treatment minus control.
    plots_dir = out / "figures"
    plots_dir.mkdir(parents=True, exist_ok=True)
    for (exp_name, metric), records in plot_payload.items():
        fig, ax = plt.subplots(figsize=(8.5, 4.8))
        comparisons = list(dict.fromkeys(r["comparison"] for r in records))
        sizes = sorted({int(r["num_sensors"]) for r in records})
        offsets = np.linspace(-0.12, 0.12, max(1, len(comparisons)))
        for offset, comp in zip(offsets, comparisons):
            subset = sorted([r for r in records if r["comparison"] == comp], key=lambda r: int(r["num_sensors"]))
            xs = [sizes.index(int(r["num_sensors"])) + offset for r in subset]
            ys = [float(r["mean_difference_treatment_minus_control"]) for r in subset]
            lows = [float(r["ci95_low"]) for r in subset]
            highs = [float(r["ci95_high"]) for r in subset]
            errs = [[y - lo for y, lo in zip(ys, lows)], [hi - y for y, hi in zip(ys, highs)]]
            ax.errorbar(xs, ys, yerr=errs, marker="o", capsize=4, linewidth=1.5, label=comp)
        ax.axhline(0, linewidth=1, linestyle="--")
        ax.set_xticks(range(len(sizes)), [str(s) for s in sizes])
        ax.set_xlabel("Number of sensors")
        ax.set_ylabel("Mean paired difference (treatment − control)")
        ax.set_title(f"{exp_name}: {metric}")
        ax.grid(True, axis="y", alpha=0.25)
        if len(comparisons) > 1:
            ax.legend(fontsize=8)
        fig.tight_layout()
        safe_metric = metric.replace(".", "_")
        fig.savefig(plots_dir / f"{exp_name}_{safe_metric}.png", dpi=180)
        plt.close(fig)

    # Human-readable results summary; statistical claims use Holm-adjusted Wilcoxon p-values.
    md = [
        "# Phase 4 matched ablation analysis",
        "",
        "Pairing key: network size (`run.num_sensors`) and seed (`run.seed`).",
        "All effects are treatment minus control. Positive/negative direction must be interpreted per metric.",
        "Paired 95% t confidence intervals are reported; Wilcoxon signed-rank p-values are Holm-adjusted",
        "within each experiment × network-size family across the listed metrics/comparisons.",
        "",
        "## Significant paired differences (Holm-adjusted p < 0.05)",
        "",
    ]
    sig = [r for r in stat_rows if r["significant_holm_0_05"]]
    if not sig:
        md.append("No listed metric reached the 0.05 threshold after Holm correction.")
    else:
        md.append("| Experiment | N | Comparison (treatment − control) | Metric | Mean difference | 95% CI | Holm p |")
        md.append("|---|---:|---|---|---:|---:|---:|")
        for r in sorted(sig, key=lambda x: (x["experiment"], x["num_sensors"], x["metric"])):
            md.append(
                f"| {r['experiment']} | {r['num_sensors']} | {r['comparison']} | {r['metric']} | "
                f"{r['mean_difference_treatment_minus_control']:.5g} | "
                f"[{r['ci95_low']:.5g}, {r['ci95_high']:.5g}] | {r['holm_wilcoxon_p']:.4g} |"
            )
    md += ["", "## Files", "", "- `variant_summary_by_size.csv`: descriptive mean, SD, and median by variant and sensor size.",
           "- `paired_statistics.csv`: paired effects, confidence intervals, paired t-tests, Wilcoxon tests, and Holm correction.",
           "- `figures/`: paired effect plots for selected metrics.", ""]
    (out / "ablation_report.md").write_text("\n".join(md), encoding="utf-8")

    print(f"Analysis complete. {len(summary_rows)} descriptive rows, {len(stat_rows)} paired tests.")
    print(f"Output: {out}")
    print(f"Holm-significant paired tests: {len(sig)}")
    print(f"Figures: {len(list(plots_dir.glob('*.png')))}")


if __name__ == "__main__":
    main()
