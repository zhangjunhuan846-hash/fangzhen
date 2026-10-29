"""Auditable finite-pool BO adapters using real BoTorch acquisition functions."""
import math
import time
import numpy as np

from user_tools.workbench.engineering_common import finish, save
from user_tools.workbench.engineering_contracts import csv_rows, finite


def dataset(config, raw):
    multi_fidelity = config['algorithm'] in ['mfkg', 'mfmes']
    if raw is None:
        rng = np.random.default_rng(config['seed'])
        rows = []
        for i in range(18):
            x = rng.uniform(0, 1, 2)
            fidelity = (.4 if i % 2 else 1.) if multi_fidelity else 1.
            completed = i < 10
            rows.append({'candidate_id': f'demo-{i:02}', 'x1': x[0], 'x2': x[1],
                         'fidelity': fidelity, 'status': 'completed' if completed else 'candidate',
                         'objective1': 1 - np.sum((x-[.3, .7])**2) + .15*(1-fidelity) if completed else '',
                         'objective2': 1 - np.sum((x-[.8, .2])**2) if completed else ''})
    else:
        rows = csv_rows(raw)
    required = {'candidate_id', 'x1', 'x2', 'objective1', 'objective2', 'status'}
    if not required <= set(rows[0]) or len(rows) > 250:
        raise ValueError('选点CSV需candidate_id,x1,x2,objective1,objective2,status；最多250行，两目标均最大化。')
    if multi_fidelity and 'fidelity' not in rows[0]:
        raise ValueError('多保真需要fidelity列(0,1]，目标保真度为1。')
    seen = set()
    completed, candidates, pending = [], [], []
    coordinates = set()
    for row in rows:
        ident = str(row['candidate_id']).strip()
        if not ident or ident in seen:
            raise ValueError('candidate_id必须非空且唯一。')
        seen.add(ident)
        x = [finite(row[k], k) for k in ['x1', 'x2']]
        if multi_fidelity:
            x.append(finite(row['fidelity'], 'fidelity', .001, 1))
        if tuple(x) in coordinates:
            raise ValueError('候选坐标重复；请先合并重复测量并明确噪声。')
        coordinates.add(tuple(x))
        item = {'candidate_id': ident, 'x': x}
        if row['status'] == 'completed':
            item['y'] = [finite(row[k], k) for k in ['objective1', 'objective2']]
            completed.append(item)
        elif row['status'] in ['candidate', 'pending']:
            if any(str(row[k]).strip() for k in ['objective1', 'objective2']):
                raise ValueError('未测/待回传候选必须清空目标列，防止未来标签泄漏。')
            (candidates if row['status'] == 'candidate' else pending).append(item)
        else:
            raise ValueError('status只能completed/candidate/pending。')
    if len(completed) < 5 or not candidates:
        raise ValueError('至少5个已完成样本和1个未测候选。')
    if multi_fidelity:
        fidelities = {r['x'][-1] for r in completed}
        if len(fidelities) < 2 or 1. not in fidelities:
            raise ValueError('训练集需至少两个保真度，并包含目标保真度1的数据。')
        if raw is not None and config.get('same_quantity_across_fidelities') is not True:
            raise ValueError('请声明same_quantity_across_fidelities=true并使用相同物理量、协议和归一口径。')
    return completed, candidates, pending


def run_optimize(config, out, raw=None):
    import torch
    from botorch.models import SingleTaskGP, ModelListGP
    from botorch.models.transforms.outcome import Standardize
    from botorch.fit import fit_gpytorch_mll
    from gpytorch.mlls import ExactMarginalLogLikelihood
    from botorch.sampling.normal import SobolQMCNormalSampler
    from botorch.utils.multi_objective.pareto import is_non_dominated
    torch.set_num_threads(1)
    torch.manual_seed(config['seed'])
    tick = time.perf_counter()
    completed, candidates, pending = dataset(config, raw)
    algorithm = config['algorithm']
    tx = torch.tensor([r['x'] for r in completed], dtype=torch.double)
    cx = torch.tensor([r['x'] for r in candidates], dtype=torch.double)
    px = torch.tensor([r['x'] for r in pending], dtype=torch.double) if pending else None
    y = torch.tensor([r['y'] for r in completed], dtype=torch.double)
    all_x = torch.cat([tx, cx] + ([px] if px is not None else []))
    lower, upper = all_x.min(0).values, all_x.max(0).values
    if torch.any(upper <= lower):
        raise ValueError('每个输入维度均需有变化。')
    if algorithm in ['mfkg', 'mfmes']:
        lower[-1], upper[-1] = 0., 1.
    span = upper-lower
    tx, cx = (tx-lower)/span, (cx-lower)/span
    px = (px-lower)/span if px is not None else None
    bounds = torch.stack([torch.zeros_like(lower), torch.ones_like(upper)])
    noise = finite(config.get('observation_noise_variance', .0001), 'observation_noise_variance', 1e-10, 100)
    models = []
    prior_details = None
    if algorithm == 'dynmeanbo':
        from gpytorch.means import Mean
        prior = config.get('expert_prior', {'center': [.35, .65], 'width': [.2, .2],
                         'A': 1., 'B': 0., 'gamma': 1., 'initial_design': 5,
                         'source': 'declared synthetic expert belief'} if raw is None else None)
        if not isinstance(prior, dict) or not prior.get('source'):
            raise ValueError('DynMeanBO需要expert_prior，明确center/width(归一化域)、A/B/gamma、initial_design及先验source。')
        center = [finite(v, 'prior center', 0, 1) for v in prior.get('center', [])]
        width = [finite(v, 'prior width', .01, 2) for v in prior.get('width', [])]
        if len(center) != 2 or len(width) != 2:
            raise ValueError('先验center和width各需两个归一化坐标。')
        a, b = finite(prior.get('A', 1), 'prior A', -100, 100), finite(prior.get('B', 0), 'prior B', -100, 100)
        gamma = finite(prior.get('gamma', 1), 'prior gamma', .0001, 100)
        n0 = finite(prior.get('initial_design', 5), 'initial_design', 1, len(completed))
        if int(n0) != n0:
            raise ValueError('initial_design必须为整数。')
        iteration = len(completed)-int(n0)
        weight = math.exp(-gamma*iteration)
        class DecayingExpertMean(Mean):
            def __init__(self):
                super().__init__()
                self.register_buffer('center', torch.tensor(center, dtype=torch.double))
                self.register_buffer('width', torch.tensor(width, dtype=torch.double))
            def forward(self, X):
                log_density = -.5*((X-self.center)/self.width).square().sum(-1)
                log_density -= self.width.log().sum()+math.log(2*math.pi)
                return weight*(a*log_density.exp()+b)
        prior_details = {**prior, 'iteration': iteration, 'decay_weight': weight,
             'equation': 'm_t(x)=exp(-gamma*t)*(A*NormalPDF(x;center,width)+B)',
             'scope': 'ICLR2026 DynMeanBO核心动态均值公式的现代BoTorch适配；固定历史设计，不重跑论文混合初始化或全部基准。',
             'author_code': 'https://github.com/quchongqi/DynMeanBO/blob/main/botorch/benchmarking/mapping/gp_priors.py'}
    if algorithm not in ['mfkg', 'mfmes']:
        for j in range(2):
            kwargs = {'mean_module': DecayingExpertMean()} if algorithm == 'dynmeanbo' and j == 0 else {}
            model = SingleTaskGP(tx, y[:, j:j+1], train_Yvar=torch.full_like(y[:, j:j+1], noise),
                                 outcome_transform=Standardize(m=1), **kwargs)
            fit_gpytorch_mll(ExactMarginalLogLikelihood(model.likelihood, model),
                              optimizer_kwargs={'options': {'maxiter': 60}})
            models.append(model)
        model = ModelListGP(*models)
    scores = None
    details = {}
    stop_reason = None
    reference = config.get('reference', [0., 0.] if raw is None else None)
    if algorithm in ['qlognehvi', 'hvkg']:
        if not isinstance(reference, list) or len(reference) != 2:
            raise ValueError('双目标需事先声明reference:[目标1下界,目标2下界]，均最大化。')
        reference = torch.tensor([finite(v, 'reference') for v in reference], dtype=torch.double)
        if not torch.any(torch.all(y > reference, dim=1)):
            raise ValueError('参考点应被至少一个已完成观测严格支配。')
    if algorithm == 'qlognehvi':
        from botorch.acquisition.multi_objective.logei import qLogNoisyExpectedHypervolumeImprovement
        acquisition = qLogNoisyExpectedHypervolumeImprovement(model, reference.tolist(), tx,
                         sampler=SobolQMCNormalSampler(torch.Size([64])), X_pending=px, prune_baseline=False)
        with torch.no_grad():
            scores = acquisition(cx[:, None, :])
        details['score_scale'] = 'log expected noisy hypervolume improvement'
    elif algorithm == 'hvkg':
        from botorch.acquisition.multi_objective.hypervolume_knowledge_gradient import qHypervolumeKnowledgeGradient
        from botorch.acquisition.acquisition import AcquisitionFunction
        from botorch.optim import optimize_acqf
        from botorch.utils.multi_objective.hypervolume import Hypervolume
        with torch.no_grad():
            mean = model.posterior(tx).mean
            current = Hypervolume(reference).compute(mean[is_non_dominated(mean)])
        hvkg = qHypervolumeKnowledgeGradient(model, reference, num_fantasies=2, num_pareto=2,
                    current_value=torch.tensor(current, dtype=torch.double), X_pending=px)
        # Fix the actual evaluation to each pool member and optimize the
        # one-shot terminal Pareto designs. Random terminal points are not KG.
        class TerminalDesign(AcquisitionFunction):
            def __init__(self, point):
                super().__init__(model)
                self.point = point
            def forward(self, X):
                first = self.point.expand(*X.shape[:-2], 1, X.shape[-1])
                return hvkg(torch.cat([first, X], dim=-2))
        values = []
        for point in cx:
            _, value = optimize_acqf(TerminalDesign(point), bounds, q=4, num_restarts=2,
                         raw_samples=16, options={'maxiter': 35, 'batch_limit': 2})
            values.append(value.detach())
        scores = torch.stack(values).flatten()
        details.update(num_fantasies=2, terminal_pareto_size=2, inner_restarts=2,
                       scope='实际BoTorch HVKG；有限候选逐一固定，连续终局Pareto设计数值优化。小预算近似。')
    elif algorithm == 'psbax':
        # Algorithm 1: sample one function, execute the target-set algorithm,
        # then query maximum posterior entropy inside the sampled target set.
        # Adapt the scalar paper to two independent objective GPs and Pareto A.
        with torch.no_grad():
            domain = torch.cat([tx, cx] + ([px] if px is not None else []))
            posterior = model.posterior(domain)
            allowed = None
            for attempt in range(16):
                sample = posterior.rsample(torch.Size([1]))[0]
                target = is_non_dominated(sample)
                allowed = target[len(tx):len(tx)+len(cx)]
                if allowed.any(): break
            if not allowed.any():
                raise ValueError('PS-BAX采样目标集合没有可查询的未测候选；本轮停止推荐。')
            entropy = .5*posterior.variance[len(tx):len(tx)+len(cx)].clamp_min(1e-15).log().sum(-1)
            floor = entropy.min()-(entropy.max()-entropy.min()).abs()-1
            scores = torch.where(allowed, entropy, floor)
        details.update(scope='按PS-BAX Algorithm 1后验采样与集合内最大后验熵实现的双目标有限池适配；不计算集合成员熵或完整EIG，不声称原文标量收敛定理自动覆盖该扩展。',
                       sampled_target_candidate_ids=[r['candidate_id'] for r, keep in zip(candidates,allowed) if bool(keep)],
                       posterior_samples_attempted=attempt+1)
    elif algorithm == 'safeopt':
        # Finite, q=1 SafeOpt with the same scalar function as utility and
        # safety quantity (the ICML 2015 setting), explicit known Lipschitz L.
        h = finite(config.get('safe_threshold', .2 if raw is None else None), 'safe_threshold')
        lipschitz = finite(config.get('lipschitz_constant', 3. if raw is None else None), 'lipschitz_constant', 1e-8, 1e8)
        beta = finite(config.get('confidence_std_multiplier', 2.), 'confidence_std_multiplier', 1, 10)
        seed_ids = config.get('safe_seed_ids', [r['candidate_id'] for r in completed if r['y'][0] > h+.05] if raw is None else [])
        if raw is not None and config.get('safety_assumptions_accepted') is not True:
            raise ValueError('SafeOpt需声明safety_assumptions_accepted=true：已知安全种子、归一化域Lipschitz上界及可信GP置信界。')
        if not seed_ids or set(seed_ids)-{r['candidate_id'] for r in completed}:
            raise ValueError('safe_seed_ids需来自已完成且独立确认安全的观测。')
        with torch.no_grad():
            domain = torch.cat([tx, cx])
            posterior = models[0].posterior(domain)
            mean, std = posterior.mean.flatten(), posterior.variance.flatten().clamp_min(0).sqrt()
            lo, hi = mean-beta*std, mean+beta*std
            distance = torch.cdist(domain,domain)
            safe = torch.tensor([r['candidate_id'] in seed_ids for r in completed]+[False]*len(cx))
            if torch.any(lo[safe] < h):
                raise ValueError('安全种子的当前GP置信下界低于阈值；停止推荐并复核模型/噪声。')
            for _ in range(len(domain)):
                propagated = (lo[safe,None]-lipschitz*distance[safe]).max(0).values
                expanded = safe | (propagated >= h)
                lo = torch.maximum(lo, propagated)
                if torch.equal(expanded,safe):break
                safe = expanded
            if torch.any(lo > hi+1e-8):
                raise ValueError('Lipschitz传播下界与GP上界冲突；停止推荐并复核L/噪声/模型。')
            potential = safe & (hi >= lo[safe].max())
            expanders = safe & ((hi[:,None]-lipschitz*distance[:,~safe] >= h).any(-1) if (~safe).any() else torch.zeros_like(safe))
            query = (potential|expanders)[len(tx):]
            if not query.any():
                stop_reason = '当前SafeOpt安全改进/扩展集合中没有可查询候选；停止推荐。'
            width = (hi-lo).clamp_min(0)[len(tx):]
            scores = torch.where(query,width,torch.full_like(width,-1.))
        details.update(objective='objective1, maximize subject to objective1 >= safe_threshold', safe_threshold=h,
             lipschitz_constant_normalized_domain=lipschitz,confidence_std_multiplier=beta,safe_seed_ids=seed_ids,
             certified_safe_candidate_ids=[r['candidate_id'] for r, keep in zip(candidates,safe[len(tx):]) if bool(keep)],
             scope='ICML2015 SafeOpt的单轮有限域、单目标同函数阈值适配；传播已知Lipschitz安全下界，在潜在最优/扩展集合中选最大置信宽度。不等同独立多约束安全BO或实物安全认证。')
    elif algorithm in ['gibbon', 'qlogei', 'dynmeanbo']:
        if algorithm == 'gibbon':
            from botorch.acquisition.max_value_entropy_search import qLowerBoundMaxValueEntropy
            acquisition = qLowerBoundMaxValueEntropy(models[0], candidate_set=torch.cat([tx, cx]),
                                                     X_pending=px, num_mv_samples=16)
        else:
            from botorch.acquisition.logei import qLogExpectedImprovement
            acquisition = qLogExpectedImprovement(models[0], best_f=y[:, 0].max(), X_pending=px,
                                      sampler=SobolQMCNormalSampler(torch.Size([128])))
        with torch.no_grad():
            scores = acquisition(cx[:, None, :])
        details.update(objective='objective1 only', scope='实际BoTorch单目标采集函数；目标2保留但不参与本次决策。')
        if prior_details:
            details['expert_prior'] = prior_details
            details['scope'] = prior_details['scope']
    elif algorithm in ['mfkg', 'mfmes']:
        from botorch.models.gp_regression_fidelity import SingleTaskMultiFidelityGP
        from botorch.acquisition.cost_aware import InverseCostWeightedUtility
        from botorch.models.cost import AffineFidelityCostModel
        from botorch.acquisition.utils import project_to_target_fidelity
        from botorch.optim import optimize_acqf
        from botorch.acquisition.analytic import PosteriorMean
        from functools import partial
        model = SingleTaskMultiFidelityGP(tx, y[:, :1], train_Yvar=torch.full_like(y[:, :1], noise),
                                           data_fidelities=[2], outcome_transform=Standardize(m=1))
        fit_gpytorch_mll(ExactMarginalLogLikelihood(model.likelihood, model),
                          optimizer_kwargs={'options': {'maxiter': 60}})
        fixed_cost = finite(config.get('fixed_cost', .1), 'fixed_cost', .001, 1e6)
        fidelity_cost = finite(config.get('fidelity_cost', 1.), 'fidelity_cost', .001, 1e6)
        cost = InverseCostWeightedUtility(AffineFidelityCostModel({2: fidelity_cost}, fixed_cost=fixed_cost))
        project = partial(project_to_target_fidelity, target_fidelities={2: 1.}, d=3)
        if algorithm == 'mfkg':
            from botorch.acquisition.knowledge_gradient import qMultiFidelityKnowledgeGradient
            _, current = optimize_acqf(PosteriorMean(model), bounds, q=1, num_restarts=3,
                           raw_samples=32, fixed_features={2: 1.}, options={'maxiter': 40})
            acquisition = qMultiFidelityKnowledgeGradient(model, num_fantasies=8,
                          current_value=current.detach(), cost_aware_utility=cost, project=project, X_pending=px)
            # evaluate performs genuine fantasy-conditioned inner maximization.
            values = [acquisition.evaluate(point[None, None, :], bounds=bounds,
                       num_restarts=2, raw_samples=16, options={'maxiter': 35}).detach().flatten()[0] for point in cx]
            scores = torch.stack(values)
        else:
            from botorch.acquisition.max_value_entropy_search import qMultiFidelityMaxValueEntropy
            acquisition = qMultiFidelityMaxValueEntropy(model, candidate_set=project(torch.cat([tx, cx])),
                        num_fantasies=8, num_mv_samples=16, num_y_samples=32,
                        cost_aware_utility=cost, project=project, X_pending=px)
            with torch.no_grad():
                scores = acquisition(cx[:, None, :])
        details.update(objective='objective1 at fidelity=1', fixed_cost=fixed_cost,
                       fidelity_cost=fidelity_cost, cost_model='fixed_cost + fidelity_cost * fidelity',
                       scope='实际BoTorch多保真采集函数；需相同目标物理量及实测成本校准。未自动把SPM/SPMe/DFN当作连续精度刻度。')
    if scores is None or not torch.isfinite(scores).all():
        raise RuntimeError('采集函数未返回全部有限分数。')
    index = int(torch.argmax(scores)) if stop_reason is None else None
    predictions = []
    with torch.no_grad():
        posterior = model.posterior(cx)
        means, stds = posterior.mean, posterior.variance.clamp_min(0).sqrt()
    for i, row in enumerate(candidates):
        predictions.append({'candidate_id': row['candidate_id'], 'x1': row['x'][0], 'x2': row['x'][1],
              'fidelity': row['x'][2] if len(row['x']) == 3 else 1.,
              'acquisition': float(scores[i]), 'predicted_objective1': float(means[i, 0]),
              'std_objective1': float(stds[i, 0]), 'selected': i == index})
    save(out / 'bo_training_manifest.json', {'completed_ids': [r['candidate_id'] for r in completed],
         'pending_ids': [r['candidate_id'] for r in pending], 'normalization_bounds': [lower.tolist(), upper.tolist()],
         'noise_variance_original_units': noise, 'objective_direction': ['maximize', 'maximize'],
         'reference': reference.tolist() if torch.is_tensor(reference) else reference})
    result = {'kind': 'engineering', 'title': 'BoTorch实验选点 / ' + algorithm,
              'algorithm': algorithm, 'recommendation': predictions[index] if index is not None else None, 'details': details,
              'decision_status': 'stopped' if stop_reason else 'recommended', 'decision_reason': stop_reason,
              'metrics': {'completed': len(completed), 'candidates': len(candidates), 'pending': len(pending),
                          'elapsed_s': time.perf_counter()-tick},
              'scope': '未测候选不读取目标值，待回传候选不重复推荐。建议需要后续实验回传；本次不产生真实材料改进证据。'}
    return finish(config, out, result, predictions, packages=['botorch', 'gpytorch', 'torch'])
