"""
Plot a cost landscape for the areal fixed-rate discharge energy and compare
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
with open(os.path.join(folder, "design_results", "parameters_after_D3p.pickle"), 'rb') as param_file:
    param = pickle.load(param_file)

options = {
    "working electrode": "positive",
    "surface form": "differential",
    "contact resistance": "true",
}

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

def make_prediction(param):
    model = set_model(param)
    prediction = model.predict(experiment=experiment)
    dt = prediction["Time [s]"].data[1] - prediction["Time [s]"].data[0]
    Qarea = np.trapz(prediction["Current [A]"].data * prediction["Voltage [V]"].data, dx=dt) / (
        3600 * param["Electrode width [m]"]* param["Electrode height [m]"]
    )
    return prediction, Qarea


# Unpack the optimised parameter values
x_optim = []
for i in range(len(param["Optimised electrode thickness [m]"])):
    x_optim.append(
        [
            param["Optimised electrode thickness [m]"][i],
            param["Optimised active material volume fraction"][i],
        ]
    )
x_2mAh_cm2, x_4mAh_cm2 = [32.5e-6, 0.597], [73e-6, 0.597]

# Create a contour plot
X, Y = np.meshgrid(np.linspace(25, 75, 11), np.linspace(0.5, 0.85, 8))
Z = np.zeros_like(X)
for idx, _ in np.ndenumerate(X):
    param.update(
        {
            "Positive electrode thickness [m]": X[idx] * 1e-6,
            "Positive electrode active material volume fraction": Y[idx],
        }
    )
    try:
        prediction, Qarea = make_prediction(param)
        Z[idx] = Qarea
    except:
        Z[idx] = np.nan
print(Z)
figc, axc = plt.subplots(1,1)
contours = axc.contourf(X, Y, Z / 10)
axc.set_xlabel("Electrode thickness ($\mu$m)")
axc.set_ylabel("Active material volume fraction")
axc.set_xlim(25, 75)
axc.set_ylim(0.5, 0.85)
figc.colorbar(contours)
plt.figtext(0.94, 0.5, "Areal energy (mW\,h\,cm$^{-2}$)", verticalalignment='center', rotation=270)
axc.plot([x[0] * 1e6 for x in x_optim], [x[1] for x in x_optim], c='w', marker='x', markersize=4)

# Plot the timeseries output
figt, axt = plt.subplots(1, 1)
Q_line = []
for x, label in zip([x_2mAh_cm2, x_4mAh_cm2, x_optim[-1]], ["2\,mA\,h\,cm$^{-2}$", "4\,mA\,h\,cm$^{-2}$", "Optimised"]):
    param.update(
        {
            "Positive electrode thickness [m]": x[0],
            "Positive electrode active material volume fraction": x[1],
        }
    )
    prediction, Qarea = make_prediction(param)
    axt.plot(prediction["Time [s]"].data, prediction["Voltage [V]"].data, label=label)
    print("Areal energy [mW.h.cm-2]:", Qarea / 10)
    if label != "Optimised":
        axc.scatter(x[0] * 1e6, x[1], s=16, c='w', marker=('p'))  
axt.set_ylabel("Voltage (V)")
axt.set_xlabel("Time (s)")
axt.legend()

save_path = os.path.join(folder, "design_results", "fixed_areal_energy.pdf")
figc.savefig(save_path)
print("Plot saved at", save_path)

save_path = os.path.join(folder, "design_results", "fixed_areal_discharge.pdf")
figt.savefig(save_path)
print("Plot saved at", save_path)

# plt.show()
