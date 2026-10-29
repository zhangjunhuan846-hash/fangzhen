"""Generate a self-contained report without altering research outcomes."""
from html import escape
from pathlib import Path
import numpy as np

def write_report(path,summary,example):
    rows=''.join('<tr>'+''.join(f'<td>{escape(str(value))}</td>' for value in (
       row['method'],row['group'],row['n_windows'],f"{row['open_loop_rmse_mV']:.3f}",
       f"{row['ekf_prior_rmse_mV']:.3f}",f"{row['ekf_posterior_residual_rmse_mV']:.3f}",f"{row['soc_proxy_rmse_pp']:.3f}"))+'</tr>' for row in summary)
    t=np.asarray([r['time_s'] for r in example]);v=np.asarray([r['measured_voltage_V'] for r in example]);pred=np.asarray([r['open_loop_voltage_V'] for r in example]);
    lo=float(min(v.min(),pred.min()));hi=float(max(v.max(),pred.max()));span=max(hi-lo,1e-9)
    def line(values):return ' '.join(f'{40+720*(x-t[0])/max(t[-1]-t[0],1e-9):.2f},{240-200*(y-lo)/span:.2f}' for x,y in zip(t,values))
    html=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>CALB EIS HPPC 方法对照</title>
<style>body{{font:16px/1.65 system-ui;max-width:1000px;margin:2rem auto;padding:0 1rem;color:#202530}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #cbd3da;padding:.35rem}}.note{{background:#fff5df;padding:1rem}}svg{{width:100%;border:1px solid #ddd}}</style>
<h1>CALB EIS＋HPPC 回顾性方法对照</h1><div class="note"><b>适用范围：</b>60129 电芯、25°C，EIS 测于被评分脉冲与驾驶之后；数据和窗口此前已经查看，SOC 和老化状态不完全匹配。仅为回顾性探索，不是事前预测、盲测或硬件认证。</div>
<p>同一 1RC 结构、相同容量/OCV、脉冲和参数边界；分别比较 HPPC 单独拟合、EIS 初始化后 HPPC 拟合、EIS＋HPPC 联合拟合。每组残差先归一化；联合目标两组各占一半。不同方法 EIS 额外测量成本未匹配。</p>
<table><thead><tr><th>方法</th><th>窗口</th><th>数量</th><th>开环 RMSE mV</th><th>EKF 预测步 RMSE mV</th><th>EKF 更新后残差 mV</th><th>SOC 代理 RMSE 百分点</th></tr></thead><tbody>{rows}</tbody></table>
<h2>示例：WLTP 第一个窗口</h2><p>蓝色：HPPC 开环预测；绿色：实测。时间 0–{t[-1]:.0f} 秒；电压范围 {lo:.3f}–{hi:.3f} V。</p>
<svg viewBox="0 0 800 270" role="img" aria-label="开环预测与实测电压"><polyline points="{line(pred)}" fill="none" stroke="#4444aa"/><polyline points="{line(v)}" fill="none" stroke="#16875c"/></svg>
<p>SOC 是由 C/20、窗口起始电压及电流积分构造的代理；初始状态设为代理减 4 个百分点。更新后的残差使用当前电压观测，不能与开环误差比较。完整参数、筛查、窗口明细和逐点数据需与本报告一并保存。</p>
</html>'''
    Path(path).write_text(html,encoding='utf8')
