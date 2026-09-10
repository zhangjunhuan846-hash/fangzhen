"""Probe: parameter-set registration format + geometry keys to override."""
import pybamm

entry = pybamm.parameter_sets["Chen2020"]
print("parameter_sets entry type:", type(entry).__name__)
print("entry:", entry)
print()
entry2 = pybamm.parameter_sets["Ecker2015_graphite_halfcell"]
print("Ecker entry:", entry2)
print()
ps = pybamm.ParameterValues("Ecker2015_graphite_halfcell")
for k in ps.keys():
    if any(s in k for s in ("Electrode height", "Electrode width",
                            "Positive electrode thickness",
                            "Positive electrode porosity",
                            "Positive electrode active material volume fraction",
                            "Positive electrode density",
                            "Maximum concentration in positive",
                            "Positive particle radius",
                            "Nominal cell capacity",
                            "Positive electrode OCP",
                            "Positive particle diffusivity",
                            "Positive electrode exchange-current",
                            "Initial concentration in positive",
                            "Lower voltage", "Upper voltage",
                            "Electrode area")):
        v = ps[k]
        print(f"  {k} = {'<callable>' if callable(v) else v}")
