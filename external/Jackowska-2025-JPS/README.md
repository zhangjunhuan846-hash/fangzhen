# Jackowska-2025-JPS
The Python scripts and results used in the following publication:

"Transport limitations in single-crystal NCM cathode electrodes" by
Roksana Jackowska, Nicola E. Courtier, Yongxiu Chen, Brady Planden, David Howey,
Carmen Lopez, Dimitra Spathara, and Emma Kendrick,
_Journal of Power Sources_, 2025.

## Contents
The file `Jackowska2025.py` is a [PyBaMM](https://github.com/pybamm-team/PyBaMM)
parameter set developed by [Roksana Jackowska](https://github.com/rjackowska) and
[Nicola Courtier](https://github.com/NicolaCourtier).

The `figure` files are the scripts used to generate figures for the paper written
by [Nicola Courtier](https://github.com/NicolaCourtier).
The numbers correspond to the order in which the files need to be run, not the
figure numbers in the paper. Please note that some of the figures appear in the
supporting information.

The `output.txt` contains a copy of the output generated from `run_all.sh`.

## Reproducible Research
Results were generated in the environment described by `pyproject.toml`.

The datasets are available from the University of Birmingham Research Portal.

To run the scripts, please use install using the following command:
`pip install .`

The scripts must be run in order, with those labelled `prep` run before
generating figures of the same number. The intermediate parameter files
are stored as pickle files so that the scripts can be re-run.

If you use this software, please cite it as described in the `CITATION.cff`.

## PyBaMM parameter sets
After installing the package, the PyBaMM parameter sets can be used in PyBaMM as follows:
```python
import pybamm
# Can be "Jackowska2025_2mAh_cm2" or "Jackowska2025_4mAh_cm2".
parameter_values = pybamm.ParameterValues("Jackowska2025_4mAh_cm2")
```
