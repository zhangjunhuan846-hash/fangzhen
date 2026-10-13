# fangzhen v0.3 本地研究工作站

## 已实现

双击根目录“启动科研工作站.bat”打开本地界面。程序内嵌关键数据表，通过SQLite持久保存，与旧版打开Excel的启动器分开。界面采用用户给定的浅紫色首页、左侧方案列表、中间表格及结果面板布局；原料、工艺、表征、极片、半电池仍只有关键字段，无复核、日期或记录人输入。

- 方案创建、重命名、搜索、切换；5张内置表格，逐格编辑、多行粘贴、增删行；自动保存、显式保存、乐观版本检查及版本恢复。
- 简版Excel导入，原文件字节和SHA-256留存，导入创建新方案；Excel导出保留单位、百分数及ICE公式；JSON备份。
- 受控科学约束正反算、输入/待求切换、面载量上下界、推理路径、冲突及欠定说明；可写回选中极片，不能把参考容量写成实测半电池性能。
- 后台任务队列调用现有PyBaMM/PyBOP：Chen公开参数前向计算、Chen电压回放、SINTEF石墨半电池回放、Chen参数辨识及同一任务冻结参数后的C2留出验证。
- 公开ASC制造数据的有限候选历史回放，仍沿用当前质检规则、5初始条件、15总预算、10随机种子，比较随机、maximin空间填充和GP EI。该回放不是新实验推荐。
- CSV实验曲线（time_s、voltage_V）导入、严格递增时间检查、原文件保留；结果曲线与任务日志。
- 按相同倍率、相同循环节点显示各颗电芯容量、ICE和保持率。相同mAh/g质量口径需由实验记录者保证；不隐式合并重复电芯。

## 数据与运行

当前电脑的数据在项目 `data/workbench/workbench.sqlite`，源Excel在 `imports`，完整任务输入快照和结果在 `jobs`，导出的Excel在 `exports`。软件升级不得覆盖数据目录。旧版Excel及桌面程序保留；不会静默搬迁用户已有记录，用户可主动导入简版。

程序仅监听127.0.0.1，浏览器连接本机，不使用云账户；API需要本地会话令牌。关闭浏览器后服务继续运行，可再次双击程序打开同一实例；点击界面“关闭程序”退出服务。运行任务未结束时不允许退出；重启后未完成任务标为中断，不假称成功。

数据录入、版本保存与约束计算使用打包Python，无需另装Python。Excel导出使用当前Codex Node与artifact-tool运行时。物理任务使用本机Ubuntu WSL及现有PyBaMM/PyBOP环境，需保留原项目代码及数据；复制exe到其他电脑不自动安装这些环境。

## 未完成的科学/工程能力

任意历史Excel的自动字段/公式理解尚未实现，本版只接受已定义简版。CSV仅接受明确列名，原始Neware/Landt/Bio-Logic等格式还需专用适配器。模型任务明确使用公开参数/数据，没有把用户样品记录自动转成可信的石墨动力学参数。用户自有半电池曲线辨识、真实再生工艺前瞻推荐、ICP/SEM图像解析、多目标工艺寻优、量产尺寸链及CpK均不在本版验收范围。

## GitHub参考与选择（2026-10-12）

|项目|可借鉴内容|本版采用情况|
|---|---|---|
|[Univer](https://github.com/dream-num/univer)|嵌入式表格、插件化参数工具；Apache-2.0核心与Pro功能须分辨|界面结构参考；未引入其SDK。当前定型关键数据网格用原生JS，后续需要通用电子表格时可评估|
|[Tabulator](https://github.com/tabulator-tables/tabulator)|可编辑数据网格、键盘与剪贴板交互|候选网格组件；未复制其代码|
|[BayBE](https://github.com/emdgroup/baybe)|实验候选空间、约束、多目标及历史回测；Apache-2.0|后续优化后端参考；本版复用已有GP回放，未安装BayBE|
|[eLabFTW](https://github.com/elabftw/elabftw)|实验与附件关系、版本记录|产品流程参考；未复制项目代码|
|[PyBaMM](https://github.com/pybamm-team/PyBaMM)|电化学模型与数值求解|继续使用项目已有物理内核|

[Handsontable官方许可说明](https://github.com/handsontable/handsontable/blob/develop/docs/content/guides/technical-specification/software-license/software-license.md)区分非商业和商业许可，不能把现代版本当成无条件MIT组件使用；本次未采用。

所有本版界面代码为本项目新增，参考项目没有被声明为已经集成。没有为了使用截图界面而重写G5/G6科学结论或修改历史失败结果。
