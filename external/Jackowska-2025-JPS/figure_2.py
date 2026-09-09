"""
Gets the final resting voltage after each GITT pulse to form a GITT-OCV vs.
capacity curve. Capacity is then converted to stoichiometry by fitting the
stretch and shift parameters to match the corresponding pseudo-OCV curve.
"""

import matplotlib.pyplot as plt
import numpy as np
import os
import pandas as pd
import pickle
import pybop
import scienceplots


plt.style.use('science')


for cell_type, cell_name in zip(["2mAh_cm2", "4mAh_cm2"], ["2mAhcm^2_NCM920305", "4mAhcm^2_NCM920305"]):
    print("\n Cell type:", cell_type)

    # Locate cell folder and import parameter values
    folder = os.path.join(os.path.dirname(os.path.realpath(__file__)), cell_type)
    with open(os.path.join(folder, "results", "parameters_after_1.pickle"), 'rb') as param_file:
        param = pickle.load(param_file)

    active_material_volume = (
        param["Electrode width [m]"]
        * param["Electrode height [m]"]
        * param["Positive electrode thickness [m]"]
        * param["Positive electrode active material volume fraction"]
    )

    """
    First process the charge (delithiation) branch.
    """
    switch_time = 1162136.819 if cell_type == "2mAh_cm2" else 1007470
    df = (
        pd.read_csv(os.path.join(folder, "GITT_25degC_" + cell_name + ".csv"))
        [lambda x: x['Time [s]'] < switch_time]
    )
    # # print(df.head()) # to display the first 5 lines of loaded data

    # Import the data into a pybop dataset
    charge_dataset = pybop.Dataset(
        {
            "Time [s]": df["Time [s]"].to_numpy() - df["Time [s]"].iloc[0],
            "Current function [A]": -df["Current [mA]"].to_numpy() * 1e-3,
            "Charge capacity [A.h]": df["Capacity [mAh]"].to_numpy() * 1e-3,
            "Voltage [V]": df["Voltage [V]"].to_numpy(),
        }
    )
    # pybop.plot.trajectories(charge_dataset["Time [s]"], charge_dataset["Voltage [V]"])

    # Extract and compile the final point of each pulse during GITT
    nonzero_index = np.concatenate(
        (
            [-1],
            np.flatnonzero(charge_dataset["Current function [A]"]),
            [len(charge_dataset["Current function [A]"]) + (1 if cell_type == "2mAh_cm2" else 0)],
        )
    )
    pulse_starts = np.extract(
        nonzero_index[1:] - nonzero_index[:-1] != 1,  # check if there is a gap
        nonzero_index[1:],  # return the index at the start of the pulse
    )

    # Select time point one or two before the pulse starts as the steady-state for this dataset
    if cell_type == "2mAh_cm2":
        ocv_index = pulse_starts - 2
    elif cell_type == "4mAh_cm2":
        ocv_index = pulse_starts - 1

    # Estimate the capacities at the min and max stoichiometry-voltage pairs
    charge_ocv = pybop.Interpolant(
        charge_dataset["Charge capacity [A.h]"][ocv_index], charge_dataset["Voltage [V]"][ocv_index]
    )
    inverse_charge_ocp = pybop.InverseOCV(charge_ocv)
    min_capacity = inverse_charge_ocp(3.51)
    max_capacity = inverse_charge_ocp(4.2)

    # Fit the capacity to stoichiometry
    ocv_dataset = charge_dataset.get_subset(ocv_index)
    if cell_type=="2mAh_cm2":
        s0, s1 = 0.91, 0.678
    else:
        s0, s1 = 0.94, 0.723
    ocv_dataset.data["Stoichiometry"] = s0 - s1 * (
        ocv_dataset["Charge capacity [A.h]"][0] - ocv_dataset["Charge capacity [A.h]"]
    ) / (ocv_dataset["Charge capacity [A.h]"][0] - ocv_dataset["Charge capacity [A.h]"][-1])
    dfpc = pd.read_csv(os.path.join(folder, "results", "ocp_charge.csv"))
    ocp_charge_function = pybop.Interpolant(
        dfpc["Stoichiometry"].to_numpy(), dfpc["Voltage [V]"].to_numpy()
    )
    linear_sto = np.linspace(0, 1, 101)
    ocv_dataset_for_fitting = ocv_dataset.get_subset(np.where(ocv_dataset["Voltage [V]"] > 3.55))
    fit_charge = pybop.OCPAverage(
        ocv_dataset_for_fitting,
        pybop.Dataset(
            {"Stoichiometry": linear_sto, "Voltage [V]": ocp_charge_function(linear_sto)}
        ),
        verbose=False,
    )
    fit_charge()
    print(fit_charge.results)

    Q_th = (
        param["Maximum concentration in positive electrode [mol.m-3]"]
        * param["Faraday constant [C.mol-1]"]
        * active_material_volume
    ) / 3600
    print("Theoretical capacity [A.h]:", Q_th)
    Q_gitt_charge = (
        (np.abs(ocv_dataset["Charge capacity [A.h]"][0] - ocv_dataset["Charge capacity [A.h]"][-1]))
        / ((ocv_dataset["Stoichiometry"][0] - ocv_dataset["Stoichiometry"][-1]) * fit_charge.results.x[1])
    )
    print("GITT charge / theoretical capacity:", Q_gitt_charge / Q_th)
    print("Theoretical GITT charge capacity [A.h]:", Q_gitt_charge)

    # Save the fitted OCP in a csv file
    dfgc = pd.DataFrame()
    dfgc["Charge capacity [mA.h]"] = 1e3 * pd.Series(ocv_dataset["Charge capacity [A.h]"] - min_capacity)
    dfgc["Stoichiometry"] = pd.Series(fit_charge.results.x[0] + fit_charge.results.x[1] * ocv_dataset["Stoichiometry"])
    dfgc["Voltage [V]"] = pd.Series(ocv_dataset["Voltage [V]"])
    save_path = os.path.join(folder, "results", "gitt_ocp_charge.csv")
    dfgc.to_csv(save_path, index=False, float_format="%.5g")
    print("Saved at", save_path)

    """
    Continue onto the discharge (lithiation) branch.
    """
    df = (
        pd.read_csv(os.path.join(folder, "GITT_25degC_" + cell_name + ".csv"))
        [lambda x: x['Time [s]'] > switch_time]
    )
    # # print(dfgd.head()) # to display the first 5 lines of loaded data
    if cell_type == "4mAh_cm2":
        df.drop(df[df["Time [s]"] == 1799045.739574581].index, inplace=True)

    # Import the data into a pybop dataset
    discharge_dataset = pybop.Dataset(
        {
            "Time [s]": df["Time [s]"].to_numpy() - df["Time [s]"].iloc[0],
            "Current function [A]": -df["Current [mA]"].to_numpy() * 1e-3,
            "Charge capacity [A.h]": df["Capacity [mAh]"].to_numpy() * 1e-3,
            "Voltage [V]": df["Voltage [V]"].to_numpy(),
        }
    )
    # pybop.plot.trajectories(discharge_dataset["Time [s]"], discharge_dataset["Voltage [V]"])

    # Extract and compile the final point of each pulse during GITT
    nonzero_index = np.concatenate(
        (
            [-1],
            np.flatnonzero(discharge_dataset["Current function [A]"]),
            [len(discharge_dataset["Current function [A]"]) + (1 if cell_type == "2mAh_cm2" else 0)],
        )
    )
    pulse_starts = np.extract(
        nonzero_index[1:] - nonzero_index[:-1] != 1,  # check if there is a gap
        nonzero_index[1:],  # return the index at the start of the pulse
    )

    # Select time point one or two before the pulse starts as the steady-state for this dataset
    if cell_type == "2mAh_cm2":
        ocv_index = pulse_starts - 2
        print(ocv_index[-1])
        ocv_index = ocv_index[:-1]  # remove last point which is below 2.5 V
    elif cell_type == "4mAh_cm2":
        pulse_starts = np.concatenate((pulse_starts[:68], pulse_starts[69:]))  # remove anomalous point discharge
        ocv_index = pulse_starts - 1

    # Fit the capacity to stoichiometry
    ocv_dataset = discharge_dataset.get_subset(ocv_index)
    if cell_type=="2mAh_cm2":
        s0, s1 = 0.31, 0.618
    else:
        s0, s1 = 0.24, 0.676
    ocv_dataset.data["Stoichiometry"] = s0 + s1 * (
        ocv_dataset["Charge capacity [A.h]"][0] - ocv_dataset["Charge capacity [A.h]"]
    ) / (ocv_dataset["Charge capacity [A.h]"][0] - ocv_dataset["Charge capacity [A.h]"][-1])
    dfpd = pd.read_csv(os.path.join(folder, "results", "ocp_discharge.csv"))
    ocp_discharge_function = pybop.Interpolant(
        dfpd["Stoichiometry"].to_numpy(), dfpd["Voltage [V]"].to_numpy()
    )
    ocv_dataset_for_fitting = ocv_dataset.get_subset(np.where(ocv_dataset["Voltage [V]"] > 3.5))
    fit_discharge = pybop.OCPAverage(
        ocv_dataset_for_fitting,
        pybop.Dataset(
            {"Stoichiometry": linear_sto, "Voltage [V]": ocp_discharge_function(linear_sto)}
        ),
        verbose=False,
    )
    fit_discharge()
    print(fit_discharge.results)

    Q_gitt_discharge = (
        -(np.abs(ocv_dataset["Charge capacity [A.h]"][0] - ocv_dataset["Charge capacity [A.h]"][-1]))
        / ((ocv_dataset["Stoichiometry"][0] - ocv_dataset["Stoichiometry"][-1]) * fit_discharge.results.x[1])
    )
    print("GITT discharge / theoretical capacity:", Q_gitt_discharge / Q_th)
    print("Theoretical GITT discharge capacity [A.h]:", Q_gitt_discharge)

    # Save the fitted OCP in a csv file
    dfgd = pd.DataFrame()
    dfgd["Charge capacity [mA.h]"] = 1e3 * pd.Series(ocv_dataset["Charge capacity [A.h]"] - min_capacity)
    dfgd["Stoichiometry"] = pd.Series(fit_discharge.results.x[0] + fit_discharge.results.x[1] * ocv_dataset["Stoichiometry"])
    dfgd["Voltage [V]"] = pd.Series(ocv_dataset["Voltage [V]"])
    save_path = os.path.join(folder, "results", "gitt_ocp_discharge.csv")
    dfgd.to_csv(save_path, index=False, float_format="%.5g")
    print("Saved at", save_path)

    """
    Plot the GITT-OCV and pseudo-OCV versus capacity for comparison.
    """
    fig, (ax, ax2) = plt.subplots(2, 1, height_ratios=[4, 2], sharex=True)
    ax.plot(dfgc["Stoichiometry"].to_numpy(), dfgc["Voltage [V]"].to_numpy(), ls='--', label="GITT-OCV charge")
    ax.plot(dfpc["Stoichiometry"].to_numpy(), dfpc["Voltage [V]"].to_numpy(), label="Pseudo-OCV charge")
    ax.plot(dfpd["Stoichiometry"].to_numpy(), dfpd["Voltage [V]"].to_numpy(), label="Pseudo-OCV discharge")
    ax.plot(dfgd["Stoichiometry"].to_numpy(), dfgd["Voltage [V]"].to_numpy(), ls='--', label="GITT-OCV disharge")
    
    fig.subplots_adjust(hspace=0)
    ax.set_ylabel("Voltage (V)")
    ax2.set_xlabel("Stoichiometry")
    ax2.set_ylabel("dx/dV (V$^{-1}$)")
    ax.legend()

    ax2.plot(
        dfgc["Stoichiometry"].to_numpy(),
        np.gradient(dfgc["Stoichiometry"].to_numpy(), dfgc["Voltage [V]"].to_numpy()),
        ls='--',
    )
    for d in [dfpc, dfpd]:
        ax2.plot(
            d["Stoichiometry"].to_numpy(),
            np.gradient(d["Stoichiometry"].to_numpy(), d["Voltage [V]"].to_numpy()),
        )
    ax2.plot(
        dfgd["Stoichiometry"].to_numpy(),
        np.gradient(dfgd["Stoichiometry"].to_numpy(), dfgd["Voltage [V]"].to_numpy()),
        ls='--',
    )

    save_path = os.path.join(folder, "comparing_OCVs_" + cell_type + ".pdf")
    fig.savefig(save_path)
    print("Plot saved at", save_path)

    # Update and save the parameters using the new data
    param.update(
        {
            "Theoretical GITT charge capacity [A.h]": Q_gitt_charge,
            "Theoretical GITT discharge capacity [A.h]": Q_gitt_discharge,
        },
        check_already_exists=False,
    )
    with open(os.path.join(folder, "results", "parameters_after_2.pickle"), 'wb') as param_file:
        pickle.dump(param, param_file)

# plt.show()    
