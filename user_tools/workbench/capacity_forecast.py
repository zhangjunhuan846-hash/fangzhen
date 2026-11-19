"""Forecast one cell's discharge capacity from a chronological prefix."""
import base64
from bisect import bisect_right
import csv
import hashlib
from importlib import metadata
import io
import json
import math
from pathlib import Path
from statistics import fmean


COLUMNS = ('cell_id', 'cycle', 'capacity_Ah')
RESULT_COLUMNS = ('cycle', 'phase', 'measured_Ah', 'predicted_Ah', 'last_value_Ah')
INTERVAL_COLUMNS = ('lower_Ah', 'upper_Ah', 'calibration_count')
INTERVAL_LEVELS = (80, 90, 95)


def _trend(cycles, capacity, target, transform):
    x = [transform(c) for c in cycles]
    center, level = fmean(x), fmean(capacity)
    slope = sum((t - center) * (q - level) for t, q in zip(x, capacity)) / sum((t - center) ** 2 for t in x)
    return [max(0., level + slope * (transform(c) - center)) for c in target]


def linear(cycles, capacity, target):
    return _trend(cycles, capacity, target, float)


def sqrt_cycles(cycles, capacity, target):
    return _trend(cycles, capacity, target, math.sqrt)


def last_value(cycles, capacity, target):
    return [capacity[-1]] * len(target)


def numpy_quadratic(cycles, capacity, target):
    from numpy.polynomial import Polynomial
    model = Polynomial.fit(cycles, capacity, deg=min(2, len(cycles) - 1))
    return [max(0.0, value) for value in model(target)]


BUILTINS = {
    'linear': ('线性趋势', linear),
    'sqrt': ('平方根趋势', sqrt_cycles),
    'last': ('末次容量基线', last_value),
}


def algorithms():
    registry = {k: (label, fn, 'builtin-v1') for k, (label, fn) in BUILTINS.items()}
    try:
        numpy_version = metadata.version('numpy')
    except metadata.PackageNotFoundError:
        pass
    else:
        registry['numpy-polynomial'] = ('NumPy 二次多项式', numpy_quadratic, 'numpy ' + numpy_version)
    for ep in metadata.entry_points(group='fangzhen.capacity_forecasters'):
        key = f'{ep.dist.name}/{ep.name}'
        registry[key] = (ep.name, ep, ep.dist.version)
    return registry


def parse_cycles(raw):
    try:
        reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline=''))
    except UnicodeError as exc:
        raise ValueError('请将逐循环容量表保存为 UTF-8 CSV。') from exc
    if not set(COLUMNS).issubset(reader.fieldnames or ()):
        raise ValueError('CSV 需要 cell_id、cycle、capacity_Ah 三列，容量单位为 Ah。')
    cells = {}
    for row in reader:
        ident = (row['cell_id'] or '').strip()
        try:
            cycle = int(row['cycle'])
            capacity = float(row['capacity_Ah'])
            if not ident or cycle < 0 or not math.isfinite(capacity) or capacity < 0:
                raise ValueError()
        except (TypeError, ValueError) as exc:
            raise ValueError(f'第 {reader.line_num} 行的电芯、循环编号或容量无效。') from exc
        values = cells.setdefault(ident, {})
        if cycle in values:
            raise ValueError(f'电芯 {ident} 的循环 {cycle} 重复，请核对原始记录。')
        values[cycle] = capacity
    if not cells:
        raise ValueError('容量表没有数据行。')
    return cells


def catalog(project):
    datasets, sources = [], []
    if project:
        for path in sorted((Path(project) / 'data/public/capacity_curves').glob('*.csv')):
            sidecar = path.with_suffix('.json')
            info = json.loads(sidecar.read_text(encoding='utf-8')) if sidecar.exists() else {}
            datasets.append(dict(id=path.stem, title=info.get('title', path.stem), source=info.get('url', ''),
                                 method=info.get('method', ''), axis_label=info.get('axis_label', '循环次数')))
        for path in sorted((Path(project) / 'data/public/sodium_ion').glob('*/manifest.json')):
            info = json.loads(path.read_text(encoding='utf-8'))
            assets = info.get('assets', [])
            sources.append(dict(id=info['id'], title=info.get('title') or info['id'], kind=info['kind'],
                                status=info['status'], files=sum(f.get('status') == 'verified' for f in assets),
                                total=len(assets), url=info.get('url', '')))
    return dict(datasets=datasets, sources=sources,
                algorithms=[{'id': k, 'title': v[0]} for k, v in algorithms().items()])


def source_folder(project, key):
    if not project or not isinstance(key, str) or not key or Path(key).name != key or '\\' in key or '/' in key:
        raise ValueError('请选择公开数据目录中的来源。')
    root = (Path(project) / 'data/public/sodium_ion').resolve()
    path = (root / key).resolve()
    manifest = path / 'manifest.json'
    if path.parent != root or not manifest.is_file() or json.loads(manifest.read_text(encoding='utf8')).get('id') != key:
        raise ValueError('这个来源没有本地数据目录。')
    return path


def input_data(project, payload):
    if payload.get('content'):
        if payload.get('dataset'):
            raise ValueError('请选择一个容量数据来源。')
        raw = base64.b64decode(payload['content'], validate=True)
        if len(raw) > 20_000_000:
            raise ValueError('逐循环 CSV 超过 20 MB。')
        name = str(payload.get('filename') or '导入 CSV')
        return raw, dict(id='upload', title=name)
    key = payload.get('dataset')
    if not project or not isinstance(key, str) or not key or Path(key).name != key or '\\' in key or '/' in key:
        raise ValueError('请选择已接入的数据集或导入 CSV。')
    root = Path(project) / 'data/public/capacity_curves'
    paths = {p.stem: p for p in root.glob('*.csv')}
    if key not in paths:
        raise ValueError('找不到这个容量数据集。')
    path = paths[key]
    sidecar = path.with_suffix('.json')
    source = json.loads(sidecar.read_text(encoding='utf8')) if sidecar.exists() else {}
    raw = path.read_bytes()
    if source.get('sha256') and hashlib.sha256(raw).hexdigest() != source['sha256']:
        raise ValueError('容量表与来源记录的校验值不一致，请重新生成容量表。')
    return raw, {**source, 'id': key, 'title': source.get('title', key)}


def cells_info(cells):
    return [dict(id=key, first=min(values), last=max(values), observations=len(values),
                 default_cutoff=sorted(values)[min(len(values), max(2, int(.7 * len(values)))) - 1])
            for key, values in sorted(cells.items())]


def _integer(value, label):
    try:
        if isinstance(value, bool) or str(int(value)) != str(value):
            raise ValueError()
        return int(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f'{label}需要整数。') from exc


def _predict(predictor, label, cycles, capacity, target):
    try:
        values = [float(v) for v in predictor(cycles, capacity, tuple(target))]
    except Exception as exc:
        raise ValueError(f'容量算法 {label} 计算失败：{exc}') from exc
    if len(values) != len(target) or not all(math.isfinite(v) and v >= 0 for v in values):
        raise ValueError('算法需为每个目标循环返回一个有限、非负的 Ah 容量。')
    return values


def _rolling_errors(cycles, capacity, leads, predictor, label):
    """Backtest prefixes at the requested cycle offsets, wholly inside the training period."""
    first_size = max(3, (len(cycles) + 4) // 5)
    sizes = range(first_size, len(cycles))
    if len(sizes) > 64:
        sizes = [sizes[i * (len(sizes) - 1) // 63] for i in range(64)]
    errors = {lead: [] for lead in leads}
    origins, failed_fits, first_error = [], 0, None
    max_lead = max(leads)
    for size in sizes:
        origin = cycles[size - 1]
        end = bisect_right(cycles, origin + max_lead, lo=size)
        indices = [i for i in range(size, end) if cycles[i] - origin in leads]
        if not indices:
            continue
        try:
            predictions = _predict(predictor, label, cycles[:size], capacity[:size], [cycles[i] for i in indices])
        except ValueError as exc:
            # Some installed models need longer histories for a successful fit.
            failed_fits += 1
            if first_error is None:
                first_error = str(exc)
            continue
        origins.append(origin)
        for i, predicted in zip(indices, predictions):
            errors[cycles[i] - origin].append(abs(capacity[i] - predicted))
    return errors, origins, failed_fits, first_error


def _add_intervals(result, cycles, capacity, target, predictor, level):
    origin = cycles[-1]
    errors, origins, failed, first_error = _rolling_errors(
        cycles, capacity, {c - origin for c in target}, predictor, result['algorithm_name'])
    covered = 0
    future_bounded = 0
    held_widths = []
    rows = []
    for row in result['points']:
        cycle, phase, measured, estimate, _ = row
        if phase == 'train':
            rows.append((*row, None, None, None))
            continue
        scores = errors[cycle - origin]
        count = len(scores)
        rank = ((count + 1) * level + 99) // 100
        if rank > count:
            rows.append((*row, None, None, count))
            continue
        width = sorted(scores)[rank - 1]
        low, high = max(0., estimate - width), estimate + width
        if not math.isfinite(high):
            raise ValueError('预测区间上限超出数值范围。')
        rows.append((*row, low, high, count))
        if phase == 'holdout':
            covered += int(low <= measured <= high)
            held_widths.append(high - low)
        else:
            future_bounded += 1
    n_held = len(held_widths)
    result.update(columns=RESULT_COLUMNS + INTERVAL_COLUMNS, points=rows, interval=dict(
        method='rolling_origin_absolute_error_by_cycle_lead_v1', level=level, min_origins_per_lead=100 // (100 - level) - 1,
        calibration_origins=origins, failed_fits=failed, first_fit_error=first_error,
        holdout_bounded=n_held, holdout_covered=covered, future_bounded=future_bounded,
        empirical_coverage=covered / n_held if n_held else None, mean_width_Ah=fmean(held_widths) if n_held else None))


def forecast(cells, cell, algorithm, cutoff, horizon, interval_level=None):
    if cell not in cells:
        raise ValueError('请选择数据表中的电芯。')
    series = sorted(cells[cell].items())
    if len(series) < 3:
        raise ValueError('至少需要三个不同循环的容量观测。')
    cutoff = _integer(cutoff, '训练截止循环')
    horizon = _integer(horizon, '外推循环数')
    if interval_level is not None:
        interval_level = _integer(interval_level, '预测区间水平')
        if interval_level not in INTERVAL_LEVELS:
            raise ValueError('预测区间水平可选 80%、90% 或 95%。')
    if not series[0][0] <= cutoff <= series[-1][0] or not 0 <= horizon <= 5000:
        raise ValueError('截止循环需在实测范围内，额外外推允许 0 至 5000 圈。')
    train = [(c, q) for c, q in series if c <= cutoff]
    holdout = [(c, q) for c, q in series if c > cutoff]
    if len(train) < 2 or not (holdout or horizon):
        raise ValueError('至少需要两个训练观测，并留出实测循环或设置额外外推圈数。')
    models = algorithms()
    if algorithm not in models:
        raise ValueError('未知容量预测算法。')
    label, predictor, version = models[algorithm]
    target = [c for c, _ in holdout] + list(range(series[-1][0] + 1, series[-1][0] + 1 + horizon))
    cycles, capacity = zip(*train)
    if isinstance(predictor, metadata.EntryPoint):
        try:
            predictor = predictor.load()
        except Exception as exc:
            raise ValueError(f'容量算法 {label} 载入失败：{exc}') from exc
    estimates = _predict(predictor, label, cycles, capacity, target)
    last = capacity[-1]
    points = [(c, 'train', q, None, None) for c, q in train]
    for n, (c, estimate) in enumerate(zip(target, estimates)):
        measured = holdout[n][1] if n < len(holdout) else None
        points.append((c, 'holdout' if measured is not None else 'future', measured, estimate, last))
    metrics = None
    if holdout:
        errors = [pred - q for pred, (_, q) in zip(estimates, holdout)]
        metrics = dict(mae_Ah=fmean(map(abs, errors)), rmse_Ah=math.sqrt(fmean(e * e for e in errors)),
                       baseline_mae_Ah=fmean(abs(last - q) for _, q in holdout))
    result = dict(cell_id=cell, algorithm=algorithm, algorithm_name=label, algorithm_version=version,
                  cutoff=cutoff, observed_through=cycles[-1], train_points=len(train), holdout_points=len(holdout),
                  future_cycles=horizon, metrics=metrics, columns=RESULT_COLUMNS, points=points)
    if interval_level is not None:
        _add_intervals(result, cycles, capacity, target, predictor, interval_level)
    return result


def csv_bytes(columns, rows):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(columns)
    writer.writerows(rows)
    return stream.getvalue().encode('utf-8-sig')


def run(project, payload):
    raw, source = input_data(project, payload)
    cells = parse_cycles(raw)
    result = forecast(cells, payload.get('cell'), payload.get('algorithm'), payload.get('cutoff'),
                      payload.get('horizon', 0), payload.get('interval_level'))
    result.update(source=source, input_sha256=hashlib.sha256(raw).hexdigest())
    return raw, result
