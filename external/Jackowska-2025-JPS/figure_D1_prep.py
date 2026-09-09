"""
Performs design optimisation on the generalised parameter set with
the target of maximising the specific 1C-discharge capacity.

Make sure to use the generalised parameter set returned by figure_D0_prep.py.
"""

import numpy as np
import os
import pickle
import pybamm
import pybop
import scienceplots

from scipy.optimize import minimize


# Locate cell folder and import parameter values
folder = os.path.dirname(os.path.realpath(__file__))
with open(os.path.join(folder, "design_results", "parameters_after_D0p.pickle"), 'rb') as param_file:
    param = pickle.load(param_file)

# Add a combined weight for the separator, counter electrode and current collectors
param.update(
    {
        "Negative current collector density [kg.m-3]": 2500 / 1.72,
        "Negative current collector thickness [m]": 20e-6,
        "Negative electrode active material density [kg.m-3]": 0,
        "Negative electrode active material volume fraction": 0,
        "Negative electrode carbon-binder density [kg.m-3]": 0,
        "Negative electrode porosity": 0,
        "Positive current collector density [kg.m-3]": 0,
        "Positive current collector thickness [m]": 0,
        "Separator density [kg.m-3]": 0,
    },
    check_already_exists=False,
)

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
        "Positive electrode thickness [m]",
        bounds=[25e-06, 75e-06],
    ),
    pybop.Parameter(
        "Positive electrode active material volume fraction",
        bounds=[0.5, 0.85],
    ),
    pybop.Parameter(
        "Nominal cell capacity [A.h]",
        initial_value=0.003,
        bounds=[0.0025, 0.0075],
    )
)

# Create a discharge experiment
experiment = pybamm.Experiment(["Discharge at 1C for 1 hour or until 2.5 V", "Rest for 30 minutes"])

# Set up a half-cell model *** needs to be SPMe or higher for design optimisation ***
model = pybop.lithium_ion.DFN(
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

# Set up a design problem and cost
problem = pybop.DesignProblem(model, parameters, experiment, signal=["Current [A]"])


class SpecificCapacity(pybop.DesignCost):
    """
    Calculates the specific capacity of a battery cell, when applied to a
    normalised discharge from upper to lower voltage limits. The goal of maximising
    the specific capacity is achieved with self.minimising=False.

    The specific capacity [A.h.kg-1] is calculated as

    .. math::
        \\frac{1}{3.6 m} \\int_{t=0}^{t=T} I(t) \\mathrm{d}t

    where m is the cell mass, t is the time, T is the total time and I is the
    current. The factor of 3600 is included to convert from seconds to hours.
    The value in A.h.kg-1 is equivalent to the value in mA.h.g-1.
    """

    def compute(self, y, dy=None):
        if not any(np.isfinite(y[signal][0]) for signal in self.signal):
            return -np.inf

        dt = y["Time [s]"][1] - y["Time [s]"][0]
        specific_capacity = np.trapz(y["Current [A]"], dx=dt) / (
            3600 * self.problem.model.cell_mass()
        )

        penalty = 5400 - y["Time [s]"][-1]  # seconds under 1C protocol length

        return specific_capacity - penalty


cost = SpecificCapacity(problem)

# Set up and run optimisation
optim = pybop.SciPyDifferentialEvolution(cost, allow_infeasible_solutions=False, max_iterations=25)
results = optim.run()
print(results)

# Update and save the parameters using the new data
param.update(
    {
        "Optimised electrode thickness [m]": results.x[0],
        "Optimised active material volume fraction": results.x[1],
        "Optimised nominal capacity [A.h]": results.x[2],
    },
    check_already_exists=False,
)
with open(os.path.join(folder, "design_results", "parameters_after_D1p.pickle"), 'wb') as param_file:
    pickle.dump(param, param_file)
