"""Prepare capacity tables from verified public sodium-cell source files."""
import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pandas as pd
from openpyxl import load_workbook

from user_tools.workbench.capacity_forecast import COLUMNS, csv_bytes, parse_cycles


def native_cycles(path):
    if path.suffix.lower() == '.csv':
        frame = pd.read_csv(path, encoding='gb18030', usecols=['循环号', '电流(A)', '放电容量(Ah)'],
                            na_values=['-'], low_memory=False).apply(pd.to_numeric, errors='raise')
        final_cycle = frame['循环号'].max()
        discharge = frame[(frame['电流(A)'] < 0) & (frame['循环号'] < final_cycle)]
        values = discharge.groupby('循环号')['放电容量(Ah)'].max().dropna().items()
    else:
        book = load_workbook(path, read_only=True, data_only=True)
        try:
            sheet = book['Cycle']
            rows = iter(sheet.values)
            header = next(rows)
            cycle, q = header.index('Cycle'), header.index('CapD/Ah')
            pairs = [(row[cycle], row[q]) for row in rows if row[cycle] is not None]
            last = max(c for c, _ in pairs)
            values = [(c, v) for c, v in pairs if c < last and v is not None]
        finally:
            book.close()
    output = []
    for c, q in values:
        if int(c) != c or c < 0 or not math.isfinite(q):
            raise ValueError(f'{path.name}: invalid cycle or capacity')
        if q > 0:
            output.append((path.stem, int(c), float(q)))
    return output


def nfm_cycles(path):
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet, = [s for s in book.worksheets if s.title.endswith('Discharge')]
        rows = iter(sheet.values)
        header = next(rows)
        voltages = [i for i, value in enumerate(header) if isinstance(value, (int, float))]
        if not (math.isclose(header[voltages[0]], 2.0) and math.isclose(header[voltages[-1]], 4.0)):
            raise ValueError(f'{path.name}: unexpected discharge voltage range')
        label = 'NFM_' + sheet.title.split('|')[2].strip().replace('℃', 'C')
        output = []
        for cycle, row in enumerate(rows, 1):
            # The voltage headers are ascending. Exclude the separate SOH column.
            low, high = row[voltages[0]], row[voltages[-1]]
            if not all(isinstance(v, (float, int)) and math.isfinite(v) for v in (low, high)) or high <= low:
                raise ValueError(f'{path.name}: missing or reversed discharge capacity at row {cycle + 1}')
            output.append((label, cycle, high - low))
        return output
    finally:
        book.close()


def nims_cycles(path):
    frame = pd.read_csv(path, encoding='utf-8-sig')
    cycling = frame.loc[frame['phase'] == 'cycling',
                        ['sample_key', 'cycle_number', 'discharge_capacity_mAh']]
    return [(str(cell), int(cycle), float(capacity) / 1000)
            for cell, cycle, capacity in cycling.itertuples(index=False, name=None)
            if pd.notna(capacity) and capacity > 0]


def pisa_cycles(path):
    import h5py

    unrar = shutil.which('unrar')
    bundled = Path(sys.executable).with_name('UnRAR.exe' if os.name == 'nt' else 'unrar')
    if not unrar and bundled.is_file():
        unrar = str(bundled)
    if not unrar:
        raise ValueError('比萨大学的数据使用分卷 RAR，请将 UnRAR 加入 PATH 后生成容量表。')
    data = subprocess.check_output([unrar, 'p', '-inul', str(path), 'SIB_aging_test_data.mat'])
    with h5py.File(io.BytesIO(data)) as mat:
        half_c = mat['SIB_test_data/half_c']
        cycles = [mat[ref][()].item() for ref in half_c['AGING_CYCLE'][()].ravel()]
        capacity = [mat[ref][()].item() for ref in half_c['Q_dsch'][()].ravel()]
    if len(cycles) != len(capacity) or any(c != int(c) for c in cycles):
        raise ValueError('半倍率放电容量与老化循环号无法配对。')
    return [('Hakadi_20Ah', int(c), q) for c, q in zip(cycles, capacity)]


ADAPTERS = {
    'batterylife-naion': (
        'BatteryLife · Na-ion 逐循环放电容量', native_cycles,
        '每份原始记录作为一条轨迹。CSV 按原始循环对负电流放电步骤取最大累计放电容量。'
        'XLSX 使用 Cycle 表的 CapD/Ah。略去没有正放电容量的循环和末次可能尚未完成的循环。'),
    'nfm-temperature': (
        'NFM 4.5 Ah · 25 °C / −15 °C', nfm_cycles,
        '使用两个 NFM 文件的 Discharge 表，取 2.00–4.00 V 两端容量之差（Ah）。'
        '原表按行排列曲线，循环轴为从 1 开始的观测序号。每个温度一条轨迹，SOH 列未参与计算。'),
    'nims-additives': (
        'NIMS · NVP / 硬碳叠片电芯', nims_cycles,
        '采用发布者的 csv/cycle_summary.csv，使用 sample_key 和原始循环号。选取 phase=cycling 的正放电容量，'
        '由 mAh 换算成 Ah，化成阶段单独保留在原始数据中。'),
    'pisa-hakadi': (
        '比萨大学 · Hakadi 20 Ah', pisa_cycles,
        '25 °C，0.5C 放电。取 half_c 表的 AGING_CYCLE 和 Q_dsch（Ah）。'
        '一只电芯在第 0、250、500、750 圈有实测容量。'),
}


def prepare(root, dest, key):
    title, convert, method = ADAPTERS[key]
    folder = root / key
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf8'))
    assets = manifest['assets']
    if key == 'nims-additives':
        assets = [a for a in assets if a['path'] == 'csv/cycle_summary.csv']
    if key == 'pisa-hakadi':
        assets = sorted((a for a in assets if a['path'].endswith('.rar')), key=lambda a: a['path'])
        if [a['path'] for a in assets] != ['SIB_aging_test_data.part1.rar', 'SIB_aging_test_data.part2.rar']:
            raise ValueError('比萨大学数据缺少原始 RAR 分卷。')
    if not assets or not all(a.get('status') == 'verified' for a in assets):
        raise ValueError(f'{key} 的容量源文件尚未全部校验。')
    rows, sources = [], []
    for item in assets:
        path = folder / item['path']
        with path.open('rb') as handle:
            digest = hashlib.file_digest(handle, 'sha256').hexdigest()
        if digest != item['sha256']:
            raise ValueError(f'{path.name}: source checksum changed')
        sources.append(dict(path=item['path'], sha256=digest))
    for index, record in enumerate(sources):
        if key == 'pisa-hakadi' and index == 1:
            record['role'] = '分卷 2，随第一卷共同读取'
            continue
        converted = convert(folder / record['path'])
        record['rows'] = len(converted)
        if len(converted) >= 3:
            rows.extend(converted)
        else:
            record['excluded'] = '不足三个可用放电循环'
    raw = csv_bytes(COLUMNS, rows)
    cells = parse_cycles(raw)
    info = dict(title=title, url=manifest['url'], method=method, license=manifest.get('license'),
                axis_label='循环观测序号' if key == 'nfm-temperature' else '循环次数',
                source_files=sources, records=len(rows), series=len(cells), sha256=hashlib.sha256(raw).hexdigest())
    dest.mkdir(parents=True, exist_ok=True)
    for suffix, content in [('json', json.dumps(info, ensure_ascii=False, indent=2).encode()), ('csv', raw)]:
        path = dest / f'{key}.{suffix}'
        tmp = path.with_suffix('.' + suffix + '.tmp')
        tmp.write_bytes(content)
        os.replace(tmp, path)
    return info


if __name__ == '__main__':
    base = Path(__file__).resolve().parents[1] / 'data/public'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=base / 'sodium_ion')
    parser.add_argument('--out', type=Path, default=base / 'capacity_curves')
    parser.add_argument('--only', nargs='+', choices=ADAPTERS, default=list(ADAPTERS))
    args = parser.parse_args()
    for dataset in args.only:
        info = prepare(args.root, args.out, dataset)
        print(dataset, info['series'], 'series,', info['records'], 'cycles')
