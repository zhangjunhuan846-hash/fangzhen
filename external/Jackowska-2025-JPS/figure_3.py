"""
Uses the diffusion timescale and lumped resistance values estimated from
GITT to calculated diffusivity and validate the GITT experiment.

The theoretical capacity values are calculated in figure_2.py.
"""

import matplotlib.pyplot as plt
import numpy as np
import os
import pandas as pd
import pickle
import pybamm
import pybop
import scienceplots

from Jackowska2025 import get_parameter_values
from scipy.optimize import curve_fit, minimize, differential_evolution


plt.style.use('science')


for cell_type, cell_name in zip(["2mAh_cm2", "4mAh_cm2"], ["2mAhcm^2_NCM920305", "4mAhcm^2_NCM920305"]):
    print("\n Cell type:", cell_type)

    # Locate cell folder and import parameter values
    folder = os.path.join(os.path.dirname(os.path.realpath(__file__)), cell_type)
    with open(os.path.join(folder, "results", "parameters_after_2.pickle"), 'rb') as param_file:
        param = pickle.load(param_file)

    # Set up plots for the parameter data
    figp, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(3.5, 2.5 * 2.625))
    figp.tight_layout()
    figp.subplots_adjust(hspace=0)

    ax1.set_xlabel("Stoichiometry")
    ax1.set_ylabel("Diffusion time (s)")

    ax2.set_xlabel("Stoichiometry")
    ax2.set_ylabel("Lumped resistance (Ohm)")

    ax3.set_xlabel("Stoichiometry")
    ax3.set_ylabel("RMSE (V)")

    figd, ax4 = plt.subplots(1,1)
    ax4.set_xlabel("Stoichiometry")
    ax4.set_ylabel("Diffusivity (m$^2$\,s$^{-1}$)")
    ax4.set_yscale("log")

    for direction in ["charge", "discharge"]:

        # Load the GITT-OCV
        ocv_df = pd.read_csv(os.path.join(folder, "results", "gitt_ocp_" + direction + ".csv"))
        gitt_ocv = pybop.Interpolant(
            np.flip(ocv_df["Stoichiometry"].to_numpy()) if direction == "charge" else ocv_df["Stoichiometry"].to_numpy(),
            np.flip(ocv_df["Voltage [V]"].to_numpy()) if direction == "charge" else ocv_df["Voltage [V]"].to_numpy(),
            name="Positive electrode OCP from GITT",
        )
        param["Positive electrode OCP [V]"] = gitt_ocv
        inverse_ocv = pybop.InverseOCV(gitt_ocv)

        # Load the GITT data
        switch_time = 1162136.819 if cell_type == "2mAh_cm2" else 1007470
        if direction == "charge":
            df = (
                pd.read_csv(os.path.join(folder, "GITT_25degC_" + cell_name + ".csv"))
                [lambda x: x['Time [s]'] < switch_time]
            )
        else:
            df = (
                pd.read_csv(os.path.join(folder, "GITT_25degC_" + cell_name + ".csv"))
                [lambda x: x['Time [s]'] > switch_time]
            )
            if cell_type == "4mAh_cm2":
                df.drop(df[df["Time [s]"] == 1799045.739574581].index, inplace=True)

        # Import the data into a pybop dataset
        dataset = pybop.Dataset(
            {
                "Time [s]": df["Time [s]"].to_numpy() - df["Time [s]"].iloc[0],
                "Current function [A]": -df["Current [mA]"].to_numpy() * 1e-3,
                "Charge capacity [A.h]": -df["Capacity [mAh]"].to_numpy() * 1e-3,
                "Voltage [V]": df["Voltage [V]"].to_numpy(),
            }
        )

        # Define the diffusion model parameter set
        param["Positive electrode diffusivity [m2.s-1]"] = 1e-16
        parameter_set = pybop.lithium_ion.SPDiffusion.apply_parameter_grouping(param, electrode="positive")
        parameter_set.update({"Initial stoichiometry": inverse_ocv(dataset["Voltage [V]"][0])})

        parameter_set["Theoretical electrode capacity [A.s]"] = (
            3600 * param["Theoretical GITT " + direction + " capacity [A.h]"]
        )

        # Load saved GITT data
        param_df = pd.read_csv(os.path.join(folder, "results", "gitt_" + direction + ".csv"))

        """
        Interpolate the parameter data and validate the identified model via plotting.
        """
        # Discard parameter estimates with a high error cost
        error_limit = 0.005
        low_error_index = [
            i for i, error in enumerate(param_df["RMSE [V]"]) if error < error_limit
        ]
        stoichiometry = param_df["Stoichiometry"][low_error_index].to_numpy()
        stoichiometry_full = np.concatenate(([0], stoichiometry, [1]))
        diffusion_timescale = param_df["Diffusion time [s]"][low_error_index].to_numpy()
        diffusivity = param_df["Diffusivity [m2.s-1]"][low_error_index].to_numpy()
        lumped_resistance = param_df["Lumped resistance [Ohm]"][low_error_index].to_numpy()

        ax1.scatter(stoichiometry, diffusion_timescale, s=4, label=direction)
        ax2.scatter(stoichiometry, lumped_resistance, s=4, label=direction)
        ax3.scatter(param_df["Stoichiometry"], param_df["RMSE [V]"], s=4, label=direction)
        ax3.axhline(y=error_limit, color='gray', ls='--')
        ax2.legend()
        ax4.scatter(stoichiometry, diffusivity, s=4, label=direction)
        ax4.legend()

        # Extrapolate to avoid negative values
        diffusion_timescale = np.concatenate(
            ([diffusion_timescale[0]], diffusion_timescale, [diffusion_timescale[-1]])
        )

        # Use either mean value or interpolant
        parameter_set.update(
            {
                "Particle diffusion time scale [s]": pybop.Interpolant(
                    stoichiometry_full, diffusion_timescale
                ),
                "Series resistance [Ohm]": pybop.Interpolant(
                    stoichiometry, lumped_resistance
                ),
            }
        )

        # Update the model
        model = pybop.lithium_ion.SPDiffusion(
            parameter_set=parameter_set,
            electrode="positive",
            build=True,
            solver=pybamm.CasadiSolver(
                on_extrapolation="ignore",
                dt_max=300,
                return_solution_if_failed_early=True,
                extra_options_setup={"max_num_steps": 3000},
            ),
        )
        model.set_current_function(dataset)

        # Compare the identified model prediction to the data
        values = model.predict(t_eval=dataset["Time [s]"])

        fig, ax = plt.subplots(1,1)
        ax.plot(dataset["Time [s]"] / 3600, dataset["Voltage [V]"], label="Measurement")
        ax.plot(values["Time [s]"].data / 3600, values["Voltage [V]"].data, label="Simulation", ls=':')
        ax.set_xlabel("Time (hr)")
        ax.set_ylabel("Voltage (V)")
        ax.legend()

        save_path = os.path.join(folder, "gitt_" + direction + "_" + cell_type + ".pdf")
        fig.savefig(save_path)
        print("Plot saved at", save_path)

        min_len = np.minimum(len(dataset["Voltage [V]"]), len(values["Voltage [V]"].data))
        print(
            cell_type + " GITT " + direction + " RMSE:",
            np.sqrt(np.mean((dataset["Voltage [V]"][:min_len] - values["Voltage [V]"].data[:min_len]) **2))
        )

    # Save the diffusivity data for the discharge branch
    df = pd.DataFrame()
    df["Stoichiometry"] = pd.Series(stoichiometry_full)
    df["Diffusivity [m2.s-1]"] = pd.Series(param["Positive particle radius [m]"]**2 / diffusion_timescale)
    save_path = os.path.join(folder, "results", "diffusivity_" + direction + ".csv")
    df.to_csv(save_path, index=False, float_format="%.5g")
    print("Saved at", save_path)

    save_path = os.path.join(folder, "gitt_results_" + cell_type + ".pdf")
    figp.savefig(save_path)
    print("Plot saved at", save_path)
    save_path = os.path.join(folder, "diffusivity_" + cell_type + ".pdf")
    figd.savefig(save_path)
    print("Plot saved at", save_path)

    # Update and save the parameters using the new data
    Q_gitt = [param["Theoretical GITT charge capacity [A.h]"], param["Theoretical GITT discharge capacity [A.h]"]]
    param = pybamm.ParameterValues(get_parameter_values(cell_type))
    param.update(
        {
            "Theoretical GITT charge capacity [A.h]": Q_gitt[0],
            "Theoretical GITT discharge capacity [A.h]": Q_gitt[1],
        },
        check_already_exists=False,
    )
    with open(os.path.join(folder, "results", "parameters_after_3.pickle"), 'wb') as param_file:
        pickle.dump(param, param_file)

# plt.show()
