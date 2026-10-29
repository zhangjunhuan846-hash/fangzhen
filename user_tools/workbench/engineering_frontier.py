"""Upstream MOBO-OSD, robust MFBO and CAMO with an observation-blind ask boundary."""
import time
from types import SimpleNamespace
import numpy as np

from user_tools.workbench.engineering_common import finish, save
from user_tools.workbench.engineering_contracts import csv_rows, finite
from user_tools.workbench.engineering_vendor import upstream


def observations(config, raw):
    if raw is None:
        rng = np.random.default_rng(config['seed'])
        rows = []
        for i in range(32):
            x = rng.uniform(0, 1, 2); f = [0.3, 0.6, 1.][i % 3]
            completed = i < 18
            rows.append(dict(candidate_id=str(i), x1=x[0], x2=x[1], fidelity=f, cost=f+.05,
                status='completed' if completed else 'candidate',
                objective1=-(x[0]-.2)**2-(x[1]-.3)**2+.1*(1-f) if completed else '',
                objective2=-(x[0]-.8)**2-(x[1]-.7)**2 if completed else ''))
    else:
        rows = csv_rows(raw)
    ids = [str(r['candidate_id']) for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError('candidate_id必须唯一。')
    xs, ys, fs, costs, done, pool = [], [], [], [], [], []
    for i, row in enumerate(rows):
        x = [finite(row[k], k, 0, 1) for k in ['x1', 'x2']]
        f = finite(row.get('fidelity', 1), 'fidelity', .01, 1)
        cost = finite(row.get('cost', f+.05), 'cost', 1e-6, 1e9)
        if row['status'] not in ['completed', 'candidate', 'pending']:
            raise ValueError('未知status。')
        if row['status'] != 'completed' and any(row.get(k, '') not in ['', None] for k in ['objective1', 'objective2']):
            raise ValueError('未测/pending候选的目标必须留空，拒绝读取未来标签。')
        xs.append(x); fs.append(f); costs.append(cost)
        if row['status'] == 'completed':
            done.append(i)
            ys.append([finite(row['objective1'], 'objective1'), finite(row.get('objective2', 0) or 0, 'objective2')])
        elif row['status'] == 'candidate':
            pool.append(i)
    if not 6 <= len(done) <= 150 or len(rows) > 1000:
        raise ValueError('需要6–150条完成记录，候选总数不超过1000。')
    return rows, np.asarray(xs), np.asarray(ys), np.asarray(fs), np.asarray(costs), np.asarray(done), np.asarray(pool, dtype=int)


def ask_osd(config, out, x, y):
    audit = upstream('mobo-osd', out)
    from sklearn.preprocessing import StandardScaler
    from pymoo.util.ref_dirs import get_reference_directions
    from mobo_osd.mobo_osd import MOBO_OSD
    from mobo_osd.gp import train_gp, estimate_mean_and_std
    from mobo_osd.pareto_estimation import ParetoEstimationSet, FirstOrderApproximation
    obj = SimpleNamespace(input_dims=2, num_objectives=2, num_constraints=0,
                          bounds=np.asarray([[0, 1], [0, 1]]), ref_point=np.max(-y, axis=0)+np.ptp(y, axis=0)*.1)
    m = MOBO_OSD(obj, len(x)+config['batch_size'], batch_size=config['batch_size'], n_beta=config['n_beta'])
    m.observed_x, m.observed_f = x, -y  # The author minimizes; workstation objectives maximize.
    scaler = StandardScaler().fit(-y)
    m.observed_f_scaled = scaler.transform(-y)
    boundary = m._compute_boundary_points(); direction = m._compute_osd(boundary)
    if not np.isfinite(direction).all():
        raise ValueError('MOBO-OSD需要有变化的双目标观测。')
    models = train_gp(x, m.observed_f_scaled)
    candidates, labels = [], []
    for i, u in enumerate(get_reference_directions('energy', 2, config['n_beta'], seed=config['seed']) @ boundary):
        # The author's subproblem already invokes FirstOrderApproximation.do().
        patch = m._optimize_osb_subprob(2, u, direction, models, x, m.observed_f_scaled)
        candidates.extend(np.atleast_2d(patch)); labels.extend([i]*len(np.atleast_2d(patch)))
    candidates = np.asarray(candidates)
    predictions, _ = estimate_mean_and_std(candidates, models)
    pfs = ParetoEstimationSet(n=100, xs=x, ys=m.observed_f_scaled, boundary_points=boundary, ortho_direction=direction)
    pfs.insert_data(candidates, predictions, labels); pfs.update_cell()
    cx = np.concatenate([a for a in pfs.x if len(a)], axis=0)
    lab = np.concatenate([a for a in pfs.ids if len(a)], axis=0)
    cx, lab = cx[lab >= 0], lab[lab >= 0]
    if len(set(lab)) < config['batch_size']:
        raise ValueError('Pareto探索片数量不足以生成指定批次，请减少batch_size。')
    chosen, _ = m.select_by_hvi_kb(cx, models, lab, scaler.transform(obj.ref_point.reshape(1, -1)).ravel())
    predicted = -scaler.inverse_transform(estimate_mean_and_std(chosen, models)[0])
    return [dict(candidate_id='proposal-'+str(i+1), x1=p[0], x2=p[1], fidelity=1.,
                 predicted_objective1=q[0], predicted_objective2=q[1]) for i, (p, q) in enumerate(zip(chosen, predicted))], audit, {
        'scope': '作者GP、正交子问题、一阶Pareto扩展、集合更新及qHVI批选真实执行；桌面端顺序执行单次ask，目标最大化转换为作者最小化。',
        'pareto_candidates': len(cx), 'exploration_patches': len(set(lab))}


def ask_rmfbo(config, out, x, y, f, costs, done, pool):
    import torch
    from botorch.sampling.normal import SobolQMCNormalSampler
    audit = upstream('rMFBO', out)
    from src.model import init_model_srdk, convert_to_nn_and_base_kernel
    from src.acquisition import qLowerConfidenceBound, qConfidenceInterval, qConstrainedCI_m_UCB
    from src.utility import monte_carlo_entropy, excessive_risk_reduction_rate, rbf_kernel_variance_reduction_rate
    levels = np.unique(f)
    if len(levels) < 2 or 1. not in f[done] or 1. not in f[pool]:
        raise ValueError('rMFBO至少两档保真度，训练及候选均需最高保真度1。')
    if config.get('same_quantity_across_fidelities') is not True:
        raise ValueError('请声明各保真度是同一物理量same_quantity_across_fidelities=true。')
    tx = torch.tensor(np.column_stack([x[done], f[done]]), dtype=torch.double)
    ty = torch.tensor(y[:, :1], dtype=torch.double)
    query = torch.tensor(np.column_stack([x[pool], f[pool]]), dtype=torch.double)
    options = dict(training_iter=config['train_iterations'], power_iterations=10, verbose=False, train_loss='mll')
    _, model = init_model_srdk(tx, ty, **options)
    model.eval(); model.likelihood.eval()
    base, projected = convert_to_nn_and_base_kernel(model, query)
    base.eval(); base.likelihood.eval()
    sampler = SobolQMCNormalSampler(sample_shape=torch.Size([128]), seed=config['seed'])
    with torch.no_grad():
        hf = f[pool] == 1
        lcb = qLowerConfidenceBound(base, beta=2., sampler=sampler)(projected.unsqueeze(1))
        ci = qConfidenceInterval(base, beta=2., sampler=sampler)(projected.unsqueeze(1))
        threshold = min(float(lcb[hf].max()), float(base.train_targets[tx[:, -1] == 1].max()))
        acq = qConstrainedCI_m_UCB([base], [threshold], return_UCB=True, beta=2., constrained=False, sampler=sampler)
        scores = acq(projected.unsqueeze(1)).numpy()
    lengths = []
    for _ in range(4):
        _, sample = init_model_srdk(tx, ty, **options)
        lengths.append(torch.ceil(sample.covar_module.base_kernel.lengthscale.detach().mean()*1000)/1000)
    entropy = monte_carlo_entropy(torch.stack(lengths))
    counts = torch.tensor([sum(f[done] == v) for v in levels])
    level_costs = np.array([np.median(costs[f == v]) for v in levels])
    learning = np.array([float(torch.sqrt(entropy)*excessive_risk_reduction_rate(counts, i, 1.))/level_costs[i] for i in range(len(levels))])
    rbf = float(rbf_kernel_variance_reduction_rate(len(done), 3, max(float(ci[hf].max()), .1)))/level_costs[-1]
    best = done[np.where(f[done] == 1)[0][np.argmax(y[f[done] == 1, 0])]]
    dist = np.linalg.norm(np.column_stack([x[pool], f[pool]])-np.r_[x[best], 1.], axis=1)
    roi = hf & (dist < np.quantile(dist, .5))
    if not roi.any(): roi = hf
    selected_level = 1. if rbf >= learning.max() else float(levels[learning.argmax()])
    available = np.where((f[pool] == selected_level) & (roi if selected_level == 1 else True))[0]
    if not len(available):
        raise ValueError('选定保真度没有未测候选，请补充候选池。')
    # Author uses a random low-fidelity spatial query; preserve that policy on the available pool.
    j = available[np.argmax(scores[available])] if selected_level == 1 else np.random.choice(available)
    return int(pool[j]), scores, audit, {'lengthscale_entropy': float(entropy), 'cost_aware_rates': learning,
        'cost_aware_rbf_rate': rbf, 'selected_fidelity': selected_level, 'roi_count': int(roi.sum()),
        'scope': '作者谱正则深核GP、投影RBF、置信区间采集、局部ROI及熵/风险成本分配；固定候选池单次ask适配。显式选择MLL损失；没有调用会偷看候选真值的初始化函数。'}


def ask_camo(config, out, x, y, f, costs, done, pool):
    import torch
    audit = upstream('CAMO', out)
    from GaussianProcess.kernel import ARDKernel
    from FidelityFusion_Models.CMF_CAR import ContinuousAutoRegression_large
    from FidelityFusion_Models.MF_data import MultiFidelityDataManager
    if len(np.unique(f[done])) < 2 or config.get('same_quantity_across_fidelities') is not True:
        raise ValueError('CAMO需要多保真训练及same_quantity_across_fidelities=true。')
    tx = torch.tensor(np.column_stack([x[done], 1+f[done]]), dtype=torch.double)
    mean, std = float(y[:, 0].mean()), max(float(y[:, 0].std()), 1e-8)
    ty = torch.tensor((y[:, :1]-mean)/std, dtype=torch.double)
    dm = MultiFidelityDataManager([dict(raw_fidelity_name='0', fidelity_indicator=0, X=tx, Y=ty)])
    model = ContinuousAutoRegression_large(ARDKernel(2), b_init=1.).double()
    optimizer = torch.optim.Adam(model.parameters(), lr=.015)
    losses = []
    for _ in range(config['train_iterations']):
        optimizer.zero_grad(); loss = model.cigp.negative_log_likelihood(tx, ty)
        if not torch.isfinite(loss): raise ValueError('CAMO负对数似然不有限。')
        loss.backward(); optimizer.step()
        with torch.no_grad(): model.b.clamp_(.05, 3.)
        losses.append(float(loss.detach()))
    # Use actual CAMO FiDE/CAR posterior. Finite-pool stochastic KG replaces the author's
    # mean-fantasy/retrain example, avoids a double fidelity offset and any true-label oracle.
    target = torch.tensor(np.column_stack([x[pool], np.full(len(pool), 2.)]), dtype=torch.double)
    query = torch.tensor(np.column_stack([x[pool], 1+f[pool]]), dtype=torch.double)
    with torch.no_grad():
        mu, cov = model(dm, torch.cat([target, query]), normal=False)
        mu = mu.ravel(); n = len(pool)
        latent = cov - model.cigp.log_beta.exp().pow(-1)*torch.eye(2*n, dtype=torch.double)
        eig = float(torch.linalg.eigvalsh((latent+latent.T)/2).min())
        if eig < -1e-6: raise ValueError('CAMO后验协方差非半正定。')
        # Symmetric normal quadrature; includes unchanged posterior as an available decision.
        from scipy.special import ndtri
        normal = torch.tensor(ndtri((np.arange(64)+.5)/64), dtype=torch.double)
        cross = latent[:n, n:]
        sd = cov.diag()[n:].clamp_min(1e-12).sqrt()
        future = mu[:n, None, None] + cross[:, :, None]/sd[None, :, None]*normal[None, None, :]
        gain = (future.max(dim=0).values.mean(dim=-1)-mu[:n].max()).clamp_min(0)
        scores = gain.numpy()*std/costs[pool]
    save(out/'camo_training.json', {'loss': losses, 'minimum_posterior_eigenvalue': eig})
    return int(pool[np.argmax(scores)]), scores, audit, {'scope': '真实作者连续保真FiDE/CAR核训练及后验；采集为固定超参数的有限池随机知识梯度适配，按声明成本归一。训练参数b约束为[0.05,3]。',
         'minimum_posterior_eigenvalue': eig, 'negative_log_likelihood': losses[-1]}


def run_frontier(config, out, raw=None):
    import torch
    from pathlib import Path
    out = Path(out); start = time.perf_counter()
    np.random.seed(config['seed']); torch.manual_seed(config['seed']); torch.set_num_threads(1)
    rows, x, y, f, costs, done, pool = observations(config, raw)
    alg = config['algorithm']
    if alg == 'mobo_osd':
        # Single-fidelity MOBO only accepts completed high-fidelity measurements.
        if np.any(f[done] != 1):
            if raw is not None: raise ValueError('MOBO-OSD完成记录必须全为最高保真度1。')
            f[:] = 1
        recommendations, audit, details = ask_osd(config, out, x[done], y)
        scored = recommendations
    else:
        if not len(pool): raise ValueError('需要未测candidate。')
        idx, scores, audit, details = (ask_rmfbo if alg == 'rmfbo' else ask_camo)(config, out, x, y, f, costs, done, pool)
        recommendations = [dict(candidate_id=str(rows[idx]['candidate_id']), x1=x[idx, 0], x2=x[idx, 1], fidelity=f[idx])]
        scored = [dict(candidate_id=str(rows[i]['candidate_id']), x1=x[i, 0], x2=x[i, 1], fidelity=f[i], acquisition=s) for i, s in zip(pool, scores)]
    save(out/'frontier_manifest.json', {'algorithm': alg, 'observations': [rows[i] for i in done],
         'pending_ids': [r['candidate_id'] for r in rows if r['status']=='pending'],
         'recommendations': recommendations, 'upstream': audit, 'details': details, 'future_labels_read': False})
    return finish(config, out, {'kind': 'engineering', 'title': {'mobo_osd': 'MOBO-OSD 正交Pareto批选', 'rmfbo': 'rMFBO 鲁棒多保真选点', 'camo': 'CAMO 连续保真选点'}[alg],
        'engine': audit['repository'], 'algorithm': alg, 'recommendation': recommendations[0], 'recommendations': recommendations,
        'metrics': dict(completed=len(done), candidates=len(pool), recommendations=len(recommendations), elapsed_s=time.perf_counter()-start),
        'details': details, 'upstream_commit': audit['commit']}, scored, packages=['torch', 'botorch', 'gpytorch', 'pymoo'])
