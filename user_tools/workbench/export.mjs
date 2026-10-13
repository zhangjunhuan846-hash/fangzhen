import fs from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const [modulePath,inputPath,outputPath]=process.argv.slice(2);
const {Workbook,SpreadsheetFile}=await import(pathToFileURL(modulePath).href);
const data=JSON.parse(await fs.readFile(inputPath,'utf8'));
const wb=Workbook.create();const col=n=>{let value='';for(;n;n=Math.floor((n-1)/26))value=String.fromCharCode(65+(n-1)%26)+value;return value;};
for(const t of data.schema.tables){
 const s=wb.worksheets.add(t.sheet),rows=data.workspace.tables[t.sheet],end=col(t.fields.length),last=Math.max(104,rows.length+4);
 s.showGridLines=false;s.getRange(`A1:${end}${last}`).format={font:{name:'Microsoft YaHei',size:11,color:'#243547'},columnWidth:20,rowHeight:26};
 s.getRange('A1').values=[[t.sheet]];s.getRange('A1').format.font={name:'Microsoft YaHei',size:16,bold:true,color:'#243C58'};
 s.getRange('A2').values=[[t.note]];s.getRange(`A4:${end}4`).values=[t.fields.map(f=>f[1])];
 s.getRange(`A4:${end}4`).format={fill:'#243C58',font:{name:'Microsoft YaHei',size:11,bold:true,color:'#FFFFFF'},wrapText:true,rowHeight:48};
 if(rows.length)s.getRange(`A5:${end}${rows.length+4}`).values=rows.map(r=>t.fields.map(([key,,typ])=>typ==='derived'?null:r[key]??null));
 for(let i=0;i<t.fields.length;i++){
  const [key, ,typ]=t.fields[i],r=s.getRange(`${col(i+1)}5:${col(i+1)}${last}`);
  if(typ==='fraction'||typ==='derived')r.setNumberFormat('0.0%');
  else if(['number','positive','temperature','signed'].includes(typ))r.setNumberFormat('0.00');
  else if(typ==='id'||typ.startsWith('ref:')||typ==='text')r.setNumberFormat('@');
  if(key==='ds_m2_s'||key.endsWith('diffusivity_m2_s')||key==='i0_A_m2')r.setNumberFormat('0.00E+00');
  if(key==='d002_nm')r.setNumberFormat('0.0000');
  if(typ==='derived'){r.format.fill='#EDF2F7';r.formulas=Array.from({length:last-4},(_,i)=>{const n=i+5;return [`=IF(AND(ISNUMBER(D${n}),ISNUMBER(E${n}),D${n}>0),E${n}/D${n},"")`];});}
 }
 s.tables.add(`A4:${end}${last}`,true,'Export_'+data.schema.tables.indexOf(t)).style='TableStyleLight1';
 s.freezePanes.freezeRows(4);s.freezePanes.freezeColumns(1);
}
wb.recalculate();await(await SpreadsheetFile.exportXlsx(wb)).save(outputPath);
