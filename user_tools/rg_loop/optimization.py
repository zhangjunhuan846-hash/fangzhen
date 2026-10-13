"""Small exact GP + constrained EI on a declared finite candidate set.

The recommender receives completed observations only. The hidden synthetic
oracle is called solely by the offline experiment driver after a suggestion.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import numpy as np
from scipy.linalg import cho_factor, cho_solve, solve_triangular
from scipy.optimize import minimize
from scipy.stats import norm

DEFAULT_THRESHOLDS = {"ice": .88, "yield": .84}
NOISE = np.array([2.5, .005, .005], dtype=float)


def candidate_grid(n=11):
    if n < 3:
        raise ValueError("grid requires >=3 levels")
    rows=[]
    for i,a in enumerate(np.linspace(0,1,n)):
        for j,b in enumerate(np.linspace(0,1,n)):
            if a+b <= 1.6+1e-10:
                rows.append({"candidate_id":f"x{i:02d}_y{j:02d}","x":[float(a),float(b)]})
    return rows


def _matern(x,y,length,amplitude):
    d=np.sqrt(np.maximum(((x[:,None,:]-y[None,:,:])/length)**2,0).sum(axis=2))
    z=np.sqrt(5)*d
    return amplitude**2*(1+z+z*z/3)*np.exp(-z)


class GaussianProcess:
    def fit(self,x,y,noise_std):
        self.x=np.asarray(x,dtype=float)
        y=np.asarray(y,dtype=float)
        if self.x.ndim!=2 or len(y)!=len(self.x) or not np.isfinite(y).all() or not np.isfinite(self.x).all():
            raise ValueError("invalid GP training records")
        if not math.isfinite(noise_std) or noise_std<=0:
            raise ValueError("positive observation noise must be declared")
        self.mean=float(np.mean(y));self.scale=max(float(np.std(y)),float(noise_std),1e-9)
        self.y=(y-self.mean)/self.scale
        self.noise=float(noise_std)/self.scale
        dimension=self.x.shape[1]
        def objective(theta):
            length=np.exp(theta[:dimension]);amp=math.exp(theta[-1])
            cov=_matern(self.x,self.x,length,amp)+np.eye(len(y))*(self.noise**2+1e-8)
            try:
                chol=cho_factor(cov,lower=True,check_finite=False)
                return float(.5*self.y@cho_solve(chol,self.y)+np.log(np.diag(chol[0])).sum()+.5*len(y)*np.log(2*np.pi))
            except np.linalg.LinAlgError:
                return 1e20
        initial=np.log([.35]*dimension+[1.])
        result=minimize(objective,initial,method="L-BFGS-B",
                        bounds=[(math.log(.05),math.log(2))]*dimension+[(math.log(.2),math.log(3))],
                        options={"maxiter":45})
        self.theta=result.x if np.isfinite(result.fun) else initial
        self.length=np.exp(self.theta[:dimension]);self.amplitude=math.exp(self.theta[-1])
        cov=_matern(self.x,self.x,self.length,self.amplitude)+np.eye(len(y))*(self.noise**2+1e-8)
        self.chol=cho_factor(cov,lower=True)
        self.alpha=cho_solve(self.chol,self.y)
        return self

    def predict(self,x):
        x=np.asarray(x,dtype=float)
        cross=_matern(self.x,x,self.length,self.amplitude)
        mean=self.mean+self.scale*(cross.T@self.alpha)
        v=solve_triangular(self.chol[0],cross,lower=True)
        variance=np.maximum(self.amplitude**2-(v*v).sum(axis=0),1e-12)
        return mean,self.scale*np.sqrt(variance)

    def joint_posterior(self,x):
        """Latent function posterior; observation noise is not added a second time."""
        x=np.asarray(x,dtype=float)
        cross=_matern(self.x,x,self.length,self.amplitude)
        mean=self.mean+self.scale*(cross.T@self.alpha)
        projected=solve_triangular(self.chol[0],cross,lower=True)
        covariance=self.scale**2*(_matern(x,x,self.length,self.amplitude)-projected.T@projected)
        return mean,(covariance+covariance.T)/2

    def joint_samples(self,x,count,seed):
        x=np.asarray(x,dtype=float);unique,inverse=np.unique(x,axis=0,return_inverse=True)
        mean,cov=self.joint_posterior(unique)
        eigenvalues,vectors=np.linalg.eigh(cov)
        if eigenvalues.min()<-1e-7*max(1.,float(np.max(np.diag(cov)))):raise ValueError('joint posterior covariance is not positive semidefinite')
        root=vectors*np.sqrt(np.maximum(eigenvalues,0))
        samples=mean+np.random.default_rng(seed).normal(size=(int(count),len(unique)))@root.T
        return samples[:,inverse]


def recommend(observations,candidates,*,batch="A",strategy="bo",seed=0,pending=(),thresholds=None,noise_std=NOISE):
    thresholds=dict(thresholds or DEFAULT_THRESHOLDS)
    if strategy not in ("bo","random","doe"):
        raise ValueError("unknown strategy")
    if any(r.get("batch")!=batch or r.get("role") not in ('optimization','exploration') or r.get("status")!="completed" for r in observations):
        raise ValueError("training only accepts same-batch completed optimization observations; final confirmation is forbidden")
    ids=[r["candidate_id"] for r in observations]
    if len(ids)!=len(set(ids)):
        raise ValueError("explicit repeated-experiment aggregation required")
    used=set(ids)|set(pending)
    available=[r for r in candidates if r["candidate_id"] not in used]
    if not available:
        return {"status":"exhausted","batch":batch}
    snapshot=hashlib.sha256(json.dumps(observations,sort_keys=True,allow_nan=False).encode()).hexdigest()
    xs=np.array([r["x"] for r in available],dtype=float)
    if len(observations)==0:
        chosen=available[0];mode="cold_start";details={}
    elif strategy=="random":
        chosen=available[int(np.random.default_rng(seed+len(observations)*101).integers(len(available)))]
        mode="random";details={}
    elif strategy=="doe" or len(observations)<3:
        train=np.array([r["x"] for r in observations])
        score=np.sqrt(((xs[:,None,:]-train[None,:,:])**2).sum(axis=2)).min(axis=1)
        chosen=available[int(np.argmax(score))]
        mode="space_filling";details={}
    else:
        train=np.array([r["x"] for r in observations])
        y=np.array([[r[k] for k in ("q","ice","yield")] for r in observations],dtype=float)
        models=[GaussianProcess().fit(train,y[:,i],float(noise_std[i])) for i in range(3)]
        means,stds=zip(*(m.predict(xs) for m in models))
        mu,sigma=means[0],stds[0]
        p=norm.cdf((means[1]-thresholds["ice"])/stds[1])*norm.cdf((means[2]-thresholds["yield"])/stds[2])
        feasible=(y[:,1]>=thresholds["ice"])&(y[:,2]>=thresholds["yield"])
        if feasible.any():
            incumbent=float(models[0].predict(train[feasible])[0].max())
            improvement=mu-incumbent
            z=improvement/sigma
            ei=improvement*norm.cdf(z)+sigma*norm.pdf(z)
            acquisition=np.maximum(ei,0)*p
            mode="constrained_EI"
        else:
            # No feasible incumbent: collect feasibility information first.
            acquisition=p+.02*sigma/max(float(sigma.max()),1e-12)
            mode="feasibility_first"
        pick=int(np.argmax(acquisition));chosen=available[pick]
        details={"q_mean":float(mu[pick]),"q_interval_95":[float(mu[pick]-1.96*sigma[pick]),float(mu[pick]+1.96*sigma[pick])],
                 "feasibility_probability":float(p[pick]),"acquisition":float(acquisition[pick]),
                 "uncertainty_kind":"conditional latent-GP interval, not validated calibration",
                 "assumption":"independent output GPs; known synthetic observation noise",
                 "acquisition_kind":"plug-in constrained EI, not qNEI"}
    return {"status":"suggested","candidate_id":chosen["candidate_id"],"x":chosen["x"],"batch":batch,
            "mode":mode,"training_count":len(observations),"training_ids":ids,"training_snapshot":snapshot,
            "strategy":strategy,**details}


def synthetic_oracle(x,batch):
    """Independent simulator truth; not callable from recommend()."""
    a,b=map(float,x)
    if batch=="A": center_a,center_b=.65,.35
    elif batch=="B": center_a,center_b=.35,.6
    else: raise ValueError("unknown synthetic feedstock")
    peak=math.exp(-((a-center_a)**2/.07+(b-center_b)**2/.09))
    q=220+110*peak-12*a+4*b
    ice=.82+.12*math.exp(-((a-center_a)**2/.20+(b-center_b)**2/.22))-.015*b
    material_yield=.99-.17*a-.055*b
    return np.array([q,ice,material_yield],dtype=float)


def _point_observation(candidate,batch,seed,noise_std=NOISE):
    truth=synthetic_oracle(candidate["x"],batch)
    # Fixed noise keyed by point. Policies see the same observation at a common point.
    key=int(hashlib.sha256(f"{batch}:{seed}:{candidate['candidate_id']}".encode()).hexdigest()[:12],16)
    observed=truth+np.random.default_rng(key).normal(0,noise_std)
    return {"candidate_id":candidate["candidate_id"],"x":candidate["x"],"batch":batch,
            "q":float(observed[0]),"ice":float(observed[1]),"yield":float(observed[2]),
            "status":"completed","role":"optimization","evidence_type":"synthetic_process"}


def run_campaign(out,*,batch="A",seed=0,strategy="bo",budget=18,initial_n=5,grid_n=11,thresholds=None,noise_std=NOISE):
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    candidates=candidate_grid(grid_n)
    thresholds=dict(thresholds or DEFAULT_THRESHOLDS)
    if not initial_n<=budget<=len(candidates):
        raise ValueError("invalid budget")
    initial=np.random.default_rng(seed).choice(len(candidates),initial_n,replace=False)
    observations=[];history=[];by_id={r["candidate_id"]:r for r in candidates}
    # Initial design is shared across policies for this batch+seed.
    for i in initial:
        observations.append(_point_observation(candidates[int(i)],batch,seed,noise_std))
    with (out/"initial_observations.json").open("w",encoding="utf-8") as f:
        json.dump(observations,f,ensure_ascii=False,indent=2)
    while len(observations)<budget:
        recommendation=recommend(observations,candidates,batch=batch,strategy=strategy,seed=seed,thresholds=thresholds,noise_std=noise_std)
        round_id=len(observations)-initial_n+1
        # Commit suggestion before the oracle reveals the next outcome.
        (out/f"suggestion_{round_id:03d}.json").write_text(json.dumps(recommendation,ensure_ascii=False,indent=2),encoding="utf-8")
        response=_point_observation(by_id[recommendation["candidate_id"]],batch,seed,noise_std)
        observations.append(response)
        history.append({"round":round_id,"suggestion":recommendation,"feedback":response})
    # Evaluator-only truth is never passed into the recommender.
    all_truth=np.array([synthetic_oracle(r["x"],batch) for r in candidates])
    feasible=(all_truth[:,1]>=thresholds["ice"])&(all_truth[:,2]>=thresholds["yield"])
    optimum=float(all_truth[feasible,0].max()) if feasible.any() else None
    observed_truth=np.array([synthetic_oracle(r["x"],batch) for r in observations])
    found=(observed_truth[:,1]>=thresholds["ice"])&(observed_truth[:,2]>=thresholds["yield"])
    best=float(observed_truth[found,0].max()) if found.any() else None
    chronology=all(h['suggestion']['training_ids']==[r['candidate_id'] for r in observations[:initial_n+h['round']-1]]
                   and h['suggestion']['candidate_id']==observations[initial_n+h['round']-1]['candidate_id']
                   and h['suggestion']['candidate_id'] not in h['suggestion']['training_ids'] for h in history)
    summary={"batch":batch,"seed":seed,"strategy":strategy,"budget":budget,"initial_n":initial_n,
             "evidence_type":"synthetic_process","candidate_count":len(candidates),
             "best_true_feasible":best,"true_feasible_count":int(found.sum()),"evaluator_optimum":optimum,
             "simple_regret":None if best is None or optimum is None else optimum-best,
             "all_suggestions_before_feedback":bool(chronology),
             "thresholds":thresholds,"noise_std":list(map(float,noise_std)),
             "note":"coordinates are synthetic unit-square variables, not recommended chemical conditions"}
    (out/"observations.json").write_text(json.dumps(observations,indent=2),encoding="utf-8")
    (out/"history.json").write_text(json.dumps(history,indent=2),encoding="utf-8")
    (out/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    return summary


def benchmark(out,seeds=range(5),batches=("A","B"),budget=18,initial_n=5,grid_n=11,thresholds=None,noise_std=NOISE):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    rows=[]
    for batch in batches:
        for seed in seeds:
            for strategy in ("random","doe","bo"):
                print(f"PROCESS {batch} seed={seed} strategy={strategy}",flush=True)
                rows.append(run_campaign(out/f"{batch}_{seed}_{strategy}",batch=batch,seed=seed,strategy=strategy,budget=budget,initial_n=initial_n,grid_n=grid_n,thresholds=thresholds,noise_std=noise_std))
    summary={"evidence_type":"synthetic_process","rows":rows,
             "scope":"offline algorithm behavior only; neither real graphite optimization nor general superiority",
             "equal_budget":True,"same_initial_data":True,"same_point_noise":True}
    (out/"benchmark.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    return summary
