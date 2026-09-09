"""
Prepare the parameter set for design optimisation.

Make sure to update the generalised parameter set with the diffusivity
scaling returned by figure_6.py.
"""

import numpy as np
import os
import pickle
import pybamm
import pybop
import scienceplots

from scipy.optimize import minimize


"""
Average and interpolate the cell parameters.
"""
# Locate cell folder
folder = os.path.dirname(os.path.realpath(__file__))

# Load parameter values
with open(os.path.join(folder, "2mAh_cm2", "results", "parameters_after_6.pickle"), 'rb') as param_file:
    param_2mAh_cm2 = pickle.load(param_file)
with open(os.path.join(folder, "4mAh_cm2", "results", "parameters_after_6.pickle"), 'rb') as param_file:
    param_4mAh_cm2 = pickle.load(param_file)

# Base the generalised parameter set on the 2mAh_cm2 cell
param = param_2mAh_cm2

# Update some parameters using the average value
for key in [
    "Positive electrode conductivity [S.m-1]",
    "Positive electrode reaction activation energy [J.mol-1]",
]:
    param[key] = (param_2mAh_cm2[key] + param_4mAh_cm2[key]) / 2

# Fit one or two-parameter functions to other parameters
d = np.asarray([32.5e-6, 73e-6])

key = "Contact resistance [Ohm]"
data = [param_2mAh_cm2[key], param_4mAh_cm2[key]]
r1 = (d[1] * data[0] - d[0] * data[1]) / (d[1] - d[0])
r2 = (data[0] - r1) / d[0]

key = "Positive electrode Bruggeman coefficient (electrolyte)"
data = [param_2mAh_cm2[key], param_4mAh_cm2[key]]
b1 = (d[1] * data[0] - d[0] * data[1]) / (d[1] - d[0])
b2 = (data[0] - b1) / d[0]

key = "Positive electrode double-layer capacity [F.m-2]"
data = [param_2mAh_cm2[key], param_4mAh_cm2[key]]
def absolute_relative_error(values):
    return np.sum(np.abs((values[0] / d - data) / data))
c1 = minimize(absolute_relative_error, [np.mean(data * d)]).x[0]

key = "Positive electrode reaction rate [A.m-2.(m3.mol-1)^1.5]"
data = [param_2mAh_cm2[key], param_4mAh_cm2[key]]
def absolute_relative_error(values):
    return np.sum(np.abs((values[0] / d - data) / data))
k1 = minimize(absolute_relative_error, [np.mean(data * d)]).x[0]

key = "Positive electrode diffusivity scaling factor"
data = [param_2mAh_cm2[key], param_4mAh_cm2[key]]
def absolute_relative_error(values):
    return np.sum(np.abs((1 + (values[0] / d)**2 - data) / data))
a1 = minimize(absolute_relative_error, [np.mean(data )]).x[0]

# Update parameters that are a function of the optimisation parameters
d = pybamm.Parameter("Positive electrode thickness [m]")
param.update(
    {
        "Contact resistance [Ohm]": r1 + r2 * d,
        "Positive electrode Bruggeman coefficient (electrolyte)": b1 + b2 * d,
        "Positive electrode double-layer capacity [F.m-2]": c1 / d,
        "Positive electrode reaction rate [A.m-2.(m3.mol-1)^1.5]": k1 / d,
        "Positive electrode diffusivity scaling factor": 1 + (a1 / d)**2,
        "Positive electrode porosity": (1
            - 0.075
            - pybamm.Parameter("Positive electrode active material volume fraction")
        ),
    }
)

options = {
    "working electrode": "positive",
    "surface form": "differential",
    "contact resistance": "true",
}
param.set_initial_stoichiometry_half_cell("4.2V", options=options)

with open(os.path.join(folder, "design_results", "parameters_after_D0p.pickle"), 'wb') as param_file:
    pickle.dump(param, param_file)

print(param)
print(r1, r2, a1, b1, b2, c1, k1)
