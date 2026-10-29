"""Windows desktop entry point for the Excel workstation and existing physics loop."""
from __future__ import annotations
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from user_tools.rg_workstation import check_workbook


def resources():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))


def application_dir():
    return Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]/'outputs'/'fangzhen_desktop'


def find_project(app):
    for p in [app,*app.parents]:
        if (p/'user_tools'/'rg_loop'/'workflow.py').exists():return p
    return None


def wsl_path(path):
    s=str(Path(path).resolve()).replace('\\','/')
    if len(s)<3 or s[1:3]!=':/':raise ValueError('仿真文件需要位于本机盘符路径，如 C:\\ 或 D:\\。')
    return '/mnt/'+s[0].lower()+'/'+s[3:]


def template_path():
    bundled=resources()/'templates'/'workstation.xlsx'
    if bundled.exists():return bundled
    return resources()/'outputs'/'rg_workstation_lite'/'回收石墨关键数据_简版.xlsx'


def validate(path,out):
    buffer=io.StringIO()
    with contextlib.redirect_stdout(buffer):code=check_workbook(path,out)
    result=json.loads(buffer.getvalue().strip().splitlines()[-1])
    return code,result


class Workstation:
    def __init__(self,root):
        self.root=root;self.app=application_dir();self.app.mkdir(parents=True,exist_ok=True)
        self.config=self.app/'settings.json';settings={}
        if self.config.exists():
            try:settings=json.loads(self.config.read_text(encoding='utf-8'))
            except (OSError,ValueError):pass
        self.data=self.app/'我的数据';self.data.mkdir(exist_ok=True)
        default=self.data/'我的关键数据_简版.xlsx'
        if not default.exists():shutil.copy2(template_path(),default)
        self.workbook=tk.StringVar(value=settings.get('workbook',str(default)) if settings.get('template_version')=='lite-1' else str(default))
        project=find_project(self.app)
        self.project=tk.StringVar(value=settings.get('project',str(project) if project else ''))
        self.mock=tk.BooleanVar(value=False);self.status=tk.StringVar(value='就绪：先打开Excel填写，保存后再校验或运行。')
        self.events=queue.Queue();self.busy=False;self.buttons=[]
        root.title('fangzhen · 回收石墨科研工作站');root.geometry('960x700');root.minsize(820,620)
        style=ttk.Style(root);style.theme_use('clam');style.configure('TLabel',font=('Microsoft YaHei',10))
        style.configure('TButton',font=('Microsoft YaHei',10),padding=8)
        panel=ttk.Frame(root,padding=24);panel.pack(fill='both',expand=True)
        ttk.Label(panel,text='回收石墨科研工作站',font=('Microsoft YaHei',22,'bold')).pack(anchor='w')
        ttk.Label(panel,text='只记录关键数据：原料、处理工艺、表征、极片、半电池').pack(anchor='w',pady=(4,18))
        files=ttk.LabelFrame(panel,text='当前工作簿',padding=12);files.pack(fill='x')
        ttk.Entry(files,textvariable=self.workbook).pack(side='left',fill='x',expand=True)
        self.button(files,'选择Excel',self.choose_workbook).pack(side='left',padx=(8,0))
        ttk.Label(panel,text='不需要填写复核、日期或时间；没有的数据可以留空。').pack(anchor='w',pady=(6,14))
        actions=ttk.Frame(panel);actions.pack(fill='x')
        for label,callback in [('① 打开Excel',self.open_workbook),('② 保存归档',self.check),('③ 查看最新结果',self.latest)]:
            self.button(actions,label,callback).pack(side='left',padx=(0,8))
        tools=ttk.Frame(panel);tools.pack(fill='x',pady=10)
        self.button(tools,'新建工作簿副本',self.new_workbook).pack(side='left',padx=(0,8))
        self.button(tools,'打开数据与归档目录',lambda:self.open(self.data)).pack(side='left',padx=(0,8))
        self.button(tools,'检查仿真环境',self.environment).pack(side='left')
        self.advanced=ttk.LabelFrame(panel,text='高级仿真（需要选择原v0.2仿真模板）',padding=10)
        self.button(panel,'显示 / 收起高级仿真',self.toggle_advanced).pack(anchor='w',pady=6)
        backend=ttk.Frame(self.advanced);backend.pack(fill='x')
        ttk.Entry(backend,textvariable=self.project).pack(side='left',fill='x',expand=True)
        self.button(backend,'选择项目',self.choose_project).pack(side='left',padx=(8,0))
        ttk.Checkbutton(self.advanced,text='同时运行合成工艺优化演示（增加运行时间）',variable=self.mock).pack(anchor='w')
        self.button(self.advanced,'运行仿真',self.simulate).pack(anchor='w')
        ttk.Label(panel,textvariable=self.status,wraplength=880,foreground='#23465b').pack(anchor='w',pady=8)
        self.log=tk.Text(panel,height=12,font=('Consolas',10),wrap='word',state='disabled')
        self.log.pack(fill='both',expand=True)
        root.after(150,self.poll)
        root.protocol('WM_DELETE_WINDOW',self.close)

    def button(self,parent,label,callback):
        b=ttk.Button(parent,text=label,command=callback);self.buttons.append(b);return b

    def save(self):
        self.config.write_text(json.dumps({'workbook':self.workbook.get(),'project':self.project.get(),'template_version':'lite-1'},ensure_ascii=False,indent=2),encoding='utf-8')

    def toggle_advanced(self):
        if self.advanced.winfo_manager():self.advanced.pack_forget()
        else:self.advanced.pack(fill='x',before=self.log,pady=6)

    def close(self):
        if self.busy:
            messagebox.showinfo('任务运行中','请等待当前任务结束后关闭，避免中断数据归档。');return
        self.save();self.root.destroy()

    def open(self,path):
        try:os.startfile(str(path))
        except OSError as exc:messagebox.showerror('无法打开',f'{exc}\n请确认已安装Excel或兼容表格软件。')

    def checked_path(self):
        p=Path(self.workbook.get())
        if not p.is_file() or p.suffix.lower()!='.xlsx':raise ValueError('请选择有效的 .xlsx 工作簿。')
        return p.resolve()

    def choose_workbook(self):
        p=filedialog.askopenfilename(filetypes=[('Excel工作簿','*.xlsx')])
        if p:self.workbook.set(p);self.save()

    def choose_project(self):
        p=filedialog.askdirectory()
        if p:self.project.set(p);self.save()

    def open_workbook(self):
        try:self.open(self.checked_path())
        except ValueError as exc:messagebox.showerror('工作簿',str(exc))

    def new_workbook(self):
        p=filedialog.asksaveasfilename(initialdir=self.data,initialfile='新科研工作台.xlsx',defaultextension='.xlsx',filetypes=[('Excel工作簿','*.xlsx')])
        if p:
            shutil.copy2(template_path(),p);self.workbook.set(p);self.save();self.open(p)

    def run(self,job):
        if self.busy:return
        self.save();self.busy=True
        for b in self.buttons:b.state(['disabled'])
        self.status.set('任务运行中，进度见下方日志。')
        def worker():
            try:job()
            except Exception as exc:self.events.put(('error',str(exc)))
            finally:self.events.put(('done',''))
        threading.Thread(target=worker,daemon=True).start()

    def poll(self):
        try:
            while True:
                kind,value=self.events.get_nowait()
                if kind=='done':
                    self.busy=False
                    for b in self.buttons:b.state(['!disabled'])
                elif kind=='open':self.open(value)
                else:
                    self.log.configure(state='normal');self.log.insert('end',value+'\n');self.log.see('end');self.log.configure(state='disabled')
                    if kind in ('status','error'):self.status.set(value)
        except queue.Empty:pass
        self.root.after(150,self.poll)

    def check(self):
        try:p=self.checked_path()
        except ValueError as exc:messagebox.showerror('工作簿',str(exc));return
        self.events.put(('log','请确保Excel已保存。本次读取磁盘文件，不读取未保存的编辑。'))
        def job():
            _,r=validate(p,self.data/'归档')
            self.events.put(('status',f"校验完成：{r['status']}，错误 {r['errors']} 项；约束状态 {r['constraint_status']}。"))
            self.events.put(('open',r['report']))
        self.run(job)

    def command(self,args,cwd):
        flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
        with subprocess.Popen(args,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                              creationflags=flags) as p:
            for line in iter(p.stdout.readline,b''):
                # WSL warnings may use UTF-16; physics output uses UTF-8.
                text=line.decode('utf-16-le' if b'\x00' in line else 'utf-8',errors='replace').strip()
                if text:self.events.put(('log',text))
            return p.wait()

    def environment(self):
        project=Path(self.project.get())
        def job():
            if not (project/'user_tools'/'rg_loop'/'workflow.py').exists():raise ValueError('未找到仿真项目，请选择包含user_tools的项目目录。')
            code=self.command(['wsl.exe','-d','Ubuntu','--','/home/zjh/miniforge3/envs/pybamm/bin/python',
                               '-c',"import pybamm,pybop,openpyxl; print('PyBaMM/PyBOP environment ready')"],project)
            if code:raise RuntimeError('WSL仿真环境检查失败，详见日志。')
            node=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
            self.events.put(('status','物理环境可用；Excel结果导出环境'+('可用。' if node.exists() else '缺失，仍可保留JSON/CSV。')))
        self.run(job)

    def simulate(self):
        try:
            workbook=self.checked_path();project=Path(self.project.get()).resolve()
            from user_tools.rg_workstation import read_xlsx
            from user_tools.rg_lite import is_lite
            if is_lite(read_xlsx(workbook)):raise ValueError('当前简版用于记录关键数据。运行高级仿真时，请选择保留的v0.2仿真工作簿。')
            if not (project/'user_tools/rg_loop/workflow.py').exists():raise ValueError('请先选择有效的仿真项目。')
            wp=wsl_path(workbook);pp=wsl_path(project);out=self.data/'仿真记录';out.mkdir(exist_ok=True)
        except (ValueError,OSError) as exc:messagebox.showerror('仿真设置',str(exc));return
        mock=self.mock.get();before={p.name for p in out.iterdir() if p.is_dir()}
        def job():
            args=['wsl.exe','-d','Ubuntu','--cd',pp,'--','/home/zjh/miniforge3/envs/pybamm/bin/python',
                  '-m','user_tools.rg_loop.workflow','--workbook',wp,'--out',wsl_path(out)]
            if not mock:args.append('--skip-process')
            self.events.put(('log','开始读取已保存工作簿；部分物理任务可能需要数分钟。'))
            code=self.command(args,project)
            sessions=[p for p in out.iterdir() if p.is_dir() and p.name not in before and (p/'summary.json').exists()]
            if not sessions:raise RuntimeError(f'未生成完整仿真记录（退出码{code}），请检查日志。')
            session=max(sessions,key=lambda p:p.name)
            node=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
            builder=project/'outputs/rg_loop_v02_20261012_01a12de8/_build/workbooks.mjs'
            if node.exists() and builder.exists():
                export=self.command([str(node),str(builder),'results',str(session)],project)
                if export:self.events.put(('log','Excel结果导出失败；原始JSON/CSV已保留。'))
            self.events.put(('open',session/'result_workbook.xlsx' if (session/'result_workbook.xlsx').exists() else session))
            self.events.put(('status',f'仿真结束，退出码{code}。请查看任务状态及可信性判断；运行完成不代表科学验证通过。'))
        self.run(job)

    def latest(self):
        from user_tools.rg_workstation import read_xlsx
        from user_tools.rg_lite import is_lite
        try:lite=is_lite(read_xlsx(self.checked_path()))
        except Exception:lite=False
        if lite:
            reports=sorted((self.data/'归档').glob('*/report.html'),reverse=True)
            if reports:self.open(reports[0])
            else:messagebox.showinfo('暂无归档','先保存Excel，再点击“保存归档”。')
            return
        base=self.data/'仿真记录'
        sessions=sorted([p for p in base.glob('*') if p.is_dir() and (p/'summary.json').exists()],reverse=True)
        if sessions:
            p=sessions[0];self.open(p/'result_workbook.xlsx' if (p/'result_workbook.xlsx').exists() else p)
        else:
            reports=sorted((self.data/'归档').glob('*/report.html'),reverse=True)
            if reports:self.open(reports[0])
            else:messagebox.showinfo('暂无结果','先运行“校验并归档”或“运行仿真”。')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--self-test',action='store_true')
    parser.add_argument('--ui-smoke',action='store_true');parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    if args.self_test:
        with tempfile.TemporaryDirectory() as d:
            code,result=validate(template_path(),Path(d)/'archive')
            report=Path(result['report'])
            assert report.is_file() and code==0 and result['errors']==0
            result['test_status']='PASS';result['template_exists']=template_path().is_file()
            if args.report:args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        return
    root=tk.Tk();app=Workstation(root)
    if args.ui_smoke:
        root.withdraw();root.update_idletasks();assert len(app.buttons)==10
        if args.report:args.report.write_text(json.dumps({'status':'PASS','buttons':len(app.buttons),'workbook_exists':app.checked_path().is_file()},indent=2),encoding='utf-8')
        root.destroy();return
    root.mainloop()


if __name__=='__main__':main()
