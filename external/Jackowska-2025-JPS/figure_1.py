"""
Plots the delithiation data versus capacity and corresponding stoichiometry,
assuming the electrode begins fully lithiated with the theoretical maximum
concentration of lithium in the active material.
"""

import matplotlib.pyplot as plt
import numpy as np
import os
import pandas as pd
import pickle
import pybamm
import scienceplots

from Jackowska2025 import get_parameter_values
from scipy.interpolate import make_smoothing_spline


plt.style.use('science')


for cell_type, cell_name in zip(["2mAh_cm2", "4mAh_cm2"], ["2mAhcm^2_NCM920305", "4mAhcm^2_NCM920305"]):
    print("\n Cell type:", cell_type)

    # Locate cell folder and import parameter values
    folder = os.path.join(os.path.dirname(os.path.realpath(__file__)), cell_type)
    param = pybamm.ParameterValues(get_parameter_values(cell_type))

    active_material_volume = (
        param["Electrode width [m]"]
        * param["Electrode height [m]"]
        * param["Positive electrode thickness [m]"]
        * param["Positive electrode active material volume fraction"]
    )
    theoretical_capacity = (
        active_material_volume
        * param["Faraday constant [C.mol-1]"]
        * param["Maximum concentration in positive electrode [mol.m-3]"]
    ) / 3600

    # Load the delithiation data as a pandas dataframe
    delithiation = (
        pd.read_csv(os.path.join(folder, "Formation_" + cell_name + ".csv"))
        [lambda x: x['Step'] < 4]
    )

    # Extract the final points
    final_step = 2
    final_capacity = 1e-3 * (
        delithiation["Capacity [mAh]"][delithiation["Step"] == final_step].iloc[-1]
        - delithiation["Capacity [mAh]"][0]
    )
    final_voltage = delithiation["Voltage [V]"][delithiation["Step"] == final_step].iloc[-1]

    def mAh2sto(cap):
        return 1 - 1e-3 * cap / theoretical_capacity

    def sto2mAh(sto):
        return (1 - sto) * theoretical_capacity * 1e3

    # Create figure
    fig, ax = plt.subplots(1, 1)
    ax.plot(
        delithiation["Capacity [mAh]"].to_numpy() - delithiation["Capacity [mAh]"][0],
        delithiation["Voltage [V]"].to_numpy(),
        label="Delithiation",
    )
    ax.set_xlabel("Charge capacity (mA\,h)")
    ax.set_ylabel("Voltage (V)")
    secax = ax.secondary_xaxis('top', functions=(mAh2sto, sto2mAh))
    secax.set_xlabel('Stoichiometry')

    # Find the minimum stoichiometry
    sto_min = mAh2sto(1e3 * final_capacity)
    print("Maximum stoichiometry", 1, 'at', delithiation["Voltage [V]"][0], "V")
    print("Minimum stoichiometry", sto_min, 'at', final_voltage, "V")

    """
    Align, plot and save the pseudo-OCV charge and discharge.
    """
    charge_data = (
        pd.read_csv(os.path.join(folder, "pOCV_" + cell_name + ".csv"))
        [lambda x: (x['Step'] > 1) & (x['Step'] < 4)]
    )
    discharge_data = (
        pd.read_csv(os.path.join(folder, "pOCV_" + cell_name + ".csv"))
        [lambda x: x['Step'] == 4]
    )

    # Drop first and last rows to avoid duplicates
    charge_data.drop(charge_data.index[[0, -1]], inplace=True)
    discharge_data.drop(discharge_data.index[[0, -1]], inplace=True)

    # Align the minimum stoichiometry reached at the end of the CV charge
    # capacity_shift = 0
    capacity_shift = 1e3 *final_capacity - charge_data["Capacity [mAh]"].iloc[-1]
    print("Formation loss [mA.h]:", capacity_shift)

    # Plot the data
    ax.plot(
        charge_data["Capacity [mAh]"].to_numpy() + capacity_shift,
        charge_data["Voltage [V]"].to_numpy(),
        label="Pseudo-OCV charge",
    )
    ax.plot(
        discharge_data["Capacity [mAh]"].to_numpy() + capacity_shift,
        discharge_data["Voltage [V]"].to_numpy(),
        label="Pseudo-OCV discharge",
    )

    if capacity_shift != 0:
        ax.axvline(x=capacity_shift, color='gray', ls='--')

    ax.legend()

    save_path = os.path.join(folder, "shifted_OCV_" + cell_type + ".pdf")
    fig.savefig(save_path)
    print("Plot saved at", save_path)

    """
    Smooth data before saving.
    """
    # Use only the CC section, drop last row to avoid duplicates
    charge_data = charge_data[charge_data["Step"] == 2]
    charge_data.drop(charge_data.index[[-1]], inplace=True)

    # Save the pseudo-OCV charge branch
    df = pd.DataFrame()
    df["Stoichiometry"] = pd.Series(mAh2sto(charge_data["Capacity [mAh]"].to_numpy() + capacity_shift))
    y_spline = make_smoothing_spline(np.flip(df["Stoichiometry"]), np.flip(charge_data["Voltage [V]"].to_numpy()), lam=1e-8)
    df["Voltage [V]"] = pd.Series(y_spline(df["Stoichiometry"]))
    save_path = os.path.join(folder, "results", "ocp_charge.csv")
    df.to_csv(save_path, index=False, float_format="%.6f")
    print("Saved at:", save_path)

    ax.plot(sto2mAh(df["Stoichiometry"]), df["Voltage [V]"], ls='--', label="Smoothed pOCV charge")

    # And the discharge branch
    df = pd.DataFrame()
    df["Stoichiometry"] = pd.Series(mAh2sto(discharge_data["Capacity [mAh]"].to_numpy() + capacity_shift))
    y_spline = make_smoothing_spline(df["Stoichiometry"], discharge_data["Voltage [V]"].to_numpy(), lam=1e-8)
    df["Voltage [V]"] = pd.Series(y_spline(df["Stoichiometry"]))
    save_path = os.path.join(folder, "results", "ocp_discharge.csv")
    df.to_csv(save_path, index=False, float_format="%.6f")
    print("Saved at:", save_path)
  
    ax.plot(sto2mAh(df["Stoichiometry"]), df["Voltage [V]"], ls='--', label="Smoothed pOCV discharge")

    ax.legend()

    # Update and save the parameters using the new data
    param = pybamm.ParameterValues(get_parameter_values(cell_type))
    with open(os.path.join(folder, "results", "parameters_after_1.pickle"), 'wb') as param_file:
        pickle.dump(param, param_file)

# plt.show()
