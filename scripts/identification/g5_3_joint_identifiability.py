#!/usr/bin/env python
"""G5.3 -- joint D_s / R_p identifiability geometry under model mismatch.

    python scripts/identification/g5_3_joint_identifiability.py [--quick]

The question is NOT "can two parameters be recovered".  It is:

    if R_p is also freed, is the model mismatch RESOLVED, or merely HIDDEN
    behind one more parameter?

And underneath that, the geometric question: what does the voltage curve
actually constrain?  A single curve can pin down a diffusion TIME SCALE
without pinning D_s and R_p separately, because

    tau_d = R_p^2 / D_s        =>   2*z_R - z_D = const   along iso-tau_d

So the shape of the cost valley is the measurement, not the location of its
minimum.  A long ridge along 2*z_R - z_D means the data see tau_d; a compact
bowl means they see the pair.

Layers:

  CONTROL    SPM  truth -> SPM  inverse : 2-D cost map, valley geometry,
             and whether the valley is along iso-tau_d
  MISMATCH   SPMe truth -> SPM  inverse : J_min(D_s)  vs  J_min(D_s, R_p)

The mismatch comparison can come out three ways, and the third is the one to
watch for:

  A  residual drops a lot, D_s/R_p move far    -> parameters absorb the error
  B  residual barely drops                     -> the missing physics is not
                                                  absorbable by these two
  C  many (D_s,R_p) pairs fit the same         -> structural non-identifiability
                                                  AND mismatch at once

Also supplies the evidence G5.2 flagged as missing: whether the objective is
actually FLAT in D_s at high rate (`leverage collapse`), via a profile of
J(z_D +/- dx) rather than an inference from the residual floor.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from identification.forward import (  # noqa: E402
    DS_KEY,
    R_NAME,
    RP_KEY,
    Z_NAME,
    ReplayCase,
    build_problem,
)
from identification.recovery import recover_from  # noqa: E402
from identification.synthetic import generate  # noqa: E402

DATASET, CELL = "chen2020", "02"
INVERSE = "SPM"
DS_TRUE = 2.0e-15
RP_TRUE = 5.22e-06
ZD_TRUE = math.log10(DS_TRUE)
ZR_TRUE = math.log10(RP_TRUE)

#: The two rates that carry the most information, per the G5.2 result:
#: 0.1C is where the mismatch is almost invisible, 0.5C where it is moderate.
RATES = ("C10", "C2")

Z_BOUNDS = (-16.0, -13.0)
R_BOUNDS = (math.log10(1.0e-6), math.log10(2.0e-5))   # 1 um .. 20 um
Z_INITS = (1.0e-15, 4.0e-15, 1.0e-14)


def _case(rate, model):
    return ReplayCase(dataset_id=DATASET, cell=CELL, rate=rate,
                      model_name=model).resolve()


def _cost(problem, zd, zr=None):
    inputs = {Z_NAME: float(zd)}
    if zr is not None:
        inputs[R_NAME] = float(zr)
    ev = problem.evaluate(inputs)
    return float(np.ravel(np.asarray(ev.values, dtype=float))[0])


# ----------------------------------------------------------------------
def cost_map(observation, runs, audit, rate, replay_case,
             n=15, half=0.35, refine=True, refine_n=15):
    """2-D J(z_D, z_R) on a grid, with one refinement pass around the argmin."""
    problem, sim = build_problem(
        observation, output_root=runs, audit_dir=audit / f"map_{rate}",
        replay_case=replay_case,
        params={
            Z_NAME: (ZD_TRUE, Z_BOUNDS),
            R_NAME: (ZR_TRUE, R_BOUNDS),
        },
    )

    def grid(zd0, zr0, span, m):
        zds = np.linspace(zd0 - span, zd0 + span, m)
        zrs = np.linspace(zr0 - span, zr0 + span, m)
        J = np.full((m, m), np.nan)
        for i, zr in enumerate(zrs):
            for j, zd in enumerate(zds):
                J[i, j] = _cost(problem, zd, zr)
        return zds, zrs, J

    zds, zrs, J = grid(ZD_TRUE, ZR_TRUE, half, n)
    i, j = np.unravel_index(int(np.nanargmin(J)), J.shape)
    zd_best, zr_best = float(zds[j]), float(zrs[i])

    if refine:
        step = 2 * half / (n - 1)
        zds2, zrs2, J2 = grid(zd_best, zr_best, 1.5 * step, refine_n)
        i2, j2 = np.unravel_index(int(np.nanargmin(J2)), J2.shape)
        zd_best, zr_best = float(zds2[j2]), float(zrs2[i2])
        zds, zrs, J = zds2, zrs2, J2
        resolution = (2 * 1.5 * step) / (refine_n - 1)
    else:
        resolution = 2 * half / (n - 1)

    return {
        "rate": rate,
        "z_D": [float(x) for x in zds],
        "z_R": [float(x) for x in zrs],
        "cost": [[float(v) for v in row] for row in J],
        "z_D_argmin": zd_best,
        "z_R_argmin": zr_best,
        "ds_argmin": float(10.0 ** zd_best),
        "rp_argmin": float(10.0 ** zr_best),
        "cost_min": float(np.nanmin(J)),
        "resolution_dex": float(resolution),
        "n_evaluations": len(sim.records),
        "audit_dir": str(audit / f"map_{rate}"),
    }


def valley_geometry(m):
    """Elongation and principal direction of the low-cost region.

    Reported so that "is the valley along iso-tau_d?" is a MEASUREMENT rather
    than an impression from a plot.  The iso-tau_d direction is
    (dz_D, dz_R) = (2, 1)/sqrt(5); the angle between the fitted direction and
    that one is the answer.
    """
    J = np.array(m["cost"], dtype=float)
    zds = np.array(m["z_D"], dtype=float)
    zrs = np.array(m["z_R"], dtype=float)
    Jmin = float(np.nanmin(J))
    finite = np.isfinite(J)
    if not finite.any():
        return {"ok": False, "reason": "no finite cost"}

    span = float(np.nanmax(J[finite]) - Jmin)
    for frac in (0.05, 0.10, 0.25):
        mask = finite & (J <= Jmin + frac * span)
        if mask.sum() >= 6:
            break
    pts = np.column_stack([np.meshgrid(zds, zrs)[0][mask],
                           np.meshgrid(zds, zrs)[1][mask]])
    if len(pts) < 3:
        return {"ok": False, "reason": f"sub-level set too small ({len(pts)})"}

    mu = pts.mean(axis=0)
    cov = np.cov(pts.T)
    w, v = np.linalg.eigh(cov)
    order = np.argsort(w)[::-1]
    w, v = w[order], v[:, order]
    major = v[:, 0]
    # orient so that the direction has positive z_R component
    if major[1] < 0:
        major = -major
    iso = np.array([2.0, 1.0]) / math.sqrt(5.0)     # iso-tau_d direction
    cosang = float(np.clip(abs(np.dot(major, iso)), -1.0, 1.0))
    angle = math.degrees(math.acos(cosang))
    elong = float(math.sqrt(w[0] / w[1])) if w[1] > 0 else float("inf")
    return {
        "ok": True,
        "n_points_in_sublevel": int(mask.sum()),
        "level_fraction_of_span": float(frac),
        "elongation": elong,
        "major_axis": [float(major[0]), float(major[1])],
        "iso_tau_d_axis": [float(iso[0]), float(iso[1])],
        "angle_to_iso_tau_d_deg": float(angle),
        # A small angle is NOT sufficient to call this a ridge: a round bowl
        # has no preferred direction, so its fitted axis can point anywhere.
        # The angle only means something if the sub-level set is actually
        # elongated, hence the elongation condition.
        "verdict": (
            "ridge ALONG iso-tau_d" if (elong >= 3.0 and angle <= 20)
            else "elongated but OFF iso-tau_d" if elong >= 3.0
            else "near-isotropic (no ridge; angle is not interpretable)"
        ),
    }


def profile(problem, name, centre, deltas, other=None):
    """J along one axis -- the direct test for leverage collapse."""
    out = []
    for d in deltas:
        inputs = {name: float(centre + d)}
        if other:
            inputs.update(other)
        ev = problem.evaluate(inputs)
        out.append({"delta": float(d),
                    "cost": float(np.ravel(np.asarray(ev.values, dtype=float))[0])})
    base = out[len(out) // 2]["cost"] if out else float("nan")
    for row in out:
        row["relative_to_centre"] = (
            row["cost"] / base if base and np.isfinite(base) else None
        )
    return {"centre": float(centre), "points": out}


# ----------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default="outputs/fitting/g5.3")
    args = ap.parse_args()

    out = ROOT / args.out
    runs, audit = out / "runs", out / "audit"
    out.mkdir(parents=True, exist_ok=True)
    rates = RATES[:1] if args.quick else RATES
    n_map = 7 if args.quick else 15
    maxiter = 80 if args.quick else 400

    tic = time.perf_counter()
    log = print
    log("=" * 80)
    log("G5.3  joint D_s / R_p identifiability geometry")
    log("=" * 80)
    log(f"  inverse model : {INVERSE}      rates: {', '.join(rates)}")
    log(f"  z_D = log10(D_s) in {Z_BOUNDS}   z_R = log10(R_p) in "
        f"({R_BOUNDS[0]:.3f}, {R_BOUNDS[1]:.3f})"
        f"  = {10**R_BOUNDS[0]:.2e} .. {10**R_BOUNDS[1]:.2e} m")
    log(f"  truth: D_s={DS_TRUE:.3e} (z_D={ZD_TRUE:+.4f})   "
        f"R_p={RP_TRUE:.3e} (z_R={ZR_TRUE:+.4f})")
    log(f"  iso-tau_d direction: 2*z_R - z_D = const -> (dz_D, dz_R) = "
        f"(2, 1)/sqrt(5)")

    report = {
        "gate": "G5.3",
        "question": ("if R_p is freed too, is the model mismatch resolved or "
                     "merely hidden behind another parameter?"),
        "boundary": ("still synthetic on both sides; the mismatch is in the "
                     "model form"),
        "config": {
            "dataset": DATASET, "cell": CELL, "inverse_model": INVERSE,
            "rates": list(rates), "ds_true": DS_TRUE, "rp_true": RP_TRUE,
            "z_D_true": ZD_TRUE, "z_R_true": ZR_TRUE,
            "z_bounds": list(Z_BOUNDS), "r_bounds": list(R_BOUNDS),
            "map_points": n_map,
        },
        "maps": {}, "mismatch": {}, "profile": {},
    }

    # ================= 1. CONTROL: 2-D geometry, SPM -> SPM ============
    log(f"\n{'=' * 80}")
    log("1. CONTROL  SPM -> SPM  : 2-D cost map (is the valley a bowl or a ridge?)")
    log(f"{'=' * 80}")
    for rate in rates:
        obs = generate(DATASET, CELL, rate, DS_TRUE, runs / "control",
                       model_name="SPM")
        m = cost_map(obs, runs / "control", audit / "control", rate,
                     _case(rate, INVERSE), n=n_map)
        g = valley_geometry(m)
        report["maps"][rate] = {"map": m, "geometry": g}
        log(f"\n  {rate}: argmin z_D={m['z_D_argmin']:+.4f} z_R={m['z_R_argmin']:+.4f}"
            f"   (truth {ZD_TRUE:+.4f}, {ZR_TRUE:+.4f})")
        log(f"        -> D_s={m['ds_argmin']:.5e}  R_p={m['rp_argmin']:.5e}"
            f"   resolution {m['resolution_dex']:.4f} dex"
            f"   {m['n_evaluations']} evals")
        if g["ok"]:
            log(f"        elongation {g['elongation']:.2f}"
                f"   angle to iso-tau_d {g['angle_to_iso_tau_d_deg']:.1f} deg"
                f"   -> {g['verdict']}")
        else:
            log(f"        geometry: {g.get('reason')}")

    # ================= 2. MISMATCH: 1-param vs 2-param =================
    log(f"\n{'=' * 80}")
    log("2. MISMATCH  SPMe -> SPM : J_min(D_s)  vs  J_min(D_s, R_p)")
    log(f"{'=' * 80}")
    for rate in rates:
        obs = generate(DATASET, CELL, rate, DS_TRUE, runs / "mismatch",
                       model_name="SPMe")
        icase = _case(rate, INVERSE)
        n_pts = len(obs.time_s)

        # --- one parameter (as in G5.2) ---
        one = []
        for z0 in (math.log10(z) for z in Z_INITS):
            sr = recover_from(obs, runs / "mismatch",
                              audit / f"mm1_{rate}_z{z0:+.4f}",
                              z_init=float(z0), z_bounds=Z_BOUNDS,
                              method="Nelder-Mead", maxiter=maxiter,
                              replay_case=icase)
            one.append(sr)
        zD1 = float(np.mean([s.z_fit for s in one]))
        J1 = float(min(s.cost_final for s in one))
        rms1 = math.sqrt(J1 / n_pts) * 1000.0 if np.isfinite(J1) else None

        # --- two parameters ---
        # A fresh Problem per initial guess rather than mutating the
        # parameter in place: PyBOP takes the starting point from the
        # parameter at construction time, so mutating afterwards may not
        # actually move the start.
        import pybop

        best = None
        for z0 in (math.log10(z) for z in Z_INITS):
            p2, sim2 = build_problem(
                obs, output_root=runs / "mismatch",
                audit_dir=audit / f"mm2_{rate}_z{z0:+.4f}",
                replay_case=icase,
                params={
                    Z_NAME: (float(z0), Z_BOUNDS),
                    R_NAME: (ZR_TRUE, R_BOUNDS),
                },
            )
            opt = pybop.SciPyMinimize(
                p2, options=pybop.SciPyMinimizeOptions(
                    method="Nelder-Mead", maxiter=int(maxiter)))
            res = opt.run()
            J = float(res.best_cost)
            if best is None or J < best["J"]:
                x = np.atleast_1d(np.asarray(res.x, dtype=float))
                best = {"J": J, "z_D": float(x[0]), "z_R": float(x[1]),
                        "n_evals": int(getattr(res, "n_evaluations", 0) or 0),
                        "message": str(getattr(res, "message", ""))}
            sim2.write_audit(
                Path(audit) / f"mm2_{rate}_z{z0:+.4f}_evaluations.json")

        J2 = best["J"]
        rms2 = math.sqrt(J2 / n_pts) * 1000.0 if np.isfinite(J2) else None
        drop = (1.0 - J2 / J1) if (np.isfinite(J1) and J1 > 0) else None

        entry = {
            "rate": rate, "n_points": int(n_pts),
            "one_param": {
                "z_D": zD1, "ds": float(10.0 ** zD1),
                "bias_vs_truth": float(10.0 ** (zD1 - ZD_TRUE) - 1.0),
                "cost": J1, "fit_rms_mV": rms1,
                "multistart_spread_dex": float(
                    max(s.z_fit for s in one) - min(s.z_fit for s in one)),
            },
            "two_param": {
                "z_D": best["z_D"], "ds": float(10.0 ** best["z_D"]),
                "z_R": best["z_R"], "rp": float(10.0 ** best["z_R"]),
                "bias_D": float(10.0 ** (best["z_D"] - ZD_TRUE) - 1.0),
                "bias_R": float(10.0 ** (best["z_R"] - ZR_TRUE) - 1.0),
                "cost": J2, "fit_rms_mV": rms2,
                "n_evals": best["n_evals"], "message": best["message"],
            },
            "relative_cost_drop": drop,
        }
        report["mismatch"][rate] = entry

        log(f"\n  {rate}   n_points={n_pts}")
        log(f"     J_min(D_s)      cost {J1:.6e}   RMS {rms1:.3f} mV"
            f"   D_s={10**zD1:.5e}  ({(10**(zD1-ZD_TRUE)-1)*100:+.2f} %)")
        log(f"     J_min(D_s,R_p)  cost {J2:.6e}   RMS {rms2:.3f} mV"
            f"   D_s={10**best['z_D']:.5e}  ({(10**(best['z_D']-ZD_TRUE)-1)*100:+.2f} %)"
            f"   R_p={10**best['z_R']:.5e}  ({(10**(best['z_R']-ZR_TRUE)-1)*100:+.2f} %)")
        if drop is not None:
            log(f"     relative cost drop {drop*100:+.3f} %")

    # ================= 3. PROFILE: leverage collapse evidence ==========
    log(f"\n{'=' * 80}")
    log("3. PROFILE  J(z_D +/- dx) -- is the objective FLAT, or just large?")
    log("   (G5.2 inferred 'leverage collapse' at 1.5C from a 92.6 mV floor;")
    log("    a floor alone does NOT prove flatness. This measures it.)")
    log(f"{'=' * 80}")
    deltas = (-0.20, -0.10, -0.05, 0.0, 0.05, 0.10, 0.20)
    for rate, model in (("1p5C", "SPMe"), ("C2", "SPMe"), ("C10", "SPMe")):
        obs = generate(DATASET, CELL, rate, DS_TRUE, runs / "profile",
                       model_name=model)
        pr, _ = build_problem(obs, output_root=runs / "profile",
                              audit_dir=audit / f"prof_{rate}",
                              replay_case=_case(rate, INVERSE),
                              z_initial=ZD_TRUE)
        prof = profile(pr, Z_NAME, ZD_TRUE, deltas)
        report["profile"][rate] = {"truth_model": model, **prof}
        log(f"\n  {rate} ({model} truth -> SPM inverse), profile at z_D truth")
        for row in prof["points"]:
            log(f"     z_D{row['delta']:+.2f}  J={row['cost']:.6e}"
                f"   x{row['relative_to_centre']:.4f} vs centre"
                if row["relative_to_centre"] is not None else "")
        pts = prof["points"]
        finite = [p for p in pts if np.isfinite(p["cost"])]
        if finite:
            pmin = min(finite, key=lambda r: r["cost"])
            # Local curvature measured AT THE PROFILE MINIMUM.  Measuring the
            # rise away from the truth would conflate two different things:
            # under mismatch the truth is not the minimum, so a large rise
            # there says the parameter is biased, NOT that it is sensitive.
            rises = []
            for target in (-0.05, 0.05):
                want = pmin["delta"] + target
                near = [p for p in finite
                        if abs(p["delta"] - want) <= 1e-9 + 1e-6]
                if near and pmin["cost"] > 0:
                    rises.append(near[0]["cost"] / pmin["cost"])
            ratio = min(rises) if rises else None
            verdict = (None if ratio is None
                       else "FLAT (leverage collapsed)" if ratio < 1.5
                       else "STILL SENSITIVE")
            report["profile"][rate].update({
                "profile_min_cost": pmin["cost"],
                "profile_min_at_delta": pmin["delta"],
                "truth_is_the_profile_minimum": bool(abs(pmin["delta"]) < 1e-9),
                "sensitivity_ratio_0p05": (float(ratio) if ratio else None),
                "verdict": verdict,
            })
            if ratio is not None:
                log(f"     profile minimum at z_D{pmin['delta']:+.2f}"
                    f"  (truth is the minimum: "
                    f"{abs(pmin['delta']) < 1e-9})")
                log(f"     J at +/-0.05 dex from that minimum is x{ratio:.3f}"
                    f" -> {verdict}")

    report["runtime_s"] = time.perf_counter() - tic
    (out / "g5_3_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    log(f"\nreport -> {out / 'g5_3_report.json'}")
    log(f"runtime {report['runtime_s']:.1f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
