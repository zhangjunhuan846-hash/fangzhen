import pybamm

# Load the parameter set. Can be "Jackowska2025_2mAh_cm2" or "Jackowska2025_4mAh_cm2".
parameter_values = pybamm.ParameterValues("Jackowska2025_4mAh_cm2")

# Get the model
options = {
    "working electrode": "positive",
    "surface form": "differential",
    "contact resistance": "true",
}
model = pybamm.lithium_ion.DFN(options)

# Define an experiment
experiment = pybamm.Experiment(["Discharge at C/20 until 2.5 V", "Rest for 30 minutes"])

# Run the simulation
simulation = pybamm.Simulation(
    model, experiment=experiment, parameter_values=parameter_values
)
simulation.solve()

# Plot the results
simulation.plot(
    [
        "Current [A]",
        "Voltage [V]",
        "X-averaged positive particle surface concentration [mol.m-3]",
    ]
)
