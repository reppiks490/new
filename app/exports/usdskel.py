from __future__ import annotations
from pathlib import Path
import re
from pydantic import BaseModel, Field


class UsdSkelValidationReport(BaseModel):
    path: str
    backend: str
    parsed: bool
    skel_root_count: int = 0
    skeleton_count: int = 0
    animation_count: int = 0
    binding_count: int = 0
    animation_source_count: int = 0
    skeletons_with_joints: int = 0
    skeletons_with_matching_bind_rest: int = 0
    influence_prim_count: int = 0
    invalid_joint_path_count: int = 0
    passed: bool
    production_ready: bool = False
    authoritative: bool = False
    computed_transform_validation: bool = False
    computed_transform_failures: int = 0
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _static_array(text: str, attr_name: str) -> list[str]:
    m = re.search(rf"\b{re.escape(attr_name)}\s*=\s*\[(.*?)\]", text, flags=re.S)
    if not m:
        return []
    body = m.group(1)
    quoted = re.findall(r'"([^"]+)"', body)
    if quoted:
        return quoted
    # Matrix arrays and numeric arrays: count top-level parenthesized matrices/tokens conservatively.
    mats = re.findall(r"\([^\n]*?\)", body)
    if mats:
        return mats
    return [x.strip() for x in body.split(',') if x.strip()]


def _validate_usda_static(p: Path) -> UsdSkelValidationReport:
    text = p.read_text(encoding='utf-8', errors='replace')
    roots = len(re.findall(r'\bdef\s+SkelRoot\b', text))
    skeleton_blocks = re.findall(r'\bdef\s+Skeleton\s+"[^"]+"\s*\{(.*?)\n\}', text, flags=re.S)
    skeletons = len(skeleton_blocks)
    anims = len(re.findall(r'\bdef\s+SkelAnimation\b', text))
    bindings = len(re.findall(r'\brel\s+skel:skeleton\s*=', text)) + len(re.findall(r'\bskel:skeleton\s*=', text))
    anim_sources = len(re.findall(r'\brel\s+skel:animationSource\s*=', text))
    influence_prims = len(re.findall(r'primvars:skel:jointIndices', text))
    blockers: list[str] = []
    warnings: list[str] = []
    with_joints = 0
    matching = 0
    invalid_joint_paths = 0

    for block in skeleton_blocks:
        joints = _static_array(block, 'uniform token[] joints') or _static_array(block, 'token[] joints')
        bind = _static_array(block, 'uniform matrix4d[] bindTransforms') or _static_array(block, 'matrix4d[] bindTransforms')
        rest = _static_array(block, 'uniform matrix4d[] restTransforms') or _static_array(block, 'matrix4d[] restTransforms')
        if joints:
            with_joints += 1
            invalid_joint_paths += sum(1 for j in joints if not j or j.startswith('/') or '//' in j or j.endswith('/'))
        if joints and bind and rest and len(joints) == len(bind) == len(rest):
            matching += 1
        elif joints:
            warnings.append('A Skeleton declaration does not statically prove matching joints/bindTransforms/restTransforms lengths.')

    if roots == 0: blockers.append('No SkelRoot declaration found.')
    if skeletons == 0: blockers.append('No Skeleton declaration found.')
    if bindings == 0: blockers.append('No skel:skeleton binding found.')
    if skeletons and with_joints < skeletons: warnings.append('One or more Skeleton declarations have no authored joints array; not production-ready.')
    if invalid_joint_paths: warnings.append(f'{invalid_joint_paths} joint path tokens are malformed for static validation; not production-ready.')
    if skeletons and matching < skeletons:
        warnings.append('Static USDA validation could not prove matching joint, bind-pose, and rest-pose array lengths for every skeleton.')
    if influence_prims == 0:
        warnings.append('No primvars:skel:jointIndices found; this may be valid for rigid bindings but deforming meshes need influence data.')
    warnings.append('Static USDA validation is structural only; install pxr/OpenUSD for authoritative schema and computed-transform validation.')

    return UsdSkelValidationReport(
        path=str(p), backend='usda_static', parsed=True, skel_root_count=roots,
        skeleton_count=skeletons, animation_count=anims, binding_count=bindings,
        animation_source_count=anim_sources, skeletons_with_joints=with_joints,
        skeletons_with_matching_bind_rest=matching, influence_prim_count=influence_prims,
        invalid_joint_path_count=invalid_joint_paths, passed=not blockers,
        production_ready=(not blockers and skeletons > 0 and with_joints == skeletons and matching == skeletons and invalid_joint_paths == 0),
        authoritative=False, computed_transform_validation=False, computed_transform_failures=0,
        blockers=blockers, warnings=warnings,
    )


def validate_usdskel(path: str | Path) -> UsdSkelValidationReport:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(p)
    try:
        from pxr import Usd, UsdSkel  # type: ignore
        stage = Usd.Stage.Open(str(p))
        if not stage:
            return UsdSkelValidationReport(path=str(p), backend='pxr', parsed=False, passed=False, blockers=['USD stage failed to open.'])
        roots = skeletons = anims = bindings = anim_sources = with_joints = matching = influence_prims = invalid_joint_paths = 0
        warnings: list[str] = []
        computed_attempted = False
        computed_failures = 0
        skel_prims = []
        for prim in stage.Traverse():
            t = prim.GetTypeName()
            if t == 'SkelRoot': roots += 1
            elif t == 'Skeleton':
                skeletons += 1
                skel_prims.append(prim)
                skel = UsdSkel.Skeleton(prim)
                joints = list(skel.GetJointsAttr().Get() or [])
                bind = list(skel.GetBindTransformsAttr().Get() or [])
                rest = list(skel.GetRestTransformsAttr().Get() or [])
                if joints: with_joints += 1
                for token in joints:
                    s = str(token)
                    if not s or s.startswith('/') or '//' in s or s.endswith('/'):
                        invalid_joint_paths += 1
                if joints and len(joints) == len(bind) == len(rest):
                    matching += 1
                else:
                    warnings.append(f'Skeleton {prim.GetPath()} has unmatched joints/bind/rest array lengths.')
            elif t == 'SkelAnimation':
                anims += 1
            try:
                api = UsdSkel.BindingAPI(prim)
                if api:
                    if api.GetSkeletonRel().HasAuthoredTargets(): bindings += 1
                    if api.GetAnimationSourceRel().HasAuthoredTargets(): anim_sources += 1
                    ji = api.GetJointIndicesAttr()
                    jw = api.GetJointWeightsAttr()
                    if (ji and ji.HasAuthoredValueOpinion()) or (jw and jw.HasAuthoredValueOpinion()):
                        influence_prims += 1
            except Exception:
                pass
        # When pxr is present, attempt computed skeleton transforms as an additional
        # authoritative runtime check. API differences across OpenUSD versions are
        # contained here; schema parsing remains authoritative even if the optional
        # computed-transform query is unavailable in a given build.
        try:
            cache = UsdSkel.Cache()
            for prim in skel_prims:
                computed_attempted = True
                skel = UsdSkel.Skeleton(prim)
                query = cache.GetSkelQuery(skel)
                if not query or not query.IsValid():
                    computed_failures += 1
                    continue
                try:
                    transforms = query.ComputeJointSkelTransforms(Usd.TimeCode.Default())
                    if transforms is None:
                        computed_failures += 1
                except Exception:
                    computed_failures += 1
        except Exception as exc:
            if skel_prims:
                warnings.append(f'pxr schema validation succeeded, but computed joint transforms could not be evaluated: {exc}')

        blockers: list[str] = []
        if roots == 0: blockers.append('No SkelRoot prim found.')
        if skeletons == 0: blockers.append('No Skeleton prim found.')
        if bindings == 0: blockers.append('No authored skeleton bindings found.')
        production_issues=[]
        if skeletons and with_joints < skeletons: production_issues.append('One or more Skeleton prims have no joints array.')
        if skeletons and matching < skeletons: production_issues.append('One or more Skeleton prims have mismatched joints/bindTransforms/restTransforms lengths.')
        if invalid_joint_paths: production_issues.append(f'{invalid_joint_paths} malformed joint path tokens found.')
        warnings.extend(x + ' Not production-ready.' for x in production_issues)
        if influence_prims == 0: warnings.append('No joint-index/weight primvars were authored; confirm whether all bindings are intentionally rigid.')
        return UsdSkelValidationReport(
            path=str(p), backend='pxr', parsed=True, skel_root_count=roots,
            skeleton_count=skeletons, animation_count=anims, binding_count=bindings,
            animation_source_count=anim_sources, skeletons_with_joints=with_joints,
            skeletons_with_matching_bind_rest=matching, influence_prim_count=influence_prims,
            invalid_joint_path_count=invalid_joint_paths, passed=not blockers,
            production_ready=(not blockers and not production_issues and (not computed_attempted or computed_failures == 0)),
            authoritative=True,
            computed_transform_validation=computed_attempted,
            computed_transform_failures=computed_failures,
            blockers=blockers, warnings=warnings,
        )
    except ImportError:
        if p.suffix.lower() != '.usda':
            return UsdSkelValidationReport(
                path=str(p), backend='unavailable', parsed=False, passed=False,
                authoritative=False, computed_transform_validation=False, computed_transform_failures=0,
                blockers=['pxr USD bindings unavailable for binary USD/USDC/USDZ validation.'],
            )
        return _validate_usda_static(p)
