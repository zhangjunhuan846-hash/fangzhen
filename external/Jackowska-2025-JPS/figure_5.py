"""
Fits the diffusivity scaling factor and validates the rate capability
discharge experiments.

The contact resistance is calculated in figure_5_prep.py.
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


rates = ["Cover10", "Cover5", "Cover2", "1C", "2C"]
colours = ["black", "blue", "purple", "red", "green"]

for cell_type, cell_name in zip(["2mAh_cm2", "4mAh_cm2"], ["2mAhcm^2_NCM920305", "4mAhcm^2_NCM920305"]):
    print("\n Cell type:", cell_type)

    # Locate cell folder and import parameter values
    folder = os.path.join(os.path.dirname(os.path.realpath(__file__)), cell_type)
    with open(os.path.join(folder, "results", "parameters_after_5a.pickle"), 'rb') as param_file:
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

    """
    Loop over the different discharge rates.
    """
    scaling_values = []
    final_costs = []

    for i, rate in enumerate(rates):
        df = pd.read_csv(os.path.join(folder, "RateCapability_" + rate + "_" + cell_name + ".csv"))
        # print(df.head()) # to display the first 5 lines of loaded data
        df = df.drop_duplicates(subset=["Time [s]"], keep="first")

        # Move the initial time point to be just before the current switch-on
        df.at[0,"Time [s]"] = (
            df["Time [s]"].iloc[1] + 2 * (df["Capacity [mAh]"].iloc[1] / df["Current [mA]"].iloc[1]) * 3600
        )

        # Import the data into a pybop dataset
        dataset = pybop.Dataset(
            {
                "Time [s]": df["Time [s]"].to_numpy() - df["Time [s]"].iloc[0],
                "Current function [A]": -df["Current [mA]"].to_numpy() * 1e-3,
                "Discharge capacity [A.h]": df["Capacity [mAh]"].to_numpy() * 1e-3,
                "Voltage [V]": df["Voltage [V]"].to_numpy(),
            }
        )

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
                    * active_material_volume
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
            ),
        )
        model.set_current_function(dataset=dataset)

        """
        Optimise the uncertain parameters.
        """
        prior_estimates = (
            [1.16, 2.09, 3.89, 8.58, 12.26] if cell_type == "2mAh_cm2" else [1.03, 1.43, 1.98, 2.46, 0.32]
        )
        parameters = pybop.Parameters(
            pybop.Parameter(
                "Positive electrode diffusivity scaling factor",
                initial_value=prior_estimates[i],
            )
        )

        # Define the fitting problem, cost and optimisation algorithm
        problem = pybop.FittingProblem(model, parameters, dataset, check_model=False)
        cost = pybop.RootMeanSquaredError(problem, weighting="domain")
        optim = pybop.SciPyMinimize(cost, tol=1e-6, max_iterations=250)

        # Run the optimisation and plot the results
        results = optim.run()
        scaling_values.append(results.x[0])
        final_costs.append(results.final_cost)
        print(results)

        """
        Create the validation plot.
        """
        fig, (ax, ax2) = plt.subplots(2, 1, figsize=(6, 3.8), height_ratios=[2.75, 2], sharex=True)
        x_var, y_var = "Time [s]", "Voltage [V]"
        ax2.set_xlabel("Time (s)")
        ax.set_ylabel("Voltage (V)")
        ax2.set_ylabel("Absolute error (V)")
        colour = colours[i]

        # Simulate the discharge
        inputs = parameters.as_dict(results.x)
        simulation = model.predict(t_eval=dataset["Time [s]"], inputs=inputs)

        # Save the simulated discharge data in a csv file
        df = pd.DataFrame()
        df["Time [s]"] = pd.Series(simulation["Time [s]"].data)
        df["Current [mA]"] = pd.Series(simulation["Current [A]"].data * 1e3)
        df["Discharge capacity [A.h]"] = pd.Series(simulation["Discharge capacity [A.h]"].data)
        df["Voltage [V]"] = pd.Series(simulation["Voltage [V]"].data)
        df["Absolute error [V]"] = pd.Series(
            np.abs(dataset["Voltage [V]"][:len(simulation["Voltage [V]"].data)] - simulation["Voltage [V]"].data)
        )
        df.to_csv(os.path.join(folder, "results", rate + "_discharge.csv"), index=False, float_format="%.5g")

        # Extract the data and generate traces
        ax.plot(dataset[x_var], dataset[y_var], color=colour)
        ax.plot(simulation[x_var].data, simulation[y_var].data, ls="dashed", color=colour)
        ax.set_ylim(2.5, 4.25)

        # ax.legend(bbox_to_anchor=(1.01, 0.65))
        fig.tight_layout()
        fig.subplots_adjust(hspace=0)

        absolute_error = np.abs(dataset[y_var][:len(simulation[y_var].data)] - simulation[y_var].data)
        ax2.plot(simulation[x_var].data, absolute_error, color=colour)
        ax2.set_ylim(0, np.maximum(0.5, np.max(absolute_error)))

        save_path = os.path.join(folder, rate + "_discharge_" + cell_type + ".pdf")
        fig.savefig(save_path)
        print("Plot saved at", save_path)

    print("c_s_max:", param["Maximum concentration in positive electrode [mol.m-3]"])
    print("Scaling:", scaling_values)
    print("RMSE [V]:", final_costs)
    
    # Update and save the parameters using the new data
    param.update(
        {"Scaling values": scaling_values, "RMSE values": final_costs},
        check_already_exists=False,
    )
    with open(os.path.join(folder, "results", "parameters_after_5.pickle"), 'wb') as param_file:
        pickle.dump(param, param_file)

# plt.show()
