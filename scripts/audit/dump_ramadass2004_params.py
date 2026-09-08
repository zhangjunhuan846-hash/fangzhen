# One-off dump of Ramadass2004 parameter values for the Step-16
# parameter audit table (docs/v02_calce_parameter_audit.md).
import pybamm

p = pybamm.ParameterValues("Ramadass2004")

keys = [
    # cell / geometry
    "Nominal cell capacity [A.h]",
    "Number of electrodes connected in parallel to make a cell",
    "Number of electrodes connected in series to make a cell",
    "Negative electrode thickness [m]",
    "Positive electrode thickness [m]",
    "Separator thickness [m]",
    "Electrode height [m]",
    "Electrode width [m]",
    # chemistry / stoichiometry
    "Maximum concentration in negative electrode [mol.m-3]",
    "Maximum concentration in positive electrode [mol.m-3]",
    # particle
    "Negative particle radius [m]",
    "Positive particle radius [m]",
    "Negative electrode diffusivity [m2.s-1]",
    "Positive electrode diffusivity [m2.s-1]",
    # reaction rates
    "Negative electrode exchange-current density [A.m-2]",
    "Positive electrode exchange-current density [A.m-2]",
    # porosity / tortuosity
    "Negative electrode porosity",
    "Positive electrode porosity",
    "Separator porosity",
    "Negative electrode Bruggeman coefficient (electrolyte)",
    "Positive electrode Bruggeman coefficient (electrolyte)",
    # electrolyte
    "Electrolyte diffusivity [m2.s-1]",
    "Electrolyte conductivity [S.m-1]",
    # voltages
    "Lower voltage cut-off [V]",
    "Upper voltage cut-off [V]",
    "Negative electrode OCP [V]",
    "Positive electrode OCP [V]",
    # thermal
    "Negative electrode specific heat capacity [J.kg-1.K-1]",
    "Positive electrode specific heat capacity [J.kg-1.K-1]",
    "Negative current collector thickness [m]",
    "Positive current collector thickness [m]",
]

for k in keys:
    try:
        v = p[k]
    except Exception as e:
        v = f"<{type(e).__name__}>"
    if callable(v):
        v = "<function>"
    print(f"{k} = {v}")

print()
print("citations / description:")
try:
    print(p.print_citations())
except Exception as e:
    print("(no citations printed)", e)
