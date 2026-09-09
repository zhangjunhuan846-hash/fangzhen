"""
Plot a cost landscape for the specific 1C-discharge capacity and compare
disharge profiles simulated with validated and optimised parameter sets.

Make sure to update the generalised parameter set with the diffusivity
scaling returned by figure_5.py.
"""

import matplotlib.pyplot as plt
import numpy as np
import os
import pickle
import pybamm
import pybop
import scienceplots


plt.style.use('science')


# Locate cell folder and import parameter values
folder = os.path.dirname(os.path.realpath(__file__))
with open(os.path.join(folder, "design_results", "parameters_after_D1p.pickle"), 'rb') as param_file:
    param = pickle.load(param_file)

options = {
    "working electrode": "positive",
    "surface form": "differential",
    "contact resistance": "true",
}

# Create a discharge experiment
experiment = pybamm.Experiment(["Discharge at 1C for 1 hour or until 2.5 V", "Rest for 30 minutes"])

# Define optimisation parameters
parameters = pybop.Parameters(
    pybop.Parameter(
        "Nominal cell capacity [A.h]",
        initial_value=0.003,
        bounds=[0, 0.0075],
    )
)


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

def set_up_optimisation(param, parameters, optimiser, max_iter):
    model = set_model(param)
    problem = pybop.DesignProblem(model, parameters, experiment, signal=["Current [A]"])
    cost = SpecificCapacity(problem)
    return optimiser(cost, allow_infeasible_solutions=False, max_iterations=max_iter, tol=1e-4)

def make_prediction(param):
    model = set_model(param)
    prediction = model.predict(experiment=experiment)
    dt = prediction["Time [s]"].data[1] - prediction["Time [s]"].data[0]
    Qspec = np.trapz(prediction["Current [A]"].data, dx=dt) / (3600 * model.cell_mass(param))
    return prediction, Qspec


# Optimise nominal capacity for the identified parameter sets
x_2mAh_cm2, x_4mAh_cm2 = [32.5e-6, 0.597], [73e-6, 0.597]
for x in [x_2mAh_cm2, x_4mAh_cm2]:
    param.update(
        {
            "Positive electrode thickness [m]": x[0],
            "Positive electrode active material volume fraction": x[1],
        }
    )
    optim = set_up_optimisation(param, parameters, pybop.SciPyMinimize, 250)
    results = optim.run()
    x.extend(results.x)

# Unpack the optimised parameter values
x_optim = [
    param["Optimised electrode thickness [m]"],
    param["Optimised active material volume fraction"],
    param["Optimised nominal capacity [A.h]"],
]

# Create a contour plot
X, Y = np.meshgrid(np.linspace(25, 75, 11), np.linspace(0.5, 0.85, 8))
Z = np.zeros_like(X)
for idx, _ in np.ndenumerate(X):
    print("Optimising index", idx)
    param.update(
        {
            "Positive electrode thickness [m]": X[idx] * 1e-6,
            "Positive electrode active material volume fraction": Y[idx],
        }
    )
    optim = set_up_optimisation(param, parameters, pybop.SciPyMinimize, 250)
    try:
        results2 = optim.run()
        param.update(parameters.as_dict(results2.x))
        prediction, Qspec = make_prediction(param)
        Z[idx] = Qspec
    except:
        Z[idx] = np.nan
print(Z)
figc, axc = plt.subplots(1,1)
contours = axc.contourf(X, Y, Z)
axc.set_xlabel("Electrode thickness ($\mu$m)")
axc.set_ylabel("Active material volume fraction")
axc.set_xlim(25, 75)
axc.set_ylim(0.5, 0.85)
figc.colorbar(contours)
plt.figtext(0.94, 0.5, "Specific capacity (mA\,h\,g$^{-1}$)", verticalalignment='center', rotation=270)

# Plot the timeseries output
figt, axt = plt.subplots(1, 1)
for x, label in zip([x_2mAh_cm2, x_4mAh_cm2, x_optim], ["2\,mA\,h\,cm$^{-2}$", "4\,mA\,h\,cm$^{-2}$", "Optimised"]):
    param.update(
        {
            "Positive electrode thickness [m]": x[0],
            "Positive electrode active material volume fraction": x[1],
            "Nominal cell capacity [A.h]": x[2],
        }
    )
    prediction, Qspec = make_prediction(param)
    axt.plot(prediction["Time [s]"].data, prediction["Voltage [V]"].data, label=label)
    print("Specific capacity [mA.h.g-1]:", Qspec)
    axc.scatter(x[0] * 1e6, x[1], s=16, c='w', marker=('x' if label=="Optimised" else 'p'))
axt.set_ylabel("Voltage (V)")
axt.set_xlabel("Time (s)")
axt.legend()

save_path = os.path.join(folder, "design_results", "specific_capacity.pdf")
figc.savefig(save_path)
print("Plot saved at", save_path)

save_path = os.path.join(folder, "design_results", "specific_discharge.pdf")
figt.savefig(save_path)
print("Plot saved at", save_path)

# plt.show()
