"""Build a source-labelled half-cell candidate. Never fill missing kinetics."""
import math


def choose(rows,key,value,label):
    matches=[r for r in rows if r.get(key)==value]
    if len(matches)!=1:raise ValueError(label+'需有且只有一条对应记录。')
    return matches[0]


def build_sample(tables,config):
    electrode=choose(tables.get('极片',[]),'electrode_id',config.get('electrode_id'),'极片')
    sample_id=electrode.get('sample_id');parameters={};warnings=[];conflicts=[];missing=[]
    cell=choose(tables.get('半电池',[]),'cell_id',config['cell_id'],'电芯') if config.get('cell_id') else {}
    if cell and (cell.get('sample_id')!=sample_id or cell.get('electrode_id')!=electrode.get('electrode_id')):
        raise ValueError('电芯与所选极片/样品编号不一致。')
    chars=[r for r in tables.get('表征',[]) if r.get('sample_id')==sample_id]
    if config.get('characterization_row') not in ('',None):
        index=int(config['characterization_row'])
        if not 0<=index<len(tables['表征']):raise ValueError('表征行号不存在。')
        char=tables['表征'][index]
        if char.get('sample_id')!=sample_id:raise ValueError('所选表征行不属于该样品。')
    else:
        char=chars[0] if len(chars)==1 else {}
        if len(chars)>1:warnings.append('同一样品有多条表征记录，请明确选择一行，未自动混合。')
    models=[r for r in tables.get('仿真输入',[]) if r.get('sample_id')==sample_id]
    model=choose(models,'model_input_id',config['model_input_id'],'模型配置') if config.get('model_input_id') else models[0] if len(models)==1 else {}
    if len(models)>1 and not model:warnings.append('模型配置不唯一，需明确选择。')
    if model.get('parameter_set') not in ('',None,'Ecker2015_graphite_halfcell'):warnings.append('本入口固定使用Ecker半电池辅助参数；配置中的其他参考集不会自动采用。')
    def put(key,value,unit,source,kind='measured'):
        if value in ('',None):return None
        try:v=float(value)
        except (TypeError,ValueError):conflicts.append(key+'不是数值');return None
        if not math.isfinite(v) or v<=0:conflicts.append(key+'应为正有限数');return None
        parameters[key]={'value':v,'unit':unit,'source':source,'kind':kind};return v
    a=put('area_cm2',electrode.get('area_cm2'),'cm²','极片.area_cm2')
    m=put('coating_mass_mg',electrode.get('coating_mass_mg'),'mg','极片.coating_mass_mg')
    t=put('thickness_um',electrode.get('thickness_um'),'μm','极片.thickness_um')
    fractions=[electrode.get(k) for k in ['graphite_fraction','conductive_fraction','binder_fraction']]
    valid_fractions=all(isinstance(v,(int,float)) and math.isfinite(v) and 0<=v<=1 for v in fractions)
    if valid_fractions and abs(sum(fractions)-1)>1e-6:conflicts.append('配方质量分数之和不等于1')
    w=put('active_mass_fraction',electrode.get('graphite_fraction'),'1','极片.graphite_fraction')
    if w and w>1:conflicts.append('石墨比例超过1')
    ra=put('true_density_g_cm3',char.get('true_density_g_cm3'),'g/cm³','表征.true_density_g_cm3')
    density=m/1000/(a*t*1e-4) if a and m and t else None
    if density:
        put('bulk_density_g_cm3',density,'g/cm³','干涂层质量/面积/厚度','derived')
        measured=electrode.get('bulk_density_g_cm3')
        if isinstance(measured,(int,float)) and abs(measured-density)>max(.02*density,1e-9):warnings.append('录入体密度与质量/面积/厚度推算相差超过2%，请复核；当前采用推算值。')
    rc=electrode.get('conductive_true_density_g_cm3');rb=electrode.get('binder_true_density_g_cm3');ro=None
    if valid_fractions and abs(sum(fractions)-1)<=1e-6 and ra and density:
        terms=[fractions[0]/ra];other_sum=0;other_ok=True
        for fraction,rho in zip(fractions[1:],[rc,rb]):
            if fraction:
                if not isinstance(rho,(int,float)) or not math.isfinite(rho) or rho<=0:other_ok=False;break
                terms.append(fraction/rho);other_sum+=fraction/rho
        if other_ok:
            pore=1-density*sum(terms);am=density*fractions[0]/ra
            if not 0<pore<1 or not 0<am<1:conflicts.append('密度/配方推算出的孔隙率或活性体积分数不在(0,1)')
            else:
                put('porosity',pore,'1','三种固体体积可加近似','derived')
                put('active_volume_fraction',am,'1','涂层体密度×石墨质量分数/真密度','derived')
                if other_sum:ro=(1-fractions[0])/other_sum
                measured=electrode.get('porosity')
                if isinstance(measured,(int,float)) and abs(measured-pore)>.02:conflicts.append('实测与密度推算孔隙率差异>0.02，需选择并解释口径')
    if 'porosity' not in parameters:put('porosity',electrode.get('porosity'),'1','极片.porosity')
    if 'active_volume_fraction' not in parameters:put('active_volume_fraction',model.get('active_volume_fraction'),'1','仿真输入.active_volume_fraction','declared_model')
    radius=char.get('effective_radius_um');basis=char.get('radius_basis')
    if radius not in ('',None):
        put('radius_um',radius,'μm','表征.effective_radius_um；依据：'+str(basis or '未说明'))
        if not basis:warnings.append('有效半径未填写测量/定义依据。')
    elif config.get('allow_d50_radius') is True and char.get('d50_um'):
        put('radius_um',float(char['d50_um'])/2,'μm','用户明确接受D50/2球形等效假设','assumed');warnings.append('D50/2不是已测有效扩散长度。')
    for k,u in [('initial_x0','1'),('c_max_mol_m3','mol/m³'),('ds_m2_s','m²/s'),('i0_A_m2','A/m²')]:
        put(k,model.get(k),u,'仿真输入.'+k,'declared_model')
    for k in ['initial_x0','porosity','active_volume_fraction']:
        if k in parameters and not 0<parameters[k]['value']<1:conflicts.append(k+'必须在(0,1)')
    if 'porosity' in parameters and 'active_volume_fraction' in parameters and parameters['porosity']['value']+parameters['active_volume_fraction']['value']>1+1e-9:conflicts.append('孔隙率与活性固相体积分数之和超过1')
    for k,u in [('separator_thickness_um','μm'),('separator_porosity','1'),('electrolyte_concentration_mol_L','mol/L')]:put(k,cell.get(k),u,'半电池.'+k)
    if 'separator_porosity' in parameters and parameters['separator_porosity']['value']>=1:conflicts.append('隔膜孔隙率必须小于1')
    current=cell.get('current_mA');reference=cell.get('rate_reference_capacity_mAh')
    if isinstance(current,(int,float)) and math.isfinite(current) and current!=0:parameters['current_mA']={'value':current,'unit':'mA','source':'半电池.current_mA','kind':'measured'}
    elif isinstance(reference,(int,float)) and reference>0 and isinstance(cell.get('c_rate'),(int,float)) and cell['c_rate']>0:
        direction=config.get('direction')
        if direction in ['lithiation','delithiation']:
            parameters['current_mA']={'value':reference*cell['c_rate']*(1 if direction=='lithiation' else -1),'unit':'mA','source':'倍率×明确的参考容量；用户选择方向','kind':'derived'}
    for k in ['voltage_lower_V','voltage_upper_V','temperature_C']:
        v=cell.get(k)
        if isinstance(v,(int,float)) and math.isfinite(v):parameters[k]={'value':v,'unit':'°C' if k=='temperature_C' else 'V','source':'半电池.'+k,'kind':'measured'}
    if 'voltage_lower_V' in parameters and 'voltage_upper_V' in parameters and parameters['voltage_lower_V']['value']>=parameters['voltage_upper_V']['value']:conflicts.append('电压下限必须小于上限')
    required=['area_cm2','thickness_um','porosity','active_volume_fraction','radius_um','initial_x0','c_max_mol_m3','ds_m2_s','i0_A_m2','current_mA','separator_thickness_um','separator_porosity','electrolyte_concentration_mol_L','voltage_lower_V','voltage_upper_V','temperature_C']
    missing=[k for k in required if k not in parameters]
    if not config.get('ocp_job_id'):missing.append('ocp_table：上传stoichiometry,voltage_V的OCP CSV')
    tolerance_means={'mass_mg':m,'area_cm2':a,'thickness_um':t,'active_fraction':w,'active_density':ra,'other_density':ro,'q_ref':None}
    return {'kind':'sample','sample_id':sample_id,'electrode_id':electrode.get('electrode_id'),'cell_id':cell.get('cell_id'),
            'model_input_id':model.get('model_input_id'),'parameters':parameters,'missing':missing,'conflicts':conflicts,'warnings':warnings,
            'tolerance_means':tolerance_means,'candidate_complete':not missing and not conflicts,
            'ocp_job_id':config.get('ocp_job_id'),'physics_validation_passed':False,
            'reference_policy':'SPM石墨/Li半电池，石墨映射到positive槽位；未覆盖辅助参数来自Ecker2015_graphite_halfcell，运行前需明确接受参考近似。',
            'scope':'参数候选与缺失诊断。三类固体体积可加；石墨比例需代表活性石墨，碳含量不能替代活性比例。实测、推算和模型声明逐项标记；资料完整不等于可辨识或独立预测已通过。'}
