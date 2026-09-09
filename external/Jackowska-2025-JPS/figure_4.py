"""
Fits the reaction rate and activation energy from the reference exchange
current density values from EIS at different SOCs and temperatures.
"""

import matplotlib.pyplot as plt
import numpy as np
import os
import pandas as pd
import pickle
import pybamm
import pybop
import scienceplots

from scipy.optimize import curve_fit, minimize


plt.style.use('science')


def j0_function(sto, param):
    c_e_ref = pybamm.Parameter("Initial concentration in electrolyte [mol.m-3]")
    c_s_max = pybamm.Parameter("Maximum concentration in positive electrode [mol.m-3]")
    c_s_surf = sto * c_s_max
    m_ref = pybamm.Parameter("Positive electrode reaction rate [A.m-2.(m3.mol-1)^1.5]")
    alpha = 0.5
    return param.evaluate(m_ref * c_s_surf**alpha * (c_e_ref * (c_s_max - c_s_surf)) ** (1-alpha))


for cell_type, cell_name in zip(["2mAh_cm2", "4mAh_cm2"], ["2mAhcm^2_NCM920305", "4mAhcm^2_NCM920305"]):
    print("\n Cell type:", cell_type)

    # Locate cell folder and import parameter values
    folder = os.path.join(os.path.dirname(os.path.realpath(__file__)), cell_type)
    with open(os.path.join(folder, "results", "parameters_after_3.pickle"), 'rb') as param_file:
        param = pickle.load(param_file)

    options = {
        "working electrode": "positive",
        "surface form": "differential",
        "contact resistance": "true",
    }

    # Define the inverse OCP function
    ocp = pd.read_csv(os.path.join(folder, "results", "ocp_charge.csv"))
    inverse_ocp = pybop.Interpolant(
        ocp["Voltage [V]"].to_numpy(),
        ocp["Stoichiometry"].to_numpy(),
        name="Inverse OCP",
    )

    # Import data
    temperatures = 273.15 + np.asarray([5, 15, 25, 35, 45])

    if cell_type == "2mAh_cm2":
        voltages = np.asarray([3.62, 3.70, 3.85, 4.06, 4.18])
    elif cell_type == "4mAh_cm2":
        voltages = np.asarray([3.62, 3.69, 3.83, 4.02, 4.17])
    sto_values = inverse_ocp(voltages)

    # Set up figure for all temperatures
    fig, ax = plt.subplots(1,1)
    ax.set_xlabel("Stoichiometry")
    ax.set_ylabel("Exchange current density (A\,m$^{-2}$)")

    reaction_rates = []
    for T in temperatures:
        if cell_type == "2mAh_cm2":
            if T == 278.15:
                j0_values = np.asarray([0.053, 0.159, 0.249, 0.201, 0.174])
            elif T == 288.15:
                j0_values = np.asarray([0.077, 0.225, 0.433, 0.376, 0.252])
            elif T == 298.15:
                j0_values = np.asarray([0.108, 0.524, 1.327, 1.120, 0.550])
            elif T == 308.15:
                j0_values = np.asarray([0.136, 0.714, 3.464, 2.938, 1.874])
            elif T == 318.15:
                j0_values = np.asarray([0.187, 1.628, 4.933, 3.773, 3.206])
        elif cell_type == "4mAh_cm2":
            if T == 278.15:
                j0_values = np.asarray([0.037, 0.078, 0.097, 0.120, 0.083])
            elif T == 288.15:
                j0_values = np.asarray([0.056, 0.134, 0.276, 0.231, 0.176])
            elif T == 298.15:
                j0_values = np.asarray([0.070, 0.185, 0.455, 0.365, 0.288])
            elif T == 308.15:
                j0_values = np.asarray([0.084, 0.236, 0.799, 1.055, 0.636])
            elif T == 318.15:
                j0_values = np.asarray([0.126, 0.325, 1.154, 1.594, 1.042])

        # Plot the exchange current density
        ax.scatter(sto_values, j0_values, s=8, label=f"{T}\,K data")

        # Fit the reaction rate to the exchange current density
        def mean_absolute_error(values):
            j0_prediction = []
            param["Positive electrode reaction rate [A.m-2.(m3.mol-1)^1.5]"] = values[0]
            for sto in sto_values:
                j0_prediction.append(j0_function(sto, param))
            error = j0_values - j0_prediction
            return np.mean(np.abs(error))

        x0 = [1e-6]
        scipy_result = minimize(mean_absolute_error, x0)
        k = scipy_result.x[0]
        reaction_rates.append(k)

        # Use optimisation result to plot the fitted function
        param["Positive electrode reaction rate [A.m-2.(m3.mol-1)^1.5]"] = k
        j0_fit = []
        sto_range = np.linspace(sto_values[0], sto_values[-1], 101)
        for sto in sto_range:
            j0_fit.append(j0_function(sto, param))

        ax.plot(sto_range, j0_fit, ls='--')
        # ax.legend()

    # Fit an Arrhenius temperature dependence
    R = param["Ideal gas constant [J.K-1.mol-1]"]
    T_ref = 298.15
    def func(T, k, E):
        return k * np.exp(-E / R * (1.0 / T - 1.0 / T_ref))

    popt, pcov = curve_fit(func, temperatures, reaction_rates)
    print("Reaction rate [A.m-2.(m3.mol-1)^1.5]:", popt[0])
    print("Activation energy [J.mol-1]:", popt[1])

    fig2, ax2 = plt.subplots(1,1)
    ax2.scatter(1 / temperatures, reaction_rates)
    rept_range = np.linspace(1 / temperatures[0], 1 / temperatures[-1], 101)
    ax2.plot(rept_range, [func(T, popt[0], popt[1]) for T in 1 / rept_range])
    ax2.set_xlabel("Reciprocal temperature (1/K)")
    ax2.set_ylabel("Reaction rate (A\,m$^{-2}$\,(m$^3$\,mol$^{-1}$)$^{1.5}$)   .") # spaces to prevent cropping!
    plt.yscale('log')

    save_path = os.path.join(folder, "exchange_" + cell_type + ".pdf")
    fig.savefig(save_path)
    print("Plot saved at", save_path)
    save_path = os.path.join(folder, "activation_" + cell_type + ".pdf")
    fig2.savefig(save_path)
    print("Plot saved at", save_path)

    # Update and save the parameters using the new data
    param.update(
        {
            "Positive electrode reaction rate [A.m-2.(m3.mol-1)^1.5]": popt[0],
            "Positive electrode reaction activation energy [J.mol-1]": popt[1],
        }
    )
    with open(os.path.join(folder, "results", "parameters_after_4.pickle"), 'wb') as param_file:
        pickle.dump(param, param_file)

# plt.show()
