"""
Plots the diffusivity scaling factor and the rate capability validation
versus discharge capacity.

The diffusivity scaling and RMSE values are calculated in figure_5.py.
"""

import matplotlib.pyplot as plt
import numpy as np
import os
import pandas as pd
import pickle
import pybamm
import pybop
import scienceplots

from scipy.optimize import curve_fit


plt.style.use('science')


Crates = [1/10, 1/5, 1/2, 1, 2]
rates = ["Cover10","Cover5","Cover2","1C","2C"]
colours = ["black", "blue", "purple", "red", "green"]

for cell_type, cell_name in zip(["2mAh_cm2", "4mAh_cm2"], ["2mAhcm^2_NCM920305", "4mAhcm^2_NCM920305"]):
    print("\n Cell type:", cell_type)

    # Locate cell folder and import parameter values
    folder = os.path.join(os.path.dirname(os.path.realpath(__file__)), cell_type)
    with open(os.path.join(folder, "results", "parameters_after_5.pickle"), 'rb') as param_file:
        param = pickle.load(param_file)

    options = {
        "working electrode": "positive",
        "surface form": "differential",
        "contact resistance": "true",
    }
    param["Lower voltage cut-off [V]"] = 1.5

    # Plot the results from figure_5.py
    fig, (ax1, ax3) = plt.subplots(2, 1, height_ratios=[2, 1], sharex=True)
    ax1.scatter(Crates, param["Scaling values"])
    ax1.set_ylabel("Diffusivity factor")
    ax3.scatter(Crates, param["RMSE values"])
    ax3.set_ylabel("RMSE (V)")
    ax3.set_xlabel("Discharge C-rate")
    fig.tight_layout()
    fig.subplots_adjust(hspace=0)

    # Fit a square-root dependence
    def func(Crate, a):
        return 1 + a * Crate

    if cell_type == "2mAh_cm2":
        popt, pcov = curve_fit(func, Crates, param["Scaling values"])
    else:
        popt, pcov = curve_fit(func, Crates[:-1], param["Scaling values"][:-1])

    print("Prefactor:", popt[0])

    r = np.linspace(0.1, 2, 101)
    ax1.plot(r, func(r, popt[0]), ls='--')

    save_path = os.path.join(folder, "vscaling_" + cell_type + ".pdf")
    fig.savefig(save_path)
    print("Plot saved at", save_path)

    """
    Set up the parameters.
    """
    scaling_values = 1 + popt[0] * np.asarray(Crates)

    # Set up validation figure
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(5, 4), height_ratios=[3, 2], sharex=True)
    x_var, y_var = "Discharge capacity [mA.h]", "Voltage [V]"
    ax2.set_xlabel("Discharge capacity (mA\,h)")
    ax.set_ylabel("Voltage (V)")
    ax2.set_ylabel("Absolute error (V)")

    """
    Loop over the different discharge rates.
    """
    for i, rate in enumerate(rates):
        df = pd.read_csv(os.path.join(folder, "RateCapability_" + rate + "_" + cell_name + ".csv"))
        # print(df.head()) # to display the first 5 lines of loaded data
        df = df.drop_duplicates(subset=["Time [s]"], keep="first")

        # Move the initial time point to be just before the current switch-on
        df.at[0,"Time [s]"] = (
            df["Time [s]"].iloc[1] + 2 * (df["Capacity [mAh]"].iloc[1] / df["Current [mA]"].iloc[1]) * 3600
        )

        # Import the data into a pybop dataset
        dataset = {
            "Time [s]": df["Time [s]"].to_numpy() - df["Time [s]"].iloc[0],
            "Current function [A]": -df["Current [mA]"].to_numpy() * 1e-3,
            "Discharge capacity [mA.h]": df["Capacity [mAh]"].to_numpy(),
            "Discharge capacity [A.h]": df["Capacity [mAh]"].to_numpy() * 1e-3,
            "Voltage [V]": df["Voltage [V]"].to_numpy(),
        }

        """
        Load the validation discharges from figure_5.py.
        """
        # sim = pd.read_csv(os.path.join(folder, "results", rate + "_discharge.csv"))
        # sim = sim.to_dict(orient='series')
        # sim["Discharge capacity [mA.h]"] = 1e3 * sim["Discharge capacity [A.h]"]

        # Update the diffusivity
        param.update({"Positive electrode diffusivity scaling factor": scaling_values[i]})

        # Scale the capacity to the dataset and set the initial concentration
        ocp = pd.read_csv(os.path.join(folder, "results", "ocp_discharge.csv"))
        inverse_ocp = pybop.InverseOCV(
            pybop.Interpolant(ocp["Stoichiometry"].to_numpy(), ocp["Voltage [V]"].to_numpy())
        )
        soc_init = inverse_ocp(dataset["Voltage [V]"][0])
        if i==0:
            soc_final = inverse_ocp(dataset["Voltage [V]"][-1])
            param["Maximum concentration in positive electrode [mol.m-3]"] = (
                np.abs(dataset["Discharge capacity [A.h]"][-1]) * 3600 / (
                    param["Faraday constant [C.mol-1]"]
                    * param["Electrode height [m]"]
                    * param["Electrode width [m]"]
                    * param["Positive electrode thickness [m]"]
                    * param["Positive electrode active material volume fraction"]
                    * np.abs(soc_init - soc_final)
                )
            )
        param["Initial concentration in positive electrode [mol.m-3]"] = (
            soc_init * pybamm.Parameter("Maximum concentration in positive electrode [mol.m-3]")
        )

        # Set up a half-cell model using the Jackowska2025 parameter set
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
        model.set_current_function(dataset=dataset)
        model.pybamm_model.events = []

        # Simulate the discharge
        simulation = model.predict(t_eval=dataset["Time [s]"])
        sim = {
            "Time [s]": simulation["Time [s]"].data,
            "Current function [A]": simulation["Current [A]"].data,
            "Discharge capacity [mA.h]": 1e3 * simulation["Discharge capacity [A.h]"].data,
            "Discharge capacity [A.h]": simulation["Discharge capacity [A.h]"].data,
            "Voltage [V]": simulation["Voltage [V]"].data,
        }

        # Extract the data and generate traces
        colour = colours[i]
        ax.plot(dataset[x_var], dataset[y_var], color=colour, label=rate.replace("_","/"))
        ax.plot(sim[x_var], sim[y_var], ls="dashed", color=colour)
        ax2.plot(
            sim[x_var],
            np.abs(dataset[y_var][:len(sim[y_var])] - sim[y_var]),
            color=colour,
        )
        ax.set_ylim(2.5, 4.25)
        if cell_type == "2mAh_cm2":
            ax.legend()  # (bbox_to_anchor=(1.01, 0.65))
        fig.tight_layout()
        fig.subplots_adjust(hspace=0)

    save_path = os.path.join(folder, "validation_" + cell_type + ".pdf")
    fig.savefig(save_path)
    print("Plot saved at", save_path)

    # Update and save the parameters using the new data
    param["Lower voltage cut-off [V]"] = 2.5
    param["Positive electrode diffusivity scaling factor"] = scaling_values[3]
    with open(os.path.join(folder, "results", "parameters_after_6.pickle"), 'wb') as param_file:
        pickle.dump(param, param_file)
    print(param)

# plt.show()
