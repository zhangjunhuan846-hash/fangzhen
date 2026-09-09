"""
Estimates the diffusion timescale and lumped resistance for each GITT
pulse and subsequent relaxation and saves the data.
"""

import matplotlib.pyplot as plt
import numpy as np
import os
import pandas as pd
import pickle
import pybamm
import pybop
import scienceplots


plt.style.use('science')


for cell_type, cell_name in zip(["2mAh_cm2", "4mAh_cm2"], ["2mAhcm^2_NCM920305", "4mAhcm^2_NCM920305"]):
    print("\n Cell type:", cell_type)

    # Locate cell folder and import parameter values
    folder = os.path.join(os.path.dirname(os.path.realpath(__file__)), cell_type)
    with open(os.path.join(folder, "results", "parameters_after_2.pickle"), 'rb') as param_file:
        param = pickle.load(param_file)

    for direction in ["charge", "discharge"]:

        # Load the GITT-OCV
        ocv_df = pd.read_csv(os.path.join(folder, "results", "gitt_ocp_" + direction + ".csv"))
        if direction == "charge":
            gitt_ocv = pybop.Interpolant(
                np.flip(ocv_df["Stoichiometry"].to_numpy()), np.flip(ocv_df["Voltage [V]"].to_numpy())
            )
        else:
            gitt_ocv = pybop.Interpolant(ocv_df["Stoichiometry"].to_numpy(), ocv_df["Voltage [V]"].to_numpy())
        param["Positive electrode OCP [V]"] = gitt_ocv
        inverse_ocv = pybop.InverseOCV(gitt_ocv)

        """
        Estimate the diffusion time scale from each GITT pulse.
        """
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

        # Extract and compile the final point of each pulse during GITT
        nonzero_index = np.concatenate(
            (
                [-1],
                np.flatnonzero(dataset["Current function [A]"]),
                [len(dataset["Current function [A]"]) + (1 if cell_type == "2mAh_cm2" else 0)],
            )
        )
        pulse_starts = np.extract(
            nonzero_index[1:] - nonzero_index[:-1] != 1,  # check if there is a gap
            nonzero_index[1:],  # return the index at the start of the pulse
        )
        if cell_type == "4mAh_cm2" and direction=="discharge":
            pulse_starts = np.concatenate((pulse_starts[:68], pulse_starts[69:]))  # remove anomalous point discharge

        # Determine the indices corresponding to each pulse in the dataset
        pulse_index = []
        for start, finish in zip(pulse_starts[:-1], pulse_starts[1:]):
            # Include one or two points before the pulse starts for this dataset
            pulse_index.append(
                np.concatenate(
                    (
                        [start-2, start-1] if cell_type == "2mAh_cm2" else [start-1],
                        # [i for i in nonzero_index if i >= start and i < finish],  # for pulse only
                        np.arange(start, finish - (1 if cell_type == "2mAh_cm2" else 0)),  # for pulse and relaxation
                    )
                )
            )

        # Begin with an approximate value for the diffusivity (for speed)
        if cell_type == "2mAh_cm2":
            param["Positive electrode diffusivity [m2.s-1]"] = (
                5.2e-17 if direction == "charge" else 4.1e-16
            )
        elif cell_type == "4mAh_cm2":
            param["Positive electrode diffusivity [m2.s-1]"] = (
                3.8e-17 if direction == "charge" else 1.0e-16
            )

        # Define the diffusion model parameter set
        parameter_set = pybop.lithium_ion.SPDiffusion.apply_parameter_grouping(param, electrode="positive")
        parameter_set.update({"Initial stoichiometry": inverse_ocv(dataset["Voltage [V]"][0])})

        # Set up the optimisation problem
        gitt_fit = pybop.GITTFit(dataset, pulse_index, parameter_set, electrode="positive")
        gitt_fit.gitt_pulse.model.solver = pybamm.CasadiSolver(return_solution_if_failed_early=True)

        # Iterate through and fit each pulse
        gitt_parameter_data = gitt_fit()

        # Save the diffusivity data in a csv file
        df = pd.DataFrame()
        df["Stoichiometry"] = pd.Series(gitt_parameter_data["Stoichiometry"])
        df["Voltage [V]"] = pd.Series(gitt_ocv(gitt_parameter_data["Stoichiometry"]))
        df["Diffusivity [m2.s-1]"] = pd.Series(
            param["Positive particle radius [m]"]**2 / gitt_parameter_data["Particle diffusion time scale [s]"]
        )
        df["Diffusion time [s]"] = pd.Series(gitt_parameter_data["Particle diffusion time scale [s]"])
        df["Lumped resistance [Ohm]"] = pd.Series(gitt_parameter_data["Series resistance [Ohm]"])
        df["RMSE [V]"] = pd.Series(gitt_parameter_data["Root Mean Squared Error [V]"])
        save_path = os.path.join(folder, "results", "gitt_" + direction + ".csv")
        df.to_csv(save_path, index=False, float_format="%.5g")
        print("Saved at", save_path)
