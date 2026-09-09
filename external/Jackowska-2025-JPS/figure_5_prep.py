"""
Fits the contact resistance to the 1C discharge experiment.

The reaction rate and activation energy are calculated in figure_4.py.
"""

import numpy as np
import os
import pandas as pd
import pickle
import pybamm
import pybop
import scienceplots


for cell_type, cell_name in zip(["2mAh_cm2", "4mAh_cm2"], ["2mAhcm^2_NCM920305", "4mAhcm^2_NCM920305"]):
    print("\n Cell type:", cell_type)

    # Locate cell folder and import parameter values
    folder = os.path.join(os.path.dirname(os.path.realpath(__file__)), cell_type)
    with open(os.path.join(folder, "results", "parameters_after_4.pickle"), 'rb') as param_file:
        param = pickle.load(param_file)

    options = {
        "working electrode": "positive",
        "surface form": "differential",
        "contact resistance": "true",
    }
    param["Lower voltage cut-off [V]"] = 1.5

    active_material_volume = (
        param["Electrode height [m]"]
        * param["Electrode width [m]"]
        * param["Positive electrode thickness [m]"]
        * param["Positive electrode active material volume fraction"]
    )

    df = pd.read_csv(os.path.join(folder, "RateCapability_1C_" + cell_name + ".csv"))
    # print(df.head()) # to display the first 5 lines of loaded data
    df = df.drop_duplicates(subset=["Time [s]"], keep="first")

    # Move the initial time point to be just before the current switch-on
    df.at[0, "Time [s]"] = (
        df["Time [s]"].iloc[1] + 2 * (df["Capacity [mAh]"].iloc[1] / df["Current [mA]"].iloc[1]) * 3600
    )

    # Import the initial phase of the discharge into a pybop dataset
    idx = (df["Time [s]"] - df["Time [s]"].iloc[0]) < 120
    dataset = pybop.Dataset(
        {
            "Time [s]": df["Time [s]"][idx].to_numpy() - df["Time [s]"].iloc[0],
            "Current function [A]": -df["Current [mA]"][idx].to_numpy() * 1e-3,
            "Discharge capacity [A.h]": df["Capacity [mAh]"].to_numpy() * 1e-3,
            "Voltage [V]": df["Voltage [V]"][idx].to_numpy(),
        }
    )

    # Scale the capacity to the dataset and set the initial concentration
    ocp = pd.read_csv(os.path.join(folder, "results", "ocp_discharge.csv"))
    inverse_ocp = pybop.InverseOCV(
        pybop.Interpolant(ocp["Stoichiometry"].to_numpy(), ocp["Voltage [V]"].to_numpy())
    )
    soc_init = inverse_ocp(dataset["Voltage [V]"][0])
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
        ),
    )
    model.set_current_function(dataset=dataset)

    # Define the optimisation parameters
    parameters = pybop.Parameters(
        pybop.Parameter("Contact resistance [Ohm]", initial_value=20.0)
    )

    # Define the fitting problem, cost and optimisation algorithm
    problem = pybop.FittingProblem(model, parameters, dataset, check_model=False)
    cost = pybop.RootMeanSquaredError(problem, weighting="domain")
    optim = pybop.SciPyMinimize(cost, tol=1e-8)

    # Run the optimisation and plot the results
    results = optim.run()
    print(results)
    
    # Update and save the parameters using the new data
    param.update({"Contact resistance [Ohm]": results.x[0]})
    with open(os.path.join(folder, "results", "parameters_after_5a.pickle"), 'wb') as param_file:
        pickle.dump(param, param_file)
