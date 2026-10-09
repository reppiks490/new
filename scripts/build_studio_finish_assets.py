"""Convert attributed MakeHuman asset files to the browser fitting format.

Usage: python scripts/build_studio_finish_assets.py SOURCE_DIRECTORY
Keep the original source and its actual license alongside the converted files.
This script does not claim that older AGPL assets are CC0.
"""
from pathlib import Path
import hashlib
import json
import shutil
import sys
import zipfile
from PIL import Image

OUT=Path(__file__).resolve().parents[1]/'app/studio/web/data/quality-assets'
SELECTION=[('hair','long01','Long, center part'),('hair','bob02','Rounded bob'),
           ('clothes','female_casualsuit01','Denim & layered top'),
           ('clothes','female_elegantsuit01','Pinstripe & skirt'),
           ('clothes','shoes01','Lace-up shoes'),('clothes','shoes02','Classic shoes'),
           ('eyelashes','eyelashes01','Natural lashes')]
SOURCE_URL='https://github.com/dmaugis/makehuman-py3-assets'


def parse_obj(path):
    positions=[];uvs=[];indices=[];uv_indices=[]
    for line in path.read_text().splitlines():
        p=line.split()
        if not p:continue
        if p[0]=='v':positions.append([float(v) for v in p[1:4]])
        elif p[0]=='vt':uvs.append([float(v) for v in p[1:3]])
        elif p[0]=='f':
            face=[x.split('/') for x in p[1:]]
            for k in range(1,len(face)-1):
                for v in (face[0],face[k],face[k+1]):
                    indices.append(int(v[0])-1);uv_indices.append(int(v[1])-1)
    return positions,uvs,indices,uv_indices


def parse_binding(path):
    bindings=[];scales={};hidden=[];mode=None
    for line in path.read_text().splitlines():
        p=line.split()
        if not p or p[0].startswith('#'):continue
        if p[0].endswith('_scale'):
            scales[p[0][0]]=[int(p[1]),int(p[2]),float(p[3])]
        elif p[0]=='verts':mode='verts'
        elif p[0]=='delete_verts':mode='delete'
        elif p[0][0].isdigit() and mode=='verts':
            if len(p)==1:bindings.append([int(p[0]),0,0,1,0,0,0,0,0])
            elif len(p)==9:bindings.append([*[int(v) for v in p[:3]],*[float(v) for v in p[3:]]])
            else:raise ValueError(f'Unsupported binding {line}')
        elif p[0][0].isdigit() and mode=='delete':
            i=0
            while i<len(p):
                if i+2<len(p) and p[i+1]=='-':hidden.extend(range(int(p[i]),int(p[i+2])+1));i+=3
                else:hidden.append(int(p[i]));i+=1
    return bindings,scales,hidden


def build(root):
    root=Path(root);OUT.mkdir(parents=True,exist_ok=True)
    entries=[];hashes=[]
    def texture(path,stem):
        image=Image.open(path);image.load()
        image.thumbnail((2048,2048),Image.Resampling.LANCZOS)
        alpha=image.mode in ('RGBA','LA') and image.getextrema()[-1][0]<255
        name=stem+('.png' if alpha or 'normal' in stem else '.jpg')
        if name.endswith('.jpg'):image.convert('RGB').save(OUT/name,quality=94,subsampling=0)
        else:image.save(OUT/name,optimize=True)
        return name,alpha
    for folder,name,label in SELECTION:
        directory=root/'base'/folder/name
        obj=directory/(name+'.obj');binding=directory/(name+'.mhclo');mat=directory/(name+'.mhmat')
        text=binding.read_text()+mat.read_text()+obj.read_text()[:3000]
        license_id='CC0-1.0' if 'released as CC0' in text else 'AGPL-3.0-or-later'
        if license_id.startswith('AGPL') and 'AGPL' not in text:raise ValueError(f'Unverified license: {name}')
        positions,uvs,indices,uv_indices=parse_obj(obj)
        bindings,scales,hidden=parse_binding(binding)
        if len(bindings)!=len(positions):raise ValueError(f'Binding count mismatch: {name}: {len(bindings)} != {len(positions)}')
        material={}
        for line in mat.read_text().splitlines():
            p=line.split()
            if not p:continue
            if p[0] in ('diffuseTexture','normalmapTexture'):
                key='diffuse' if p[0]=='diffuseTexture' else 'normal'
                material[key],alpha=texture(directory/p[1],name+'_'+key)
                if key=='diffuse':material['alpha']=alpha
        payload={'id':name,'label':label,'kind':'shoes' if name.startswith('shoes') else {'clothes':'garment','eyelashes':'lashes'}.get(folder,folder),
                 'license':license_id,'source':SOURCE_URL,'uvs':uvs,'indices':indices,'uv_indices':uv_indices,
                 'bindings':bindings,'scales':scales,'hidden_vertices':hidden,'material':material}
        file=name+'.json';(OUT/file).write_text(json.dumps(payload,separators=(',',':')))
        entries.append({k:payload[k] for k in ['id','label','kind','license','source']}|{'file':file})
        thumb=directory/(name+'.thumb')
        if thumb.exists():Image.open(thumb).save(OUT/(name+'_thumb.png'))
    textures={}
    for sex in ['female','male']:
        path=root/f'base/skins/textures/young_lightskinned_{sex}_diffuse2.png'
        textures['skin_'+sex]=texture(path,'skin_'+sex)[0]
    for path in sorted(root.rglob('*')):
        if path.is_file():hashes.append({'path':path.relative_to(root).as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    # Preserve corresponding source, texture originals, and copyright notices.
    with zipfile.ZipFile(OUT/'source-assets.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for path in root.rglob('*'):
            if path.is_file():archive.write(path,path.relative_to(root))
    shutil.copyfile(root/'LICENSE',OUT/'LICENSE-AGPL-3.0.txt')
    (OUT/'index.json').write_text(json.dumps({'version':1,'assets':entries,'textures':textures,'source':SOURCE_URL,
       'source_archive':'source-assets.zip','license':'AGPL-3.0-or-later','hashes':hashes},indent=2))
    (OUT/'CREDITS.md').write_text('''# Character finish assets

These assets come from the MakeHuman asset collection mirrored at
https://github.com/dmaugis/makehuman-py3-assets.
Copyright notices include Data Collection AB, Joel Palmius, and Jonas Hauquier
(2016); original per-file notices are preserved in source-assets.zip.

These older accessory, material and texture files are distributed under
AGPL-3.0-or-later as declared by their source. They are **not** labeled CC0.
LICENSE-AGPL-3.0.txt and the corresponding original source are bundled here.
The body mesh and shape targets elsewhere in this app are separately CC0.

Changes: accessory meshes and hm08 bindings converted to browser JSON;
textures resized to at most 2048 pixels and opaque color textures encoded as
JPEG. Conversion code: scripts/build_studio_finish_assets.py in the app source.
''')
    print(json.dumps({'assets':len(entries),'output':str(OUT),'bytes':sum(p.stat().st_size for p in OUT.iterdir())}))

if __name__=='__main__':build(sys.argv[1])
