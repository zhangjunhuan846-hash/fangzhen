"""Inspect or fetch individual ZIP entries by HTTP range without full download.

The publisher publishes a single archive MD5, not file-level hashes. Extracted
entries are verified by ZIP CRC and recorded with local SHA-256; this cannot
independently verify the full archive's publisher MD5.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import requests
import zipfile
import re
import struct
import zlib
from concurrent.futures import ThreadPoolExecutor,as_completed

URL='https://borealisdata.ca/api/access/datafile/1187117'
SIZE=705071445
ROOT=Path('data/public/tesla_soc_benchmark_v3')


class RemoteArchive(io.RawIOBase):
    def __init__(self):
        self.position=0;self.session=requests.Session()
    def seekable(self):return True
    def readable(self):return True
    def tell(self):return self.position
    def seek(self,offset,whence=0):
        position=offset if whence==0 else self.position+offset if whence==1 else SIZE+offset
        if position<0:raise ValueError('Negative seek')
        self.position=position;return position
    def read(self,size=-1):
        if size is None or size<0:size=SIZE-self.position
        size=min(size,SIZE-self.position)
        if size<=0:return b''
        lo=self.position;hi=lo+size-1
        response=self.session.get(URL,headers={'Range':f'bytes={lo}-{hi}'},timeout=120)
        if response.status_code!=206 or len(response.content)!=size:raise IOError('Archive server did not honor requested byte range')
        self.position+=size
        return response.content


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--list',action='store_true');parser.add_argument('--fetch',action='store_true');parser.add_argument('--holdout2',action='store_true');args=parser.parse_args()
    ROOT.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(RemoteArchive()) as archive:
        entries=archive.infolist()
        listing=[{'name':i.filename,'size':i.file_size,'compressed_size':i.compress_size,'crc32':f'{i.CRC:08x}'} for i in entries if not i.is_dir()]
        (ROOT/'archive_index.json').write_text(json.dumps(listing,ensure_ascii=False,indent=2),encoding='utf8')
        print('Archive entries:',len(listing))
        if args.list:
            for item in listing[:100]:print(item['name'],item['size'])
        if not args.fetch and not args.holdout2:return
        # Predeclared calibration/validation split. Nothing from the blind set is accessed.
        selected=[]
        for cell in (('m1000',) if args.holdout2 else ('m80','m448-N','m1000')):
            for temp in ('-20C','-10C','0C','10C','25C','40C'):
                group=[i for i in entries if i.filename.startswith(f'{cell}/{temp}/') and i.filename.endswith('.mat')]
                patterns=([(f'drive{n}',fr'^\d+_REORDERED{n}_') for n in (7,8)] if args.holdout2 else [('hppc',r'^\d+_HPPC_'),('c20',r'^\d+_C_20_Discharge_Charge_'),
                          ('capacity40',r'^\d+_40C_Discharge_')]+[(f'drive{n}',fr'^\d+_REORDERED{n}_') for n in (1,2,5,6)]
                          )
                for role,pat in patterns:
                    found=sorted([i for i in group if re.match(pat,Path(i.filename).name)],key=lambda x:x.filename)
                    if not found:raise ValueError(f'No file for {cell}/{temp}/{role}')
                    selected.append((cell,temp,role,found[0]))
        def fetch(item):
            cell,temp,role,info=item
            target=ROOT/cell/temp/(role+'.mat');target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists():
                raw=target.read_bytes()
                if len(raw)==info.file_size and zlib.crc32(raw)&0xffffffff==info.CRC:
                    return {'cell':cell,'temperature':temp,'role':role,'archive_name':info.filename,'path':target.as_posix(),
                            'size':len(raw),'crc32':f'{info.CRC:08x}','sha256':hashlib.sha256(raw).hexdigest()}
            # Local ZIP header followed by the complete compressed payload.
            start=info.header_offset;end=min(SIZE-1,start+30+4096+info.compress_size)
            response=requests.get(URL,headers={'Range':f'bytes={start}-{end}'},timeout=120)
            if response.status_code!=206:raise IOError('Range retrieval failed')
            body=response.content
            header=struct.unpack('<IHHHHHIIIHH',body[:30])
            if header[0]!=0x04034b50:raise ValueError('Invalid local ZIP header')
            offset=30+header[-2]+header[-1];compressed=body[offset:offset+info.compress_size]
            if len(compressed)!=info.compress_size:raise ValueError('ZIP entry header larger than range allowance')
            raw=zlib.decompress(compressed,-15) if info.compress_type==8 else compressed if info.compress_type==0 else None
            if raw is None or len(raw)!=info.file_size or zlib.crc32(raw)&0xffffffff!=info.CRC:raise ValueError('ZIP entry CRC or length mismatch')
            target.write_bytes(raw)
            return {'cell':cell,'temperature':temp,'role':role,'archive_name':info.filename,'path':target.as_posix(),
                    'size':len(raw),'crc32':f'{info.CRC:08x}','sha256':hashlib.sha256(raw).hexdigest()}
        result=[];errors=[]
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures={pool.submit(fetch,item):item for item in selected}
            for number,future in enumerate(as_completed(futures),1):
                try:result.append(future.result())
                except Exception as exc:errors.append({'name':futures[future][3].filename,'error':str(exc)})
                if number%18==0:print(f'{number}/{len(selected)} files attempted; failures={len(errors)}',flush=True)
        manifest={'source':'https://doi.org/10.5683/SP3/ZVTR4B','license':'CC BY 4.0',
                  'archive_id':1187117,'archive_size':SIZE,'publisher_archive_md5':'b05b8bf5bb38d8df280c8a67371a1f74',
                  'integrity_scope':'ZIP CRC verified per extracted file; local SHA256 recorded; full archive MD5 not independently verified',
                  'files':sorted(result,key=lambda x:(x['cell'],x['temperature'],x['role'])),'failures':errors}
        (ROOT/('manifest_holdout2.json' if args.holdout2 else 'manifest.json')).write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
        if errors:raise RuntimeError(f'Archive extraction failed: {errors}')


if __name__=='__main__':main()
