"""
Performs design optimisation on the generalised parameter set with
the target of maximising the areal fixed-rate discharge energy.

Make sure to use the generalised parameter set returned by figure_D0_prep.py.
"""

import matplotlib.pyplot as plt
import numpy as np
import os
import pickle
import pybamm
import pybop
import scienceplots

from scipy.optimize import minimize


plt.style.use('science')


# Locate cell folder and import parameter values
folder = os.path.dirname(os.path.realpath(__file__))
with open(os.path.join(folder, "design_results", "parameters_after_D0p.pickle"), 'rb') as param_file:
    param = pickle.load(param_file)

"""
Set up and perform the electrode optimisation.
"""
options = {
    "working electrode": "positive",
    "surface form": "differential",
    "contact resistance": "true",
}
param.set_initial_stoichiometry_half_cell("4.2V", options=options)

# Choose the optimisation parameters
parameters = pybop.Parameters(
    pybop.Parameter(
        "Positive electrode active material volume fraction",
        initial_value=0.7,
        bounds=[0.5, 0.85],
    ),
)

# Create a discharge experiment
experiment = pybamm.Experiment(["Discharge at 5 mA for 30 minutes or until 2.5 V", "Rest for 30 minutes"])


def set_model(param):
    param.set_initial_stoichiometry_half_cell("4.2V", options=options)
    return pybop.lithium_ion.DFN(
        parameter_set=param,
        options=options,
        solver=pybamm.CasadiSolver(
            extrap_tol=-0.03,
            dt_max=300,
            max_step_decrease_count=1,
            return_solution_if_failed_early=True,
            extra_options_setup={"max_num_steps": 3000},
        )
    )

class ArealEnergy(pybop.DesignCost):
    """
    Calculates the areal energy of a battery cell, when applied to a normalised
    discharge from upper to lower voltage limits. The goal of maximising the areal
    energy is achieved with self.minimising=False.

    The areal energy [W.h.m-2] is calculated as

    .. math::
        \\frac{1}{3600 A} \\int_{t=0}^{t=T} I(t)V(t) \\mathrm{d}t

    where A is the electrode area, t is the time, T is the total time, I is the
    current and V is the voltage. The factor of 3600 is included to convert from
    seconds to hours.
    """

    def compute(self, y, dy=None):
        if not any(np.isfinite(y[signal][0]) for signal in self.signal):
            return -np.inf

        dt = y["Time [s]"][1] - y["Time [s]"][0]
        areal_energy = np.trapz(y["Current [A]"] * y["Voltage [V]"], dx=dt) / (
            3600
            * self.problem.model._parameter_set["Electrode width [m]"]
            * self.problem.model._parameter_set["Electrode height [m]"]
        )

        return areal_energy


def set_up_optimisation(param, parameters, optimiser, max_iter):
    model = set_model(param)
    problem = pybop.DesignProblem(model, parameters, experiment)
    cost = ArealEnergy(problem)
    return optimiser(cost, allow_infeasible_solutions=False, max_iterations=max_iter)

# Optimise the areal capacity for a range of thicknesses
optim_p = []
d_range = [30e-6, 40e-6, 50e-6, 60e-6, 70e-6]
for d in d_range:
    param.update({"Positive electrode thickness [m]": d})
    optim = set_up_optimisation(param, parameters, pybop.SciPyMinimize, 250)
    results = optim.run()
    print(results)
    optim_p.append(results.x[0])

# Update and save the parameters using the new data
param.update(
    {
        "Optimised electrode thickness [m]": d_range,
        "Optimised active material volume fraction": optim_p,
    },
    check_already_exists=False,
)
with open(os.path.join(folder, "design_results", "parameters_after_D3p.pickle"), 'wb') as param_file:
    pickle.dump(param, param_file)
