"""Build redistributable browser data from verified CC0 MakeHuman assets.

Usage: python scripts/build_studio_assets.py /path/to/makehuman-source.tar.gz
Source: https://github.com/makehumancommunity/makehuman
No upstream program code is bundled, only explicitly CC0 data.
"""
from pathlib import Path
import hashlib
import json
import sys
import tarfile
import numpy as np

OUT = Path(__file__).resolve().parents[1] / 'app/studio/web/data'
GROUPS = {'armslegs', 'eyes', 'ears', 'mouth', 'nose', 'head', 'cheek', 'neck',
          'chin', 'hip', 'forehead', 'stomach', 'eyebrows', 'pelvis', 'buttocks', 'torso', 'breast'}
PAIRS = [('decr', 'incr'), ('down', 'up'), ('in', 'out'), ('backward', 'forward')]


def parse_base(lines):
    positions, faces, uvs, uv_indices, eyes = [], [], [], [], {'l':set(),'r':set()}
    group=''
    for line in lines:
        if line.startswith('v '):
            positions.append([round(float(x)*.1,7) for x in line.split()[1:4]])
        elif line.startswith('vt '):
            uvs.append([float(x) for x in line.split()[1:3]])
        elif line.startswith('g '):
            group=line.split()[1]
        elif line.startswith('f '):
            parts=[x.split('/') for x in line.split()[1:]]
            indices=[int(x[0])-1 for x in parts]
            if group=='body':
                texture_indices=[int(x[1])-1 for x in parts]
                for i in range(1,len(indices)-1):
                    faces.extend([indices[0],indices[i],indices[i+1]])
                    uv_indices.extend([texture_indices[0],texture_indices[i],texture_indices[i+1]])
            for side in eyes:
                if group==f'helper-{side}-eye':eyes[side].update(indices)
    return positions,faces,uvs,uv_indices,eyes


def main(archive):
    OUT.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as tar:
        files = {m.name.split('/makehuman/data/', 1)[1]: m for m in tar.getmembers()
                 if '/makehuman/data/' in m.name and m.isfile()}
        provenance = []

        def read(name):
            raw = tar.extractfile(files[name]).read()
            text = raw.decode('utf-8')
            if 'released as CC0' not in text:
                raise ValueError(f'CC0 declaration missing: {name}')
            provenance.append({'path': name, 'sha256': hashlib.sha256(raw).hexdigest()})
            return text

        lines = read('3dobjs/base.obj').splitlines()
        positions,faces,uvs,uv_indices,eyes=parse_base(lines)

        def delta(name):
            result = []
            for line in read(name).splitlines():
                if not line.strip() or line.startswith('#'):
                    continue
                i, *v = line.split()
                result.append([int(i), *[round(float(x)*.1, 7) for x in v]])
            return result

        bases = {}
        for sex in ('female', 'male'):
            bases[sex] = []
            for population in ('caucasian', 'african', 'asian'):
                bases[sex].append(delta(f'targets/macrodetails/{population}-{sex}-young.target'))
        controls = []
        for path in sorted(files):
            parts = path.split('/')
            if len(parts) != 3 or parts[0] != 'targets' or parts[1] not in GROUPS:
                continue
            if parts[1] == 'breast' and not parts[2].startswith(('breast-dist-', 'breast-trans-', 'breast-volume-vert-')):
                continue
            if parts[2].startswith('bulge-'):
                continue
            for negative, positive in PAIRS:
                suffix = f'-{negative}.target'
                if not path.endswith(suffix):
                    continue
                stem = path[:-len(suffix)]
                other = f'{stem}-{positive}.target'
                if other not in files:
                    continue
                identifier = stem.split('/')[-1]
                # Translation axes share a stem upstream. IDs must identify
                # one operation, otherwise a width edit also moves height/depth.
                if negative != 'decr':
                    identifier += {'down':'-vertical','in':'-lateral','backward':'-depth'}[negative]
                label = identifier.replace('l-', 'Left ', 1) if identifier.startswith('l-') else identifier
                label = label.replace('r-', 'Right ', 1) if label.startswith('r-') else label
                label = label.replace('-', ' ').replace('horiz', 'width').replace('vert', 'height')
                controls.append({'id': identifier, 'label': label.capitalize(), 'group': parts[1], 'source_kind': 'authored',
                                 'min': -100, 'max': 100, 'negative': delta(path), 'positive': delta(other)})

        def add_pair(identifier, label, category, negative, positive, description):
            controls.append({'id':identifier,'label':label,'group':category,'source_kind':'authored',
                'min':-100,'max':100,'negative':delta(negative),'positive':delta(positive),'description':description})

        prefix = 'targets/breast/female-young-averagemuscle-averageweight-'
        add_pair('breast-size', 'Breast size', 'breast', prefix+'mincup-averagefirmness.target',
                 prefix+'maxcup-averagefirmness.target', 'Authored adult volume target. Garments follow the resulting surface.')
        add_pair('breast-firmness', 'Breast contour firmness', 'breast', prefix+'averagecup-minfirmness.target',
                 prefix+'averagecup-maxfirmness.target', 'Shape contour only; this is not soft-tissue physics.')
        renames = {'breast-dist':'Breast spacing', 'breast-trans-vertical':'Breast lift',
                   'breast-volume-vert-vertical':'Breast vertical fullness', 'buttocks-volume':'Glute size'}
        for control in controls:
            control['label'] = renames.get(control['id'], control['label'])

        # Derive localized sculpt deltas from the spatial support of an authored
        # volume target. These are explicitly labeled derived controls. They
        # affect the selected region instead of scaling the complete torso.
        neutral = np.array(positions, dtype=float)
        for target in bases['female']:
            a = np.array(target); neutral[a[:,0].astype(int)] += a[:,1:]/3
        for source_id, category, prefix_id, label in [('breast-size','breast','breast','Breast'),
                                                      ('buttocks-volume','buttocks','glute','Glute')]:
            source = next(c for c in controls if c['id']==source_id)
            support = {}
            for target in (source['negative'],source['positive']):
                for index, *v in target:
                    support[index] = max(support.get(index,0), float(np.linalg.norm(v)))
            indices = np.array(sorted(support)); coords=neutral[indices]
            weights=np.array([support[i] for i in indices]);weights /= max(weights.max(),1e-8)
            weights=np.sqrt(weights)
            center=(coords*weights[:,None]).sum(axis=0)/weights.sum()
            span=max(np.ptp(coords[:,1]),1e-6)
            vertical=np.clip((coords[:,1]-center[1])/span*3,-1,1)
            side=np.tanh(coords[:,0]/.035)
            fields = {
                'projection':np.column_stack([weights*0,weights*0,weights*(.055 if category=='breast' else -.065)]),
                'width':np.column_stack([weights*side*.035,weights*0,weights*0]),
                'upper-fullness':np.column_stack([weights*0,weights*0,weights*np.clip(vertical,0,1)*(.04 if category=='breast' else -.045)]),
                'lower-fullness':np.column_stack([weights*0,weights*0,weights*np.clip(-vertical,0,1)*(.04 if category=='breast' else -.045)]),
            }
            if category=='buttocks':
                fields['lift']=np.column_stack([weights*0,weights*.035,weights*0])
                fields['roundness']=np.column_stack([weights*side*.018,weights*vertical*.015,weights*-.035])
            for name, movement in fields.items():
                d=[[int(i),*[round(float(v),7) for v in delta_v]] for i,delta_v in zip(indices,movement)]
                controls.append({'id':f'{prefix_id}-{name}','label':f'{label} {name.replace("-"," ")}',
                    'group':category,'source_kind':'derived','min':-100,'max':100,'positive':d,
                    'negative':[[i,-x,-y,-z] for i,x,y,z in d],
                    'description':'Localized sculpt delta. Combinations require fit inspection; no tissue simulation.'})
            for side_id,side_label,direction in [('l','Left',1),('r','Right',-1)]:
                split={}
                for polarity in ('negative','positive'):
                    split[polarity]=[[i,*[round(v*max(0,float(np.tanh(neutral[i,0]/.035))*direction),7) for v in values]]
                                     for i,*values in source[polarity]]
                controls.append({'id':f'{side_id}-{prefix_id}-size','label':f'{side_label} {label.lower()} size',
                    'group':category,'source_kind':'derived','min':-100,'max':100,**split,
                    'description':'Independent regional size adjustment. Disable symmetry linking to edit one side.'})
        ids=[c['id'] for c in controls]
        if len(ids)!=len(set(ids)):
            raise ValueError('Duplicate control IDs')
        payload = {'license': 'CC0-1.0', 'source': 'MakeHuman community, hm08',
                   'positions': positions, 'indices': faces, 'uvs':uvs,'uv_indices':uv_indices,
                   'eyes': {s: sorted(v) for s,v in eyes.items()},
                   'bases': bases, 'controls': controls,
                   'limitations': ['Static mesh; no rig or animation', 'Extreme combinations are experimental',
                                   'Surface clothing templates are not cloth simulation']}
        (OUT/'human.json').write_text(json.dumps(payload, separators=(',', ':')))
        (OUT/'provenance.json').write_text(json.dumps({'source': 'https://github.com/makehumancommunity/makehuman',
            'license': 'CC0-1.0', 'assets': provenance}, indent=2))
        for member in tar.getmembers():
            if member.name.endswith('/LICENSE.CC0') or member.name.endswith('/license.txt'):
                raw = tar.extractfile(member).read() if member.isfile() else b''
                if b'CC0' in raw:
                    (OUT/'LICENSE-CC0.txt').write_bytes(raw)
                    break
        print(f'{len(controls)} paired shape controls; {len(faces)//3} body triangles; {len(provenance)} CC0 source assets')


if __name__ == '__main__':
    main(sys.argv[1])
