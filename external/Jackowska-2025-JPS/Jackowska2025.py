import os

import numpy as np
import pybamm


def li_metal_electrolyte_exchange_current_density_Xu2019(c_e, c_Li, T):
    """
    Exchange-current density for Butler-Volmer reactions between li metal and LiPF6 in
    EC:DMC.

    References
    ----------
    .. [1] Xu, Shanshan, Chen, Kuan-Hung, Dasgupta, Neil P., Siegel, Jason B. and
    Stefanopoulou, Anna G. "Evolution of Dead Lithium Growth in Lithium Metal Batteries:
    Experimentally Validated Model of the Apparent Capacity Loss." Journal of The
    Electrochemical Society 166.14 (2019): A3456-A3463.

    Parameters
    ----------
    c_e : :class:`pybamm.Symbol`
        Electrolyte concentration [mol.m-3]
    c_Li : :class:`pybamm.Symbol`
        Pure metal lithium concentration [mol.m-3]
    T : :class:`pybamm.Symbol`
        Temperature [K]

    Returns
    -------
    :class:`pybamm.Symbol`
        Exchange-current density [A.m-2]
    """
    m_ref = 3.5e-8 * pybamm.constants.F  # (A/m2)(mol/m3) - includes ref concentrations

    return m_ref * c_Li**0.7 * c_e**0.3


# Load data in the appropriate format, different for each electrode
path = os.path.dirname(os.path.abspath(__file__))
ncm_ocp_Jackowska2025_power_data = pybamm.parameters.process_1D_data(
    "ocp_discharge.csv", path=os.path.join(path, "2mAh_cm2", "results")
)
ncm_ocp_Jackowska2025_energy_data = pybamm.parameters.process_1D_data(
    "ocp_discharge.csv", path=os.path.join(path, "4mAh_cm2", "results")
)


def ncm_ocp_Jackowska2025_power(sto):
    name, (x, y) = ncm_ocp_Jackowska2025_power_data
    return pybamm.Interpolant(x, y, sto, name=name, interpolator="linear")


def ncm_ocp_Jackowska2025_energy(sto):
    name, (x, y) = ncm_ocp_Jackowska2025_energy_data
    return pybamm.Interpolant(x, y, sto, name=name, interpolator="linear")


# Load data in the appropriate format, different for each electrode
nmc_diffusivity_Jackowska2025_power_data = pybamm.parameters.process_1D_data(
    "diffusivity_discharge.csv", path=os.path.join(path, "2mAh_cm2", "results")
)
nmc_diffusivity_Jackowska2025_energy_data = pybamm.parameters.process_1D_data(
    "diffusivity_discharge.csv", path=os.path.join(path, "4mAh_cm2", "results")
)


def nmc_diffusivity_Jackowska2025_power(sto, T):
    name, (x, y) = nmc_diffusivity_Jackowska2025_power_data
    scaling = pybamm.Parameter("Positive electrode diffusivity scaling factor")
    return scaling * pybamm.Interpolant(x, y, sto, name=name, interpolator="linear")


def nmc_diffusivity_Jackowska2025_energy(sto, T):
    name, (x, y) = nmc_diffusivity_Jackowska2025_energy_data
    scaling = pybamm.Parameter("Positive electrode diffusivity scaling factor")
    return scaling * pybamm.Interpolant(x, y, sto, name=name, interpolator="linear")


def nmc_electrolyte_exchange_current_density_Jackowska2025(c_e, c_s_surf, c_s_max, T):
    """
    Exchange-current density for Butler-Volmer reactions between NMC and LiPF6 in
    EC:EMC.

    References
    ----------
    .. [1] Xu, Shanshan, Chen, Kuan-Hung, Dasgupta, Neil P., Siegel, Jason B. and
    Stefanopoulou, Anna G. "Evolution of Dead Lithium Growth in Lithium Metal Batteries:
    Experimentally Validated Model of the Apparent Capacity Loss." Journal of The
    Electrochemical Society 166.14 (2019): A3456-A3463.

    Parameters
    ----------
    c_e : :class:`pybamm.Symbol`
        Electrolyte concentration [mol.m-3]
    c_s_surf : :class:`pybamm.Symbol`
        Particle concentration [mol.m-3]
    c_s_max : :class:`pybamm.Symbol`
        Maximum particle concentration [mol.m-3]
    T : :class:`pybamm.Symbol`
        Temperature [K]

    Returns
    -------
    :class:`pybamm.Symbol`
        Exchange-current density [A.m-2]
    """
    m_ref = pybamm.Parameter("Positive electrode reaction rate [A.m-2.(m3.mol-1)^1.5]")
    T_ref = pybamm.Parameter("Reference temperature [K]")
    E_a = pybamm.Parameter("Positive electrode reaction activation energy [J.mol-1]")
    alpha = pybamm.Parameter("Positive electrode charge transfer coefficient")

    c_s = pybamm.maximum(0, pybamm.minimum(c_s_max, c_s_surf))
    arrhenius = np.exp(E_a / pybamm.constants.R * (1 / T_ref - 1 / T))

    return (
        m_ref
        * arrhenius
        * c_s_surf**alpha
        * (c_e * (c_s_max - c_s_surf)) ** (1 - alpha)
    )


def electrolyte_diffusivity_base_Landesfeind2019(c_e, T):
    """
    Diffusivity of LiPF6 in solvent_X as a function of ion concentration and
    temperature. The data comes from [1].

    References
    ----------
    .. [1] Landesfeind, J. and Gasteiger, H.A., 2019. Temperature and Concentration
    Dependence of the Ionic Transport Properties of Lithium-Ion Battery Electrolytes.
    Journal of The Electrochemical Society, 166(14), pp.A3079-A3097.

    Parameters
    ----------
    c_e: :class:`pybamm.Symbol`
        Dimensional electrolyte concentration
    T: :class:`pybamm.Symbol`
        Dimensional temperature
    coeffs: :class:`pybamm.Symbol`
        Fitting parameter coefficients

    Returns
    -------
    :class:`pybamm.Symbol`
        Electrolyte diffusivity
    """
    c = c_e / 1000  # mol.m-3 -> mol.l
    coeffs = [1.01e03, 1.01, -1.56e03, -4.87e02]  # from Table II for EC:EMC (3:7 w:w)
    p1, p2, p3, p4 = coeffs
    A = p1 * np.exp(p2 * c)
    B = np.exp(p3 / T)
    C = np.exp(p4 * c / T)
    D_e = A * B * C * 1e-10  # m2/s

    return D_e


def electrolyte_conductivity_base_Landesfeind2019(c_e, T):
    """
    Conductivity of LiPF6 in solvent_X as a function of ion concentration and
    temperature. The data comes from [1].

    References
    ----------
    .. [1] Landesfeind, J. and Gasteiger, H.A., 2019. Temperature and Concentration
    Dependence of the Ionic Transport Properties of Lithium-Ion Battery Electrolytes.
    Journal of The Electrochemical Society, 166(14), pp.A3079-A3097.

    Parameters
    ----------
    c_e: :class:`pybamm.Symbol`
        Dimensional electrolyte concentration
    T: :class:`pybamm.Symbol`
        Dimensional temperature
    coeffs: :class:`pybamm.Symbol`
        Fitting parameter coefficients

    Returns
    -------
    :class:`pybamm.Symbol`
        Electrolyte conductivity
    """
    c = c_e / 1000  # mol.m-3 -> mol.l
    coeffs = [
        5.21e-01,
        2.28e02,
        -1.06,
        3.53e-01,
        -3.59e-03,
        1.48e-03,
    ]  # from Table II for EC:EMC (3:7 w:w)
    p1, p2, p3, p4, p5, p6 = coeffs
    A = p1 * (1 + (T - p2))
    B = 1 + p3 * pybamm.sqrt(c) + p4 * (1 + p5 * np.exp(1000 / T)) * c
    C = 1 + c**4 * (p6 * np.exp(1000 / T))
    sigma_e = A * c * B / C  # mS.cm-1

    return sigma_e / 10


# Call dict via a function to avoid errors when editing in place
def get_parameter_values(type: str):
    """
    Parameters for a NCM920305 half-cell, from the paper :footcite:t:`Jackowska2025`
    and references therein. Anode is Li metal. Separator is Celgard 2325.
    Cathode is Lithium Nickel Manganese Cobalt Oxide. Electrolyte is LiPF6.

    Parameters for Li metal anode are from the paper :footcite:t:`Xu2019`
    Parameters for a LiPF6 electrolyte are from the paper :footcite:t:`Valoen2005`

    Parameters
    ----------
    type : str
        Pass either "2mAh_cm2" or "4mAh_cm2" to get the parameter values for one of
        the validated electrode thicknesses.
    """

    # First define parameters that are the same for each electrode
    parameter_dictionary = {
        "chemistry": "lithium_ion",
        # coin cell
        "Electrode width [m]": np.sqrt(np.pi) * 0.0148 / 2,
        "Electrode height [m]": np.sqrt(np.pi) * 0.0148 / 2,
        # negative electrode, same for both electrodes
        "Negative electrode thickness [m]": 0.0001,
        "Negative electrode OCP [V]": 0.0,
        "Negative electrode conductivity [S.m-1]": 10776000.0,
        "Negative electrode OCP entropic change [V.K-1]": 0.0,
        "Lithium metal partial molar volume [m3.mol-1]": 1.3e-05,
        "Exchange-current density for lithium metal electrode [A.m-2]"
        "": li_metal_electrolyte_exchange_current_density_Xu2019,
        "Negative electrode double-layer capacity [F.m-2]": np.finfo(
            np.float64
        ).eps,  # no double layer
        # positive electrode
        "Positive electrode exchange-current density [A.m-2]"
        "": nmc_electrolyte_exchange_current_density_Jackowska2025,
        "Positive electrode charge transfer coefficient": 0.5,
        "Positive electrode diffusivity scaling factor": 1.0,
        "Positive electrode Bruggeman coefficient (electrode)": 0,
        "Maximum concentration in positive electrode [mol.m-3]": 49225,
        "Positive particle radius [m]": 1.88e-06,
        # separator, same for both electrodes
        "Separator thickness [m]": 2.5e-05,
        "Separator porosity": 0.39,
        "Separator Bruggeman coefficient (electrolyte)": 1.5,
        "Separator Bruggeman coefficient (electrode)": 0,
        # electrolyte, same for both electrodes
        "Initial concentration in electrolyte [mol.m-3]": 1000.0,
        "Cation transference number": 0.38,
        "Electrolyte diffusivity [m2.s-1]": electrolyte_diffusivity_base_Landesfeind2019,
        "Electrolyte conductivity [S.m-1]": electrolyte_conductivity_base_Landesfeind2019,
        "Thermodynamic factor": 1.0,
        # experiment
        "Ambient temperature [K]": 298.15,
        "Reference temperature [K]": 298.15,
        "Number of electrodes connected in parallel to make a cell": 1.0,
        "Number of cells connected in series to make a battery": 1.0,
        "Lower voltage cut-off [V]": 2.5,
        "Upper voltage cut-off [V]": 4.2,
        "Open-circuit voltage at 0% SOC [V]": pybamm.Parameter(
            "Lower voltage cut-off [V]"
        ),
        "Open-circuit voltage at 100% SOC [V]": pybamm.Parameter(
            "Upper voltage cut-off [V]"
        ),
        "Initial concentration in positive electrode [mol.m-3]": 5e3,
        "Initial temperature [K]": 298.15,
        # for calculation of electrode coating weight
        "Electrolyte density [kg.m-3]": 1.203e3,
        "Positive electrode active material density [kg.m-3]": 4.796e03,
        "Positive electrode carbon-binder density [kg.m-3]": 1.86e3,
        # citations
        "citations": ["Jackowska2025", "Xu2019", "Landesfeind2019"],
    }

    # Now define parameters that are different for each electrode
    if type == "2mAh_cm2":
        parameter_dictionary.update(
            {
                # cell
                "Nominal cell capacity [A.h]": 0.003112,
                "Current function [A]": 0.003112,
                "Contact resistance [Ohm]": 22.4,
                # positive electrode
                "Positive electrode OCP [V]": ncm_ocp_Jackowska2025_power,
                "Positive electrode OCP entropic change [V.K-1]": 0.0,
                "Positive electrode thickness [m]": 3.25e-05,
                "Positive electrode conductivity [S.m-1]": 0.416,
                "Positive particle diffusivity [m2.s-1]": nmc_diffusivity_Jackowska2025_power,
                "Positive electrode porosity": 0.259,
                "Positive electrode active material volume fraction": 0.661,
                "Positive electrode Bruggeman coefficient (electrolyte)": 1.90,
                "Positive electrode double-layer capacity [F.m-2]": 6.86e-3,
                "Positive electrode reaction rate [A.m-2.(m3.mol-1)^1.5]": 1.037e-06,
                "Positive electrode reaction activation energy [J.mol-1]": 56410,
            }
        )

    elif type == "4mAh_cm2":
        parameter_dictionary.update(
            {
                # cell
                "Nominal cell capacity [A.h]": 0.006636,
                "Current function [A]": 0.006636,
                "Contact resistance [Ohm]": 23.4,
                # positive electrode
                "Positive electrode OCP [V]": ncm_ocp_Jackowska2025_energy,
                "Positive electrode OCP entropic change [V.K-1]": 0.0,
                "Positive electrode thickness [m]": 7.3e-05,
                "Positive electrode conductivity [S.m-1]": 0.427,
                "Positive particle diffusivity [m2.s-1]": nmc_diffusivity_Jackowska2025_energy,
                "Positive electrode porosity": 0.299,
                "Positive electrode active material volume fraction": 0.625,
                "Positive electrode Bruggeman coefficient (electrolyte)": 2.12,
                "Positive electrode double-layer capacity [F.m-2]": 3.74e-3,
                "Positive electrode reaction rate [A.m-2.(m3.mol-1)^1.5]": 0.435e-06,
                "Positive electrode reaction activation energy [J.mol-1]": 46040,
            }
        )

    else:
        raise ValueError('Unrecognised type. Please choose "2mAh_cm2" or "4mAh_cm2".')

    return parameter_dictionary


def get_parameter_values_2mAh_cm2():
    return get_parameter_values("2mAh_cm2")


def get_parameter_values_4mAh_cm2():
    return get_parameter_values("4mAh_cm2")
