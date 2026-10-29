import base64
import csv
import hashlib
import io
import json
import math
from pathlib import Path

import pytest

from user_tools.workbench.eis_fit import prepare_eis_fit, run_eis_fit
from user_tools.workbench.physics_worker import run
from user_tools.workbench.server import Application


def spectrum(parameters=(.012, .055, 120.), *, scale=1., negative=False, corrupt=False):
    """Independent analytic RC oracle; no impedance.py forward model."""
    text = io.StringIO()
    writer = csv.writer(text)
    writer.writerow(['frequency_Hz', 'Z_real_ohm', 'Z_imag_ohm'])
    for i in range(81):
        frequency = 10 ** (-4 + i / 10)
        z = complex(parameters[0])
        for resistance, capacitance in zip(parameters[1::2], parameters[2::2]):
            z += resistance / (1 + 2j * math.pi * frequency * resistance * capacitance)
        if corrupt:
            z += (.006 + .004j) * (-1 if i % 2 else 1)
        writer.writerow([frequency, z.real * scale, z.imag * scale * (-1 if negative else 1)])
    return text.getvalue().encode()


def execute(tmp_path, raw, **options):
    pytest.importorskip('impedance')
    source = tmp_path / 'source.csv'
    source.write_bytes(raw)
    config = {'mode': 'eis_fit', 'source_path': str(source),
              'source_sha256': hashlib.sha256(raw).hexdigest(), 'eis_config': options}
    return run(config, tmp_path / 'result')


@pytest.mark.parametrize('parameters,circuit', [((.012, .055, 120.), '1rc'),
                                               ((.01, .03, 10., .05, 3000.), '2rc')])
def test_known_rc_recovery_with_real_backend_and_full_exports(tmp_path, parameters, circuit):
    result = execute(tmp_path, spectrum(parameters), circuit=circuit)
    assert result['rmse_complex_ohm'] < 1e-7
    found = {p['name']: p['value'] for p in result['parameters']}
    assert found['R0'] == pytest.approx(parameters[0], rel=1e-3)
    recovered_pairs = sorted((found[f'R{i}'], found[f'C{i}']) for i in range(1, len(parameters) // 2 + 1))
    for recovered, expected in zip(recovered_pairs, sorted(zip(parameters[1::2], parameters[2::2]))):
        assert recovered == pytest.approx(expected, rel=1e-3)
    assert result['point_count'] == 81
    assert result['material_validation'] is False
    assert result['parameter_identifiability'] == 'not_assessed'
    assert result['linearity_assessed'] is False
    assert result['runtime_versions']['impedance'] == '1.7.1'
    folder = tmp_path / 'result'
    assert len(list(csv.DictReader((folder / 'spectrum_fit.csv').open(encoding='utf-8-sig')))) == 81
    assert json.loads((folder / 'ui_result.json').read_text())['result'] == result
    assert (folder / 'parameters.csv').is_file()
    assert len(result['eis_spectra']) == 3
    assert result['lin_kk']['status'] == 'within_tolerance'
    assert result['lin_kk']['order_selection'] == 'fixed'


def test_milliohm_negative_imaginary_conversion_reaches_same_fit(tmp_path):
    result = execute(tmp_path, spectrum(scale=1000, negative=True),
                     impedance_unit='mohm', imag_is_negative=True)
    assert result['parameters'][0]['value'] == pytest.approx(.012, rel=1e-3)
    assert result['parameters'][1]['value'] == pytest.approx(.055, rel=1e-3)
    assert result['imag_sign_converted'] is True


def test_inconsistent_spectrum_is_reported_without_claiming_validation(tmp_path):
    result = execute(tmp_path, spectrum(corrupt=True), kk_tolerance=.001)
    assert result['lin_kk']['status'] == 'above_tolerance'
    assert result['lin_kk']['relative_rms'] > .001
    assert not result['material_validation']


def test_duplicate_frequencies_and_mixed_spectra_require_explicit_handling():
    raw = spectrum()
    with pytest.raises(ValueError, match='重复频率'):
        prepare_eis_fit(raw + raw.splitlines(keepends=True)[1], {})
    rows = list(csv.DictReader(io.StringIO(raw.decode())))
    text = io.StringIO()
    writer = csv.DictWriter(text, fieldnames=[*rows[0], 'spectrum_id'])
    writer.writeheader()
    for label in ['A', 'B']:
        writer.writerows([{**row, 'spectrum_id': label} for row in rows])
    grouped = text.getvalue().encode()
    with pytest.raises(ValueError, match='多条谱'):
        prepare_eis_fit(grouped, {})
    assert len(prepare_eis_fit(grouped, {'spectrum_id': 'B'})['points']) == 81


@pytest.mark.parametrize('config', [{'circuit': '__import__("os")'}, {'weighting': 'other'},
                                  {'initial_guess': [1, 2, 0]}, {'kk_tolerance': float('nan')}])
def test_invalid_scientific_configuration_is_rejected(config):
    with pytest.raises(ValueError):
        prepare_eis_fit(spectrum(), config)


def test_queued_source_hash_is_enforced(tmp_path):
    pytest.importorskip('impedance')
    path = tmp_path / 'source.csv'
    path.write_bytes(spectrum())
    with pytest.raises(ValueError, match='校验失败'):
        run_eis_fit({'source_path': str(path), 'source_sha256': '0' * 64, 'eis_config': {}}, tmp_path)


def test_server_keeps_original_input_and_normalized_job_config(tmp_path, monkeypatch):
    import user_tools.workbench.server as server
    app = Application(tmp_path / 'data', project=Path(__file__).resolve().parents[1])
    # Queue transport is checked here; the real WSL process is exercised in HTTP smoke.
    monkeypatch.setattr(server, 'wsl_path', lambda path: str(path))
    monkeypatch.setattr(server.threading.Thread, 'start', lambda self: None)
    raw = spectrum()
    job = app.start_job({'workspace': app.store.list()[0]['id'], 'mode': 'eis_fit',
                         'content': base64.b64encode(raw).decode(), 'eis_config': {'circuit': '1rc'}})
    folder = app.data / 'jobs' / job['id']
    config = json.loads((folder / 'config.json').read_text())
    assert (folder / 'source.csv').read_bytes() == raw
    assert config['source_sha256'] == hashlib.sha256(raw).hexdigest()
    assert config['eis_config']['circuit'] == '1rc'
    assert job['model'] == 'impedance.py / RC'
