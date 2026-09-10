# external/pybamm-input-data

Vendored **PyBaMM input-data tables** used by platform readers that must
NOT import PyBaMM (dataset adapters are pure data-I/O by design).

| file | origin | purpose |
|---|---|---|
| `graphite_ocp_Ecker2015.csv` | PyBaMM 26.8.0.0, `pybamm/input/parameters/lithium_ion/data/graphite_ocp_Ecker2015.csv` (BSD-3-Clause) | graphite OCP(stoichiometry) table — the SAME table PyBaMM's `Ecker2015_graphite_halfcell` set interpolates. Used by the SINTEF graphite adapter for **inverse-OCP initialisation** (measured rest OCV -> initial Li fraction x0) |

Vendoring (rather than reading `site-packages/`) keeps a **stable, auditable
path** and pins the table version: a PyBaMM upgrade cannot silently change
how the initial state is derived.

`graphite_ocp_Ecker2015.csv` facts (verified):
- no header; columns = (stoichiometry, voltage [V])
- voltage direction: sto = 0 -> 1.4325 V (delithiated); sto = 1 -> 0.0706 V (lithiated)
- 41 rows, sha256 `427504eabeae9b0cb0417932c93d1d733c743945fbc4f54f43dbcfb0abf04185`

Wording: this table is a **published reference parameterisation**, not a
measurement of any specific user cell.
